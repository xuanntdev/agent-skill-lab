#!/usr/bin/env python3
"""Hook ghi trajectory. Khong phu thuoc gi ngoai thu vien chuan, va khong bao gio chan.

Cai vao `PreToolUse` va `PostToolUse` voi matcher `*`. `skill_lab/fixture.py` tu lam viec do ben
trong fixture; file nay duoc chep nguyen vao fixture nen no phai dung duoc mot minh -- khong
`import skill_lab`, khong sys.path, khong venv. Mot hook goi bang `python` tran hiem khi thay duoc
moi truong da cai package.

**DONG LOGIC DAU TIEN la toan bo cau chuyen chi phi**: khong co `SKILL_LAB_TRACE` thi khong lam gi
ca -- khong stat, khong import, khong doc stdin. Moi phien binh thuong deu khong dat bien nay, nen
hook khong ton gi cua no.

**Khong bao gio raise, luon exit 0.** Mot hook lam ket lan chay ma no ton tai de quan sat thi bien
chinh phep do thanh bien gay nhieu, te hon la khong do. Cac gate khac (neu workspace co) van chay
tren cung su kien va quyet dinh doc lap; mot lan bi chan van duoc ghi y het mot lan duoc cho qua --
`blocked` la mot du kien, khong phai mot cho trong.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

TRACE_ENV = "SKILL_LAB_TRACE"

#: Khoa trong `tool_input` duoc ghi lai lam duong dan, mot cach de dat. `command` KHONG nam trong
#: day: no di vao truong `command` rieng. Bo do truoc gop ca hai vao mot truong, va hau qua la moi
#: tieu chi hoi "co ghi vao thu muc X khong" deu khong phan biet duoc mot lenh ghi that voi mot
#: dong `echo` tinh co co ten X trong do.
PATH_KEYS = ("file_path", "filePath", "notebook_path", "path", "dir")

#: Tool chay lenh shell. Dong lenh duoc giu nguyen ven, khong bao gio bi phan tich de moc duong
#: dan an trong do -- "de dat" o day nghia la chi lay nguyen ca chuoi duoi khoa cua no.
COMMAND_KEYS = ("command",)

#: Doc de nhan ra mot Grep/Glob rong, va chi de the.
QUERY_KEYS = ("pattern", "glob")


def _digest(tool_input: dict) -> str:
    """Van tay ngan, on dinh cua tham so, ma khong luu chinh tham so.

    16 ky tu hex du de phan biet hai call trong mot lan chay; trace duoc doc boi mot bo cham so
    cac row voi nhau, khong boi ai do dao nguoc hash.
    """
    payload = tool_input if isinstance(tool_input, dict) else {}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _paths_of(tool_input: dict) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    found = []
    for key in PATH_KEYS + QUERY_KEYS:
        value = tool_input.get(key)
        if value:
            found.append(str(value))
    return found


def _command_of(tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in COMMAND_KEYS:
        value = tool_input.get(key)
        if value:
            return str(value)
    return ""


def _response_verdict(data: dict) -> tuple[bool | None, bool, str]:
    """`(ok, blocked, detail)` doc tu `tool_response` cua mot su kien PostToolUse.

    Host khong hua mot hinh dang duy nhat cho `tool_response`, nen o day doc de dat va tra `None`
    khi khong chac. `None` nghia la "khong quan sat duoc", va `diagnose.py` doc `None` khac han
    `False`: mot buoc khong ro ket qua khong phai la mot buoc that bai.
    """
    response = data.get("tool_response")
    if response is None:
        return None, False, ""
    if isinstance(response, dict):
        if response.get("interrupted"):
            return False, True, "interrupted"
        if "is_error" in response:
            is_error = bool(response.get("is_error"))
            detail = str(response.get("error") or response.get("stderr") or "")[:300]
            return (not is_error), False, detail
        if "exit_code" in response or "exitCode" in response:
            code = response.get("exit_code", response.get("exitCode"))
            try:
                code = int(code)
            except (TypeError, ValueError):
                return None, False, ""
            return code == 0, False, "" if code == 0 else f"exit {code}"
        return True, False, ""
    if isinstance(response, str):
        lowered = response.lower()
        # Chuoi tu choi cua chinh harness, khong phai cua tool. Day la cach duy nhat nhin thay mot
        # gate da chan tay agent khi hook nay chay canh mot gate khac ma no khong doc duoc.
        blocked = "permission" in lowered and "denied" in lowered
        return (not blocked), blocked, response[:300] if blocked else ""
    return None, False, ""


def _row_of(data: dict) -> dict:
    event_name = str(data.get("hook_event_name") or "")
    tool_input = data.get("tool_input") or {}
    is_post = event_name == "PostToolUse"
    ok, blocked, detail = _response_verdict(data) if is_post else (None, False, "")
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": "tool_result" if is_post else "tool_call",
        "session_id": data.get("session_id") or "",
        # Co-mat-nhung-null tren call cua phien chinh, mot chuoi that tren call cua subagent -- giu
        # thanh hai khoa rieng chu khong gop, de bo cham phan biet duoc "vang mat" voi "rong".
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
        "tool": data.get("tool_name") or "",
        "tool_use_id": data.get("tool_use_id") or "",
        "args_digest": _digest(tool_input),
        "paths": _paths_of(tool_input),
        "command": _command_of(tool_input),
        "ok": ok,
        "blocked": blocked,
        "detail": detail,
    }
    return row


def main() -> int:
    trace_path = os.environ.get(TRACE_ENV)
    if not trace_path:
        return 0

    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    data = json.loads(raw)
    if not isinstance(data, dict):
        return 0

    path = Path(trace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_row_of(data), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
