"""Mot thi nghiem duoc khai bao, khong phai duoc nho.

File nay co y nho. No khong toi uu gi, khong sinh candidate, khong tu sua skill. No chi lam mot
viec: bat nguoi chay phai **viet ra gia thuyet va bien nao doi truoc khi thay ket qua**.

Do la toan bo gia tri cua no. Khi gia thuyet duoc viet sau, moi ket qua deu xac nhan mot gia
thuyet nao do, va bo so sanh tro thanh mot may sinh cau chuyen. Khi bien doi khong duoc khai, hai
ben co the khac nhau o ba thu cung luc va khong ai nhan ra -- `compare.py` bat duoc truong hop do
va tra `INSUFFICIENT_EVIDENCE`, nhung no chi bat duoc sau khi tien da tieu.

```yaml
id: rang-buoc-truoc-ghi-1-8-3
hypothesis: |
  Viet rang buoc thu tu thanh cau menh lenh se giam so lan actor ghi truoc khi doc rang buoc.
dataset: demo
runs: 3
baseline:
  label: "1.8.2"
candidate:
  label: "1.8.3-candidate"
changed: [skill_version]
fixed: [model, effort, workspace_rev]
```

`baseline`/`candidate` co the khai `model` va `effort` rieng. Doi ca skill lan model trong cung
mot thi nghiem la hop le -- `compare.py` se noi thang rang khong tach duoc phan dong gop, va do la
cau tra loi dung cho mot thi nghiem duoc thiet ke nhu vay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ExperimentError(Exception):
    """File thi nghiem khong co hoac khong dung hinh dang."""


@dataclass(frozen=True)
class Arm:
    """Mot ben cua thi nghiem. `label` la ten nguoi dat; no di thang vao `RunRecord.label` va la
    thu `compare` dung de chon lan chay."""

    label: str
    model: str = ""
    effort: str = ""

    @classmethod
    def of(cls, raw: Any, *, which: str) -> "Arm":
        if isinstance(raw, str):
            return cls(label=raw)
        if not isinstance(raw, dict):
            raise ExperimentError(f"`{which}` phai la mot chuoi hoac mapping")
        label = str(raw.get("label") or "").strip()
        if not label:
            raise ExperimentError(f"`{which}` thieu `label`")
        return cls(label=label, model=str(raw.get("model") or ""), effort=str(raw.get("effort") or ""))


@dataclass(frozen=True)
class Experiment:
    id: str
    hypothesis: str
    dataset: str
    baseline: Arm
    candidate: Arm
    runs: int = 3
    #: Khai bao cua nguoi viet ve bien nao doi va bien nao giu. Day la **y dinh**, va `compare.py`
    #: doc identity that tu cac lan chay de doi chieu. Hai cai lech nhau la mot phat hien, khong
    #: phai mot loi cau hinh -- no co nghia la thi nghiem khong chay dung nhu da thiet ke.
    changed: tuple[str, ...] = ()
    fixed: tuple[str, ...] = ()
    path: Path | None = None
    notes: str = ""

    def mismatch(self, observed_changed: dict[str, tuple[str, str]]) -> list[str]:
        """Bien thuc su doi ma khong duoc khai, va bien khai la giu nhung lai doi."""
        observed = set(observed_changed)
        problems = []
        for name in sorted(observed - set(self.changed)):
            problems.append(f"`{name}` doi tren thuc te nhung khong nam trong `changed`")
        for name in sorted(set(self.fixed) & observed):
            problems.append(f"`{name}` duoc khai la `fixed` nhung da doi")
        for name in sorted(set(self.changed) - observed):
            problems.append(f"`{name}` duoc khai la `changed` nhung thuc te khong doi")
        return problems


def load(path: Path) -> Experiment:
    if not path.is_file():
        raise ExperimentError(f"khong co file thi nghiem tai {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ExperimentError(f"{path} khong phai mot mapping YAML")

    hypothesis = str(raw.get("hypothesis") or "").strip()
    if not hypothesis:
        raise ExperimentError(
            f"{path} thieu `hypothesis` -- mot thi nghiem khong co gia thuyet la mot lan chay, "
            "va ket qua cua no se xac nhan bat cu dieu gi nguoi doc muon"
        )
    dataset = str(raw.get("dataset") or "").strip()
    if not dataset:
        raise ExperimentError(f"{path} thieu `dataset`")
    if "baseline" not in raw or "candidate" not in raw:
        raise ExperimentError(f"{path} can ca `baseline` lan `candidate`")

    return Experiment(
        id=str(raw.get("id") or path.stem),
        hypothesis=hypothesis,
        dataset=dataset,
        baseline=Arm.of(raw["baseline"], which="baseline"),
        candidate=Arm.of(raw["candidate"], which="candidate"),
        runs=int(raw.get("runs") or 3),
        changed=tuple(str(x) for x in raw.get("changed") or ()),
        fixed=tuple(str(x) for x in raw.get("fixed") or ()),
        path=path,
        notes=str(raw.get("notes") or ""),
    )


@dataclass
class ExperimentResult:
    experiment: Experiment
    baseline_runs: list[str] = field(default_factory=list)
    candidate_runs: list[str] = field(default_factory=list)
    design_problems: list[str] = field(default_factory=list)
