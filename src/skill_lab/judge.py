"""Cai gi mot model phai doc, vi mot check tat dinh khong doc duoc -- va chi cai do.

Cau hoi o day la **nhi phan**, khong bao gio la mot thang xep hang. Mot cau hoi "ben nao hay hon"
moi dung dung cac thien vi da biet cua judge: van phong cung ho model, cau tra loi dai, va vi tri
trong mot so sanh cap. Mot cau hoi co/khong ve mot su kien cu the thi it cho cho nhung thien vi do
bam vao.

Judge khong bao gio chay skill, khong bao gio sua duoc trace, va khong bao gio nhin thay cac check
tat dinh. No doc dung hai thu: dau ra cuoi cung cua actor, va mot ban tom tat trajectory -- ca hai
deu sinh ra sau khi actor da xong han.

Model duoc ghim o cau hinh va mac dinh la mot ho khac voi actor. Mot judge cung ho voi thu no dang
cham la mot judge dang cham chinh giong minh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from skill_lab.agent import ask
from skill_lab.case import JudgeSpec
from skill_lab.config import JudgeConfig
from skill_lab.model import FAIL, PASS, CheckResult, Step, call_steps


class JudgeError(RuntimeError):
    """Khong goi duoc judge, hoac no tra ve thu khong dung duoc."""


@dataclass(frozen=True)
class JudgeAnswer:
    id: str
    question: str
    verdict: bool
    why: str


def trace_summary(steps: Sequence[Step], *, limit: int = 120) -> str:
    """Trajectory rut gon du de tra loi mot cau hoi ve hanh vi, khong hon.

    Cat o `limit` buoc vi mot trajectory dai hon the se day phan dau ra khoi cua so ma judge thuc
    su doc ky, va mot judge doc luot la mot judge doan.
    """
    lines = []
    for step in call_steps(steps)[:limit]:
        actor = step.actor
        payload = step.command or ", ".join(step.paths)
        lines.append(f"{step.index}. {step.tool} [{actor}] {payload[:160]}")
    return "\n".join(lines)


def _prompt(question: str, *, skill: str, actor_output: str, summary: str) -> str:
    return f"""Ban dang cham mot agent vua chay skill `/{skill}` trong mot fixture cach ly, da ket
thuc. Ban KHONG chay lai skill, KHONG sua duoc gi -- chi doc hai thu duoi day roi tra loi mot cau
hoi nhi phan ve no.

Cau hoi: {question}

Tra loi CHI mot dong JSON, khong them chu nao khac, khong markdown fence:
{{"verdict": true hoac false, "why": "mot cau ngan giai thich"}}

--- ket qua cuoi cung cua agent ---
{actor_output}

--- tom tat trajectory, theo thu tu da xay ra ---
{summary}
"""


def _parse(text: str) -> dict:
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        raise JudgeError(f"khong co object JSON trong cau tra loi cua judge: {text[:200]!r}")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"cau tra loi cua judge khong phai JSON hop le: {exc}") from exc
    if not isinstance(payload, dict) or "verdict" not in payload:
        raise JudgeError(f"cau tra loi cua judge khong co `verdict`: {stripped[:200]!r}")
    return payload


def ask_one(
    spec: JudgeSpec,
    *,
    skill: str,
    actor_output: str,
    summary: str,
    config: JudgeConfig,
    call: Callable[..., str] = ask,
    cwd: Path | None = None,
) -> JudgeAnswer:
    """Mot cau hoi, mot lan goi. `call` tiem vao duoc de test duong dung prompt va duong phan tich
    ma khong bao gio cham toi mot model that -- mot bo do phai kiem duoc voi chi phi bang khong,
    va mot lan goi judge thi khong mien phi."""
    reply = call(
        _prompt(spec.question, skill=skill, actor_output=actor_output, summary=summary),
        cli=config.cli,
        model=config.model,
        timeout=config.timeout_seconds,
        cwd=cwd,
    )
    payload = _parse(reply)
    return JudgeAnswer(
        id=spec.id,
        question=spec.question,
        verdict=bool(payload["verdict"]),
        why=str(payload.get("why") or ""),
    )


def ask_all(
    specs: Sequence[JudgeSpec],
    *,
    skill: str,
    actor_output: str,
    steps: Sequence[Step],
    config: JudgeConfig,
    call: Callable[..., str] = ask,
    cwd: Path | None = None,
) -> list[JudgeAnswer]:
    summary = trace_summary(steps)
    return [
        ask_one(
            spec,
            skill=skill,
            actor_output=actor_output,
            summary=summary,
            config=config,
            call=call,
            cwd=cwd,
        )
        for spec in specs
    ]


def as_checks(answers: Sequence[JudgeAnswer]) -> list[CheckResult]:
    """Ket qua judge doc nhu cac check khac, nhung mang `deterministic=False`.

    Cung mot bang, va mot cot noi ro cai nao dua duoc vao. `compare.py` xep hang theo cot do: mot
    khac biet do check tat dinh chi ra nang hon mot khac biet do judge chi ra, va gop chung lam mot
    la cach mot bo do bat dau tin vao chinh tieng on cua no.
    """
    return [
        CheckResult.of(
            PASS if a.verdict else FAIL,
            id=a.id,
            kind="judge",
            why=a.why,
            category="skill",
            deterministic=False,
        )
        for a in answers
    ]
