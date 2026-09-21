"""Doc lai file trace ma hook da ghi.

Mot dong JSON mot su kien, va module nay khong bao gio bia ra mot truong ma hook khong ghi. Do la
toan bo hop dong giua hai file: `hooks/trace_hook.py` ghi, `trace.py` doc, va khi mot ben doi hinh
dang thi ben kia vo ngay chu khong am tham doc lech.

**Vi sao trace phai den tu hook chu khong tu agent.** Mot agent tu viet bao cao ve chinh no la mot
agent tu cham chinh no: no noi "toi da doc rule truoc khi ghi", va khong co gi mau thuan duoc voi
cau do. Mot `PreToolUse` hook nhin thay moi tool call bat ke agent ke lai the nao, nen thu tu ma
`verify.py` doc la thu tu that su da xay ra.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"


class TraceError(Exception):
    """File trace khong dung hinh dang ma `trace_hook.py` ghi ra."""


@dataclass(frozen=True)
class TraceRow:
    """Mot dong, gan nhu nguyen ven.

    `agent_id`/`agent_type` la `None` khi khoa vang mat trong payload -- tuc la mot tool call cua
    phien chinh. Khong bao gio lan `None` voi `""`: hook ghi thang gia tri host gui, nen chuoi rong
    o day nghia la *host* gui chuoi rong, mot su kien khac han.
    """

    at: str
    event: str
    session_id: str
    agent_id: str | None
    agent_type: str | None
    tool: str
    tool_use_id: str
    args_digest: str
    #: Duong dan that, da tach khoi `command`. Gop hai thu nay vao chung mot truong la cach de
    #: nhat, va no hong theo mot kieu kho thay: moi tieu chi doc thu tu deu phai noi ca truong lai
    #: roi tim chuoi con, nen mot tieu chi hoi "co ghi vao thu muc nay khong" khong con phan biet
    #: duoc mot lenh ghi that voi mot dong `echo` tinh co co ten thu muc do trong no.
    paths: tuple[str, ...]
    #: Dong lenh shell, nguyen ven, chi co tren tool chay lenh.
    command: str
    #: `None` tren mot `tool_call` (chua biet gi) va tren moi run do hook cu ghi. `False` nghia la
    #: harness *da noi* call nay that bai hoac bi chan -- khac han voi "khong nghe thay gi".
    ok: bool | None
    blocked: bool
    detail: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def is_subagent(self) -> bool:
        return bool(self.agent_type or self.agent_id)

    @property
    def actor(self) -> str:
        return self.agent_type or self.agent_id or "main"


def _row_of(obj: dict[str, Any]) -> TraceRow:
    return TraceRow(
        at=str(obj.get("at") or ""),
        event=str(obj.get("event") or TOOL_CALL),
        session_id=str(obj.get("session_id") or ""),
        agent_id=obj.get("agent_id"),
        agent_type=obj.get("agent_type"),
        tool=str(obj.get("tool") or ""),
        tool_use_id=str(obj.get("tool_use_id") or ""),
        args_digest=str(obj.get("args_digest") or ""),
        paths=tuple(str(p) for p in obj.get("paths") or ()),
        command=str(obj.get("command") or ""),
        ok=obj.get("ok"),
        blocked=bool(obj.get("blocked")),
        detail=str(obj.get("detail") or ""),
        raw=obj,
    )


def parse(lines: Iterable[str]) -> list[TraceRow]:
    """Mot row moi dong khong rong, dung thu tu file -- thu tu la toan bo tin hieu.

    Khac voi hook (phai fail open, vi no tuyet doi khong duoc lam hong lan chay ma no dang quan
    sat), mot dong hong o day dang de bao loi to: no nghia la hook ghi ra thu gay, hoac co thu
    khac ghi them vao file, va mot bo cham am tham bo dong do se cham mot lan chay ngan hon lan
    chay that.
    """
    rows: list[TraceRow] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError(f"dong {lineno}: khong phai JSON hop le: {exc}") from exc
        if not isinstance(obj, dict):
            raise TraceError(f"dong {lineno}: can mot object, nhan {type(obj).__name__}")
        rows.append(_row_of(obj))
    return rows


def read(path: Path) -> list[TraceRow]:
    """Moi row hien co tren dia. File chua ton tai la khong row, khong phai mot loi -- `--step`
    doc file nay truoc khi hook kip ghi dong dau tien."""
    if not path.is_file():
        return []
    return parse(path.read_text(encoding="utf-8").splitlines())
