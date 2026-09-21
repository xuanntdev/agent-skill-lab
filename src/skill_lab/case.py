"""Mot test case: mot nhiem vu, va nhung gi phai dung ve lan chay ma no sinh ra.

Mot rubric viet bang ham Python chi cham duoc dung mot skill -- do la ly do bo do truoc do khong
bao gio cham duoc skill thu hai. Case file mang theo assertion cua chinh no, nen mot skill moi la
mot file moi chu khong phai mot ham moi trong bo cham.

**Ca hai cach viet deu duoc chap nhan, co chu y.** Mot chuoi tran goi ten mot check dung mac dinh;
mot mapping thi tham so hoa no. Dang chuoi giu cho nhung case don gian doc duoc bang mot lan liec,
dang mapping la thu mot skill that can.

```yaml
id: doc-rang-buoc-truoc-khi-ghi
skill: tidy-a-module
fixture: git-worktree
tags: [core]
task: |
  Module `model` co mot ham khong con ai goi. Bo no di.
expect:
  must:
    - check: command_before_write
      id: rang-buoc-truoc-ghi
      command: ["make lint-rules"]
      under: src
    - check: delegated_to
      agent: verifier
  must_not:
    - check: tool_used
      tool: WebFetch
  evidence:
    required: true
budget:
  max_cost_usd: 1.50
  max_steps: 90
judge:
  - id: Q2
    question: Cho mo ho thi actor HOI hay DOAN?
```

**`must_not` dao nguoc phan quyet cua chinh check do.** Mot registry, doc theo hai chieu, thay vi
mot bo check phu dinh thu hai co the bat dong voi bo khang dinh ve chinh dieu no do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from skill_lab.model import digest_text


class CaseError(Exception):
    """Case file khong co, khong doc duoc, hoac doi mot check ma registry khong co."""


@dataclass(frozen=True)
class CheckSpec:
    """Mot assertion, da chuan hoa khoi ca hai cach viet.

    `negate` mang o day chu khong o cho goi, de `verify.py` chay mot vong lap tren mot danh sach --
    lua chon con lai la hai vong lap phai luon dong y voi nhau ve moi thu tru dau.
    """

    id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    negate: bool = False


@dataclass(frozen=True)
class JudgeSpec:
    """Mot cau hoi nhi phan cho judge. Nhi phan chu khong phai thang diem: mot thang "cai nao hay
    hon" moi dung cac thien vi ma judge von co -- van phong cung ho, cau dai, va vi tri."""

    id: str
    question: str


@dataclass(frozen=True)
class Case:
    id: str
    skill: str
    task: str
    fixture: str = ""
    tags: tuple[str, ...] = ()
    checks: tuple[CheckSpec, ...] = ()
    judge: tuple[JudgeSpec, ...] = ()
    path: Path | None = None
    digest: str = ""

    @property
    def is_boundary(self) -> bool:
        """Mot case bien hoi skill co biet luc nao **khong** nen hanh dong: kich hoat thua, lam
        viec khong can, chay ca bo test cho mot sua doi tai lieu. `compare.py` gac rieng nhom nay
        vi mot trung binh che mat chung: chung it ve so luong va la toan bo cau hoi ve hau qua.
        """
        return "boundary" in self.tags


def _spec_of(entry: Any, index: int, *, negate: bool) -> CheckSpec:
    prefix = "must_not" if negate else "must"
    if isinstance(entry, str):
        return CheckSpec(id=entry, kind=entry, negate=negate)
    if not isinstance(entry, dict):
        raise CaseError(f"{prefix}[{index}] khong phai chuoi cung khong phai mapping: {entry!r}")
    kind = str(entry.get("check") or "").strip()
    if not kind:
        raise CaseError(f"{prefix}[{index}] thieu khoa `check`")
    params = {k: v for k, v in entry.items() if k not in ("check", "id")}
    return CheckSpec(
        id=str(entry.get("id") or f"{prefix}.{kind}.{index}"),
        kind=kind,
        params=params,
        negate=negate,
    )


def _evidence_specs(block: Any) -> list[CheckSpec]:
    """`evidence.required: true` la duong cho mot check co ten, khong phai mot co che rieng.

    No no ra thanh `evidence_backed`, tuc la: khi actor tuyen bo da xong, trace phai chua mot lan
    thuc thi that co ket qua, chu khong chi mot cau khang dinh. Viet thanh duong giu cho rang buoc
    do duoc danh van giong nhau o moi case file, thay vi moi nguoi tu nghi mot cach dien dat.
    """
    if not isinstance(block, dict) or not block.get("required"):
        return []
    params = {}
    if block.get("commands"):
        params["commands"] = [str(c) for c in block["commands"]]
    return [CheckSpec(id="evidence.required", kind="evidence_backed", params=params)]


