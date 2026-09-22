"""Chay mot luot agent headless, va lay ve nhung con so ma envelope cua CLI von da co.

Hai thu dang noi o day.

**Mot: exit khac 0 la mot KET QUA, khong phai mot su co.** Nguyen nhan pho bien nhat la cham tran
`--max-turns`, va lan chay do van ghi day du mot trace: no da doc rule, da mo task, da lam viec,
chi la het ngan sach truoc khi ket thuc. Nem cai do di la vut mat hien vat dat nhat ma lan chay
tao ra, va de nguoi dung khong con cach nao nhin xem skill di duoc toi dau. Nen ham nay tra ve
ket qua kem ma exit, va nguoi goi cham thu no co.

**Hai: chi phi, thoi gian va so turn duoc lay, khong bi bo.** `--output-format json` tra san
`total_cost_usd`, `duration_ms`, `num_turns`, `usage`. Mot bo do doc `result` roi vut phan con lai
se khong bao gio tra loi duoc cau hoi "candidate nay dat hon bao nhieu" -- va do chinh la cau hoi
ngan mot diem so cao hon tu tro thanh mot quyet dinh promote sai.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from skill_lab.config import ActorConfig
from skill_lab.fixture import TRACE_ENV


class AgentError(Exception):
    """Khong goi duoc CLI, hoac no tra ve thu khong doc noi."""


@dataclass
class AgentResult:
    output: str = ""
    exit_code: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def completed(self) -> bool:
        return self.exit_code == 0


def cli_command(binary: str) -> str:
    """Duong dan toi mot CLI agent cuc bo, phan giai theo dung cach Windows can.

    npm cai cac CLI nay thanh ca `.ps1` lan `.cmd`. Khi PATHEXT liet ke `.PS1` truoc, mot lenh
    `shutil.which` tran tra ve shim PowerShell, thu ma `CreateProcess` khong chay duoc -- no bao
    `[WinError 2] The system cannot find the file specified`, mot thong bao day moi nguoi di tim
    mot ban cai thieu thay vi mot shim khong chay duoc.
    """
    if platform.system() == "Windows":
        found = shutil.which(f"{binary}.cmd")
        if found:
            return found
    found = shutil.which(binary)
    if not found:
        raise AgentError(
            f"khong thay CLI `{binary}` tren PATH. Cai no va chay `{binary}` mot lan de dang nhap."
        )
    return found


def _envelope(stdout: str) -> dict[str, Any]:
    payload = json.loads(stdout)
    if isinstance(payload, list):
        payload = next((r for r in payload if isinstance(r, dict) and "result" in r), {})
    return payload if isinstance(payload, dict) else {}


def run(
    prompt: str,
    *,
    cwd: Path,
    actor: ActorConfig,
    trace_path: Path,
    model: str = "",
    effort: str = "",
    system_prompt: str = "",
    on_poll: Callable[[], None] | None = None,
) -> AgentResult:
    """Mot luot `claude -p`, cwd ghim vao fixture.

    `SKILL_LAB_TRACE` la thu duy nhat bat hook len -- khong dat o moi phien khac, dat o day toi mot
    duong dan ben trong fixture nen khong gi lan chay nay ghi ra thoat duoc khoi do.
    """
    argv = [
        cli_command(actor.cli),
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        model or actor.model,
        "--permission-mode",
        actor.permission_mode,
        "--max-turns",
        str(actor.max_turns),
    ]
    # Chi truyen `--effort` khi co gia tri. Cung mot model o hai muc effort la hai cau hinh khac
    # nhau, va `RunRecord.effort` ghi lai dung gia tri da truyen -- mot truong rong nghia la khong
    # truyen gi va de CLI tu chon, chu khong phai mot muc mac dinh nao do ma bo do tu bia ra.
    if effort:
        argv += ["--effort", effort]
    if system_prompt:
        argv += ["--append-system-prompt", system_prompt]

    env = dict(os.environ)
    env[TRACE_ENV] = str(trace_path)

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + actor.timeout_seconds
    while proc.poll() is None:
        if on_poll:
            on_poll()
        if time.monotonic() > deadline:
            proc.kill()
            proc.communicate()
            return AgentResult(
                output=f"[actor bi giet sau {actor.timeout_seconds}s]",
                exit_code=124,
            )
        time.sleep(0.3)
    stdout, stderr = proc.communicate()
    if on_poll:
        on_poll()

    try:
        envelope = _envelope(stdout)
    except json.JSONDecodeError:
        detail = (stderr or "").strip() or (stdout or "").strip()
        if proc.returncode != 0:
            return AgentResult(
                output=f"[actor exit {proc.returncode}] {detail[:400]}", exit_code=proc.returncode
            )
        raise AgentError(f"khong doc duoc envelope JSON cua CLI; nhan {stdout[:200]!r}")

    return AgentResult(
        output=str(envelope.get("result") or ""),
        exit_code=proc.returncode,
        cost_usd=float(envelope.get("total_cost_usd") or 0.0),
        duration_ms=int(envelope.get("duration_ms") or 0),
        num_turns=int(envelope.get("num_turns") or 0),
        usage=envelope.get("usage") or {},
    )


def ask(prompt: str, *, cli: str, model: str, timeout: int = 180, cwd: Path | None = None) -> str:
    """Mot prompt vao, van ban cua model ra. Dung auth cua chinh CLI cuc bo; khong doc API key.

    Chi dan di vao **luot user**, khong bao gio vao `--system-prompt`. Cac CLI gan day coi system
    prompt la mot dau vao trong nhieu dau vao va van chen them context cua thu muc lam viec, den
    luc do mot payload tran khong co menh lenh se duoc tra loi kieu tro chuyen thay vi duoc thi
    hanh.
    """
    argv = [
        cli_command(cli),
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
    ]
    proc = subprocess.run(
        argv,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        cwd=str(cwd) if cwd else None,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise AgentError(f"{cli} -p exit {proc.returncode}: {detail[:400]}")
    envelope = _envelope(proc.stdout)
    return str(envelope.get("result") or proc.stdout)
