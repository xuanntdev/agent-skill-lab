"""So sanh hai phien ban, va tu choi goi mot ben la "tot hon" khi du lieu khong noi duoc dieu do.

Ba rang buoc lam nen ca file nay.

**So theo cap, khong so hai trung binh.** Hai phien ban chay cung tap case, roi lay hieu tren tung
case. So sanh hai con so tong the vat qua mat rang phan lon phuong sai den tu viec case nay kho
hon case kia, chu khong tu phien ban -- va do la phuong sai deu co o ca hai ben.

**Mot khoang chenh nho hon nhieu thi phai duoc goi la nhieu.** Voi n case, sai so chuan cua mot ty
le xap xi `sqrt(p(1-p)/n)`. Voi n = 12 va p = 0,75, con so do vao khoang 12 diem phan tram: mot
"cai thien 8 diem" tren 12 case khong phai mot cai thien, no la mot lan tung dong xu. File nay in
ra nguong do canh ket qua thay vi de nguoi doc tu nho.

**Diem tong tang khong du de promote.** Mot candidate phai qua nam cua: tong the, regression nang,
regression o case bien, chi phi, va thoi gian. Muc 9 cua de bai noi thang dieu nay, va ly do la
mot candidate dat gap ba lan de doi ba diem phan tram thuong la mot quyet dinh sai ma bang diem
mot cot se giau di.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Sequence

from skill_lab.model import RunRecord

#: Nguong tuong doi truoc khi mot khoan tang chi phi hay thoi gian duoc goi la regression. 25% la
#: mot lua chon, khong phai mot hang so tu nhien -- `--cost-tolerance` doi duoc no, va bao cao in
#: ra con so da dung.
DEFAULT_COST_TOLERANCE = 0.25
DEFAULT_LATENCY_TOLERANCE = 0.25

#: Nam ket luan, va khong ket luan nao trong so do la "promote".
#:
#: `IMPROVED` noi rang do do da tang that va khong co gi di lui -- no khong noi rang nen trien
#: khai. Quyet dinh promote can nhung thu ma bo do nay khong nhin thay: rui ro, thoi diem, ai truc.
#: Mot cong cu tu tuyen bo "promote" la mot cong cu da lang le doi vai tro tu do luong sang quyet
#: dinh.
IMPROVED = "IMPROVED"
REGRESSED = "REGRESSED"
TRADE_OFF = "TRADE_OFF"
#: Du lieu du de so, va hieu nam trong nhieu.
NO_CLEAR_DIFFERENCE = "NO_CLEAR_DIFFERENCE"
#: Du lieu KHONG du de so. Khac han cai tren, va gop chung lam mot la cach mot bo so sanh noi
#: "khong khac biet" trong khi su that la "chua do du de biet".
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

#: So lan chay toi thieu moi ben truoc khi mot hieu duoc doc nhu mot tin hieu. Ba la muc thap
#: nhat con noi duoc gi do ve phuong sai; duoi nguong nay, mot hieu bat ky chi la mot lan rut.
DEFAULT_MIN_RUNS = 3

#: Bien thi nghiem thuoc ve "cau hinh chay" chu khong thuoc ve skill. Doi mot trong nhung truong
#: nay la doi mot bien KHAC voi skill, va neu ca hai cung doi thi khong ai tach duoc phan dong gop
#: cua tung ben.
RUNTIME_FIELDS = ("model", "effort", "harness_version", "toolset_version")
SKILL_FIELDS = ("skill_version",)

#: Truong identity thuoc ve TUNG CASE chu khong thuoc ve mot ben.
#:
#: `case_digest` la mot vi du va ly do truong nay ton tai: mot dataset hai case thi hai case co hai
#: digest, o ca hai ben. Gop chung o muc ben se bao "ben nay tron nhieu cau hinh" tren moi dataset
#: nhieu hon mot case -- mot canh bao dung ve mat co hoc va vo nghia ve mat noi dung, va loai canh
#: bao do day nguoi ta toi cho thoi doc canh bao. Chung duoc so **theo tung case** o duoi.
PER_CASE_FIELDS = ("case_digest",)


@dataclass
class CaseStat:
    case_id: str
    runs: int = 0
    passed: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    tool_calls: float = 0.0
    boundary: bool = False
    digest: str = ""

    @property
    def rate(self) -> float:
        return self.passed / self.runs if self.runs else 0.0


@dataclass
class Side:
    """Mot phien ban, da gop tu cac lan chay cua no."""

    label: str
    stats: dict[str, CaseStat] = field(default_factory=dict)
    #: Cac gia tri da thay cho tung truong identity, gop tu moi lan chay cua ben nay. Mot ben tron
    #: hai model se co hai gia tri o `model`, va do la mot su that can hien ra chu khong phai mot
    #: chi tiet can lam phang.
    identity: dict[str, set[str]] = field(default_factory=dict)

    def identity_of(self, field_name: str) -> str:
        values = sorted(v for v in self.identity.get(field_name, set()) if v)
        if not values:
            return ""
        return values[0] if len(values) == 1 else "|".join(values)

    @property
    def mixed_identity(self) -> list[str]:
        return sorted(
            f
            for f, v in self.identity.items()
            if f not in PER_CASE_FIELDS and len({x for x in v if x}) > 1
        )

    @property
    def runs(self) -> int:
        return sum(s.runs for s in self.stats.values())

    @property
    def rate(self) -> float:
        total = sum(s.runs for s in self.stats.values())
        passed = sum(s.passed for s in self.stats.values())
        return passed / total if total else 0.0

    def mean(self, attr: str) -> float:
        total_runs = sum(s.runs for s in self.stats.values())
        if not total_runs:
            return 0.0
        return sum(getattr(s, attr) for s in self.stats.values()) / total_runs


@dataclass
class CaseDelta:
    case_id: str
    baseline_rate: float
    candidate_rate: float
    boundary: bool
    #: `True` khi chinh case da doi giua hai ben. Mot case doi ban le thi hai ben khong con tra loi
    #: cung mot cau hoi, va hieu tren case do khong doc duoc.
    case_changed: bool = False

    @property
    def delta(self) -> float:
        return self.candidate_rate - self.baseline_rate

    @property
    def regressed(self) -> bool:
        return self.candidate_rate < self.baseline_rate

    @property
    def critical(self) -> bool:
        """Mot case truoc kia **luon** xanh, gio khong con luon xanh.

        Day la dinh nghia hep co chu y. Mot case von chap chon 60% roi xuong 50% la nhieu; mot case
        von 100% ma gio khong con 100% la mot thu da hong, va do la thu mot bo regression ton tai
        de bat.
        """
        return self.baseline_rate >= 1.0 and self.candidate_rate < 1.0


@dataclass
class Comparison:
    baseline: Side
    candidate: Side
    deltas: list[CaseDelta]
    verdict: str
    reasons: list[str]
    shared_cases: int
    noise_threshold: float
    cost_tolerance: float
    latency_tolerance: float
    #: Cac bien identity khac nhau giua hai ben: `{ten: (baseline, candidate)}`.
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: `skill` | `runtime` | `confounded` | `khong doi bien nao`. Phep so nay dang do cai gi.
    subject: str = "skill"
    #: Cac bien cung doi mot luc khien khong the quy phan dong gop cho ben nao.
    confounders: list[str] = field(default_factory=list)
    min_runs: int = DEFAULT_MIN_RUNS

    @property
    def rate_delta(self) -> float:
        return self.candidate.rate - self.baseline.rate

    @property
    def cost_delta_ratio(self) -> float:
        base = self.baseline.mean("cost_usd")
        return (self.candidate.mean("cost_usd") - base) / base if base else 0.0

    @property
    def latency_delta_ratio(self) -> float:
        base = self.baseline.mean("duration_ms")
        return (self.candidate.mean("duration_ms") - base) / base if base else 0.0

    @property
    def within_noise(self) -> bool:
        return abs(self.rate_delta) < self.noise_threshold

    @property
    def critical(self) -> list[CaseDelta]:
        return [d for d in self.deltas if d.critical]

    @property
    def boundary_regressions(self) -> list[CaseDelta]:
        return [d for d in self.deltas if d.boundary and d.regressed]


def side_of(label: str, records: Sequence[RunRecord], passed: dict[str, bool], boundary: set[str]) -> Side:
    """Gop cac lan chay thanh mot ben. `passed` tra loi "lan chay nay xanh hay do" theo run_id."""
    side = Side(label=label)
    for record in records:
        stat = side.stats.setdefault(
            record.case_id, CaseStat(case_id=record.case_id, boundary=record.case_id in boundary)
        )
        stat.runs += 1
        stat.passed += 1 if passed.get(record.run_id) else 0
        stat.cost_usd += record.cost_usd
        stat.duration_ms += record.duration_ms
        stat.tool_calls += record.num_tool_calls
        stat.digest = record.case_digest or stat.digest
        for name, value in record.identity().items():
            side.identity.setdefault(name, set()).add(value)
    return side


def changed_variables(baseline: Side, candidate: Side) -> dict[str, tuple[str, str]]:
    """Cac truong identity khac nhau giua hai ben. Day la "da doi gi" cua mot thi nghiem."""
    changed = {}
    for name in RunRecord.IDENTITY_FIELDS:
        if name in PER_CASE_FIELDS:
            continue
        left, right = baseline.identity_of(name), candidate.identity_of(name)
        if left != right:
            changed[name] = (left, right)
    return changed


def subject_of(changed: dict[str, tuple[str, str]]) -> tuple[str, list[str]]:
    """`(chu the cua phep so, danh sach bien gay nhieu)`.

    Day la cau tra loi cho cau hoi "so sanh nay dang do skill hay dang do model". Truoc khi co ham
    nay, `compare` tron hai thu do: hai ben chay tren hai model khac nhau van duoc doc nhu mot cai
    thien cua skill, va khong co dong nao trong bao cao noi rang model da doi.
    """
    skill_changed = [f for f in SKILL_FIELDS if f in changed]
    runtime_changed = [f for f in RUNTIME_FIELDS if f in changed]
    if skill_changed and runtime_changed:
        return "confounded", skill_changed + runtime_changed
    if runtime_changed:
        return "runtime", []
    if skill_changed:
        return "skill", []
    return "khong doi bien nao", []


def noise_threshold(rate: float, n: int) -> float:
    """Hai lan sai so chuan cua mot ty le voi n quan sat.

    Hai lan, khong phai mot: mot lan la khoang 68%, va mot nguong ma mot lan ba khoang chenh ngau
    nhien vuot qua duoc thi khong phai mot nguong.
    """
    if n <= 0:
        return 1.0
    p = min(max(rate, 0.0), 1.0)
    return 2 * sqrt(max(p * (1 - p), 0.01) / n)


def compare(
    baseline: Side,
    candidate: Side,
    *,
    cost_tolerance: float = DEFAULT_COST_TOLERANCE,
    latency_tolerance: float = DEFAULT_LATENCY_TOLERANCE,
    min_runs: int = DEFAULT_MIN_RUNS,
) -> Comparison:
    shared = sorted(set(baseline.stats) & set(candidate.stats))
    deltas = [
        CaseDelta(
            case_id=case_id,
            baseline_rate=baseline.stats[case_id].rate,
            candidate_rate=candidate.stats[case_id].rate,
            boundary=baseline.stats[case_id].boundary or candidate.stats[case_id].boundary,
            case_changed=baseline.stats[case_id].digest != candidate.stats[case_id].digest,
        )
        for case_id in shared
    ]

    threshold = noise_threshold(baseline.rate, len(shared))
    comparison = Comparison(
        baseline=baseline,
        candidate=candidate,
        deltas=deltas,
        verdict=INSUFFICIENT_EVIDENCE,
        reasons=[],
        shared_cases=len(shared),
        noise_threshold=threshold,
        cost_tolerance=cost_tolerance,
        latency_tolerance=latency_tolerance,
    )

    reasons: list[str] = []
    comparison.changed = changed_variables(baseline, candidate)
    comparison.subject, comparison.confounders = subject_of(comparison.changed)
    comparison.min_runs = min_runs

    only_baseline = sorted(set(baseline.stats) - set(candidate.stats))
    only_candidate = sorted(set(candidate.stats) - set(baseline.stats))
    if only_baseline or only_candidate:
        reasons.append(
            f"hai ben khong chay cung tap case (chi baseline: {len(only_baseline)}, "
            f"chi candidate: {len(only_candidate)}) -- phan khong chung khong duoc tinh vao hieu"
        )
    for side in (baseline, candidate):
        if side.mixed_identity:
            reasons.append(
                f"ben `{side.label}` tron nhieu cau hinh o: {', '.join(side.mixed_identity)} "
                "-- trung binh cua no khong dai dien cho cau hinh nao"
            )

    def finish(verdict: str) -> Comparison:
        comparison.verdict = verdict
        comparison.reasons = reasons
        return comparison

    # ── ba cua "chua du de so", xet TRUOC moi con so ──────────────────────────
    #
    # Thu tu nay quan trong. Tinh hieu roi moi hoi "co du du lieu khong" la cach mot bao cao in ra
    # mot con so chinh xac ve mot thu khong do duoc, va con so do se duoc nho lau hon canh bao di
    # kem no.
    if not shared:
        reasons.append("khong co case nao chung giua hai ben")
        return finish(INSUFFICIENT_EVIDENCE)

    if comparison.subject == "confounded":
        reasons.append(
            "ca skill lan cau hinh chay deu doi giua hai ben ("
            + ", ".join(f"{f}: {comparison.changed[f][0] or '-'} -> {comparison.changed[f][1] or '-'}"
                        for f in comparison.confounders)
            + ") -- khong tach duoc phan dong gop cua skill khoi phan dong gop cua model"
        )
        return finish(INSUFFICIENT_EVIDENCE)

    if baseline.runs < min_runs or candidate.runs < min_runs:
        reasons.append(
            f"moi ben can it nhat {min_runs} lan chay de mot hieu co nghia; dang co "
            f"{baseline.runs} va {candidate.runs}"
        )
        return finish(INSUFFICIENT_EVIDENCE)

    drifted = [d.case_id for d in deltas if d.case_changed]
    if drifted:
        reasons.append(
            f"{len(drifted)} case da doi noi dung giua hai ben ({', '.join(drifted)}) -- hai ben "
            "khong con tra loi cung mot cau hoi tren nhung case do"
        )

    if comparison.subject == "runtime":
        reasons.append(
            "skill khong doi; thu doi la cau hinh chay ("
            + ", ".join(f"{f}: {v[0] or '-'} -> {v[1] or '-'}" for f, v in comparison.changed.items())
            + ") -- ket qua duoi day noi ve nang luc cau hinh, khong noi ve chat luong skill"
        )

    # ── cac cua regression ────────────────────────────────────────────────────
    critical = comparison.critical
    boundary_regressions = comparison.boundary_regressions

    if critical:
        reasons.append(
            f"{len(critical)} case tu luon-xanh thanh khong-con-luon-xanh: "
            + ", ".join(d.case_id for d in critical)
        )
        return finish(REGRESSED)
    if boundary_regressions:
        reasons.append(
            f"{len(boundary_regressions)} case bien di lui: "
            + ", ".join(d.case_id for d in boundary_regressions)
        )
        return finish(REGRESSED)

    if comparison.within_noise:
        reasons.append(
            f"chenh lech {comparison.rate_delta:+.1%} nam trong nguong nhieu ±{threshold:.1%} "
            f"tren {len(shared)} case"
        )
        return finish(NO_CLEAR_DIFFERENCE)

    if comparison.rate_delta < 0:
        reasons.append(f"ty le xanh giam {comparison.rate_delta:+.1%}, vuot nguong nhieu")
        return finish(REGRESSED)

    cost_over = comparison.cost_delta_ratio > cost_tolerance
    latency_over = comparison.latency_delta_ratio > latency_tolerance
    if cost_over or latency_over:
        if cost_over:
            reasons.append(
                f"chi phi tang {comparison.cost_delta_ratio:+.0%}, vuot nguong {cost_tolerance:.0%}"
            )
        if latency_over:
            reasons.append(
                f"thoi gian tang {comparison.latency_delta_ratio:+.0%}, vuot nguong {latency_tolerance:.0%}"
            )
        reasons.append("danh doi nay la mot quyet dinh cua nguoi, khong phai cua cong cu")
        return finish(TRADE_OFF)

    reasons.append(
        f"ty le xanh tang {comparison.rate_delta:+.1%}, vuot nguong nhieu ±{threshold:.1%}, "
        "khong co regression nang va khong vuot ngan sach"
    )
    return finish(IMPROVED)