def _budget_specs(block: Any) -> list[CheckSpec]:
    if not isinstance(block, dict):
        return []
    specs = []
    if block.get("max_cost_usd") is not None:
        specs.append(
            CheckSpec(id="budget.cost", kind="max_cost_usd", params={"limit": float(block["max_cost_usd"])})
        )
    if block.get("max_steps") is not None:
        specs.append(
            CheckSpec(id="budget.steps", kind="max_steps", params={"limit": int(block["max_steps"])})
        )
    if block.get("max_duration_s") is not None:
        specs.append(
            CheckSpec(
                id="budget.duration",
                kind="max_duration_s",
                params={"limit": float(block["max_duration_s"])},
            )
        )
    return specs


def _judge_specs(raw: Any) -> tuple[JudgeSpec, ...]:
    if not raw:
        return ()
    specs = []
    for i, entry in enumerate(raw):
        if isinstance(entry, str):
            specs.append(JudgeSpec(id=f"Q{i + 1}", question=entry))
        elif isinstance(entry, dict):
            question = str(entry.get("question") or "").strip()
            if not question:
                raise CaseError(f"judge[{i}] thieu khoa `question`")
            specs.append(JudgeSpec(id=str(entry.get("id") or f"Q{i + 1}"), question=question))
        else:
            raise CaseError(f"judge[{i}] khong doc duoc: {entry!r}")
    return tuple(specs)


def load(path: Path) -> Case:
    if not path.is_file():
        raise CaseError(f"khong co case tai {path}")
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise CaseError(f"{path} khong phai mot mapping YAML")

    expect = raw.get("expect") or {}
    specs: list[CheckSpec] = []
    for i, entry in enumerate(expect.get("must") or ()):
        specs.append(_spec_of(entry, i, negate=False))
    for i, entry in enumerate(expect.get("must_not") or ()):
        specs.append(_spec_of(entry, i, negate=True))
    specs.extend(_evidence_specs(expect.get("evidence")))
    specs.extend(_budget_specs(raw.get("budget")))

    skill = str(raw.get("skill") or "").strip()
    if not skill:
        raise CaseError(f"{path} thieu khoa `skill` -- khong biet chay skill nao")
    task = str(raw.get("task") or raw.get("request") or "").strip()
    if not task:
        raise CaseError(f"{path} thieu khoa `task` -- khong co gi de giao cho actor")

    return Case(
        id=str(raw.get("id") or path.stem),
        skill=skill,
        task=task,
        fixture=str(raw.get("fixture") or ""),
        tags=tuple(str(t) for t in raw.get("tags") or ()),
        checks=tuple(specs),
        judge=_judge_specs(raw.get("judge")),
        path=path,
        digest=digest_text(text),
    )


def find(case_id: str, *, root: Path) -> Case:
    """Tim theo id tren ca cay. Id la duy nhat trong cay, va bat nguoi ta go lai ten skill ma ho
    da khai ben trong file la them mot cho cho hai ben bat dong."""
    for path in sorted(root.rglob("*.yaml")):
        if path.stem == case_id:
            return load(path)
    for path in sorted(root.rglob("*.yaml")):
        case = load(path)
        if case.id == case_id:
            return case
    raise CaseError(f"khong tim thay case '{case_id}' duoi {root}")


def dataset(name: str, *, root: Path) -> list[Case]:
    """Moi case duoi `<root>/<name>/`, hoac moi case mang `<name>` lam tag hoac lam skill.

    Hai cach goi ten mot tap vi chung tra loi hai cau hoi khac nhau: mot thu muc la "tat ca cho
    skill nay", mot tag la "tat ca thu thu hanh vi nay", va mot case thuong thuoc ca hai.
    """
    directory = root / name
    if directory.is_dir():
        return [load(p) for p in sorted(directory.rglob("*.yaml"))]
    matched = [c for c in all_cases(root=root) if name in c.tags or c.skill == name]
    if not matched:
        raise CaseError(f"'{name}' khong phai thu muc, tag hay skill nao duoi {root}")
    return matched


def all_cases(*, root: Path) -> list[Case]:
    if not root.is_dir():
        return []
    return [load(p) for p in sorted(root.rglob("*.yaml"))]
