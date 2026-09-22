"""Buoc sai dau tien, va mot gia thuyet co bang chung ve viec ai phai sua.

Hai quyet dinh dinh hinh ca file nay.

**Mot: buoc sai dau tien duoc tinh, khong duoc hoi model.** Moi check that bai deu da biet chi so
buoc noi no vo -- do la ly do `CheckResult.at_step` ton tai -- nen buoc sai dau tien la min cua
cac chi so do. Tat dinh, mien phi, va lap lai duoc. Cach lam pho bien la dua ca trajectory cho mot
LLM va hoi "buoc nao sai dau tien"; o day do la duong lui, khong phai duong chinh.

**Hai: khong phai that bai nao cung la loi cua skill.** Neu trace cho thay agent da lam dung va
moi truong tu choi -- mot gate chan, mot lenh khong ton tai, mot tran turn cat ngang -- thi quy
trach nhiem cho skill la sai, va sua skill de "cho xanh" se sinh ra mot skill co hai loi thay vi
mot. Cac ham `_override_*` duoi day lam dung mot viec: doi chu so huu khi trace noi khac.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Sequence

from skill_lab import taxonomy
from skill_lab.model import (
    UNDECIDED,
    WEAK_EVIDENCE,
    CheckResult,
    RunRecord,
    Step,
    call_steps,
    result_of,
)

#: Mot chan doan noi ro no chac den dau, va con so do duoc suy tu **do neo cua bang chung**, khong
#: tu cam giac.
#:
#: * `high`   -- bang chung nam dung tai buoc sai dau tien.
#: * `medium` -- bang chung nam o cho khac trong trace nhung lien quan truc tiep toi check da vo.
#: * `low`    -- khong neo duoc vao buoc nao, hoac phan quyet den tu judge, hoac khong con gi de
#:               quy trach nhiem. `owner` khi do la `unknown`, va do la mot cau tra loi hop le.
HIGH, MEDIUM, LOW = "high", "medium", "low"

UNKNOWN_OWNER = "unknown"

#: Cac check ma phan quyet cua chung phu thuoc vao viec mot lenh co chay duoc hay khong. Chi nhung
#: check nay moi duoc phep quy trach nhiem cho `repository` bang bang chung khong neo -- va khi do
#: `confidence` tut xuong `medium`.
COMMAND_DEPENDENT_KINDS = frozenset(
    {"command_ran", "command_order", "command_before_write", "evidence_backed", "shell"}
)


@dataclass
class Diagnosis:
    run_id: str = ""
    verdict: str = "PASS"
    first_error_step: int | None = None
    first_error_check: str = ""
    category: str = "unknown"
    owner: str = UNKNOWN_OWNER
    #: `high` | `medium` | `low`. Mot chan doan khong duoc tu nhan la su that; day la cho no noi
    #: no dang dung o dau giua gia thuyet va ket luan.
    confidence: str = LOW
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    #: Cau hoi ma chan doan nay tra loi, viet nhu mot gia thuyet co the bac bo duoc chu khong nhu
    #: mot phan quyet.
    hypothesis: str = ""
    suggested_change: str = ""
    suggestion: str = ""
    downstream_steps: int = 0
    #: Dat khi chu so huu bi doi khoi doc mac dinh cua check. Giu lai nhan cu la de nguoi doc phan
    #: bac duoc, thay vi phai tin.
    reattributed_from: str = ""
    undecided: list[str] = field(default_factory=list)
    #: Cac check co bang chung nhung la bang chung yeu. Tach khoi `undecided` vi huong xu ly khac
    #: han: mot check yeu duoc chua bang cach viet chat lai case, khong phai bang cach sua skill.
    weak_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _failed(checks: Sequence[CheckResult]) -> list[CheckResult]:
    return [c for c in checks if not c.passed and not c.undecided]


def _blocked_near(steps: Sequence[Step], index: int | None) -> Step | None:
    """Ket qua cua chinh buoc do, neu harness da chan no.

    Chi buoc do, khong quet vung lan can: mot lan bi chan cach do sau buoc la mot su kien khac, va
    dung no de go toi cho skill la doi mot ket luan tuy tien lay mot ket luan tuy tien khac.
    """
    if index is None:
        return None
    outcome = result_of(steps, index)
    if outcome and (outcome.blocked or outcome.ok is False):
        return outcome
    return None


def _override_turn_limit(record: RunRecord, diag: Diagnosis, steps: Sequence[Step]) -> bool:
    """Mot lan chay bi cat vi tran turn khong noi duoc gi chac chan ve than skill.

    No van noi duoc vai thu -- no da di toi dau -- nhung moi buoc sau diem cat la mot buoc khong
    bao gio xay ra, nen quy mot check thieu cho skill o day la quy cho mot thu chua kip chay.
    """
    if record.completed or record.exit_code == 0:
        return False
    diag.reattributed_from = diag.category

    # "Cham tran turn" va "bi giet" deu chi la mot ma exit khac 0, va goi ca hai la `turn_limit`
    # la noi nhieu hon bang chung. Do do duoc tu mot lan chay that: actor bi giet o phut 40, khong
    # he cham tran, va bao cao van dan nhan `termination.turn_limit` -- dung huong, sai ly do, va
    # mot huong sua ("nang tran turn") khong chua duoc gi.
    hit_ceiling = bool(record.max_turns) and record.num_turns >= record.max_turns
    diag.category = "termination.turn_limit" if hit_ceiling else "termination.aborted"
    diag.owner = taxonomy.owner_of(diag.category)
    # Bang chung la chinh ma exit cua tien trinh, khong phai mot suy dien -- nen `high`.
    diag.confidence = HIGH
    ceiling = f"/{record.max_turns}" if record.max_turns else ""
    diag.evidence.append(
        f"actor exit {record.exit_code} sau {record.num_turns}{ceiling} turn va "
        f"{len(call_steps(steps))} tool call"
    )
    diag.summary = (
        "Lan chay bi cat truoc khi ket thuc. Cac check con do co the chi phan anh phan viec chua "
        "kip chay, khong phai mot buoc skill bi bo."
    )
    diag.suggested_change = (
        "Nang tran turn roi chay lai truoc khi ket luan bat cu dieu gi ve skill."
        if hit_ceiling
        else "Chay lai; mot lan chay bi cat khong noi duoc gi ve skill."
    )
    diag.suggestion = diag.suggested_change
    return True


#: Dau hieu trong ket qua cua mot tool cho biet moi truong thieu thu can chay, chu khong phai
#: harness tu choi. Hai thu nay nhin giong nhau tu ngoai -- ca hai deu la mot buoc that bai -- va
#: gop chung lam mot se day moi lo hong cua repository sang cho harness.
MISSING_COMMAND_MARKERS = (
    "command not found",
    "not recognized",
    "no such file",
    "khong tim thay",
)


def _looks_missing(detail: str) -> bool:
    lowered = (detail or "").lower()
    return any(marker in lowered for marker in MISSING_COMMAND_MARKERS)


def _override_blocked(diag: Diagnosis, steps: Sequence[Step]) -> bool:
    blocked = _blocked_near(steps, diag.first_error_step)
    if blocked is None:
        return False
    if _looks_missing(blocked.detail):
        # Mot lenh khong ton tai la mot buoc that bai, y het mot gate tu choi. Nhuong cho
        # `_override_repository` doc no, neu khong thi moi lo hong cua repo se doi ten thanh mot
        # van de cua harness va khong ai tim lai duoc no.
        return False
    diag.reattributed_from = diag.category
    diag.category = "harness.gate_bypass" if blocked.blocked else "harness.tool_failure"
    diag.owner = taxonomy.owner_of(diag.category)
    # `_blocked_near` chi nhin ket qua cua chinh buoc sai dau tien, nen bang chung da neo.
    diag.confidence = HIGH
    detail = blocked.detail or ("bi chan" if blocked.blocked else "that bai")
    diag.evidence.append(f"buoc {blocked.of_step} co ket qua: {detail[:160]}")
    diag.summary = (
        "Agent da thu dung buoc nay va moi truong tu choi. Cho can sua nam o harness, khong o "
        "than skill."
    )
    diag.suggested_change = taxonomy.suggestion(diag.category)
    diag.suggestion = diag.suggested_change
    return True


def _override_repository(diag: Diagnosis, steps: Sequence[Step], first_kind: str) -> bool:
    """Skill bao chay mot lenh, agent chay, va repo khong co lenh do.

    Day la truong hop ma "khong sua skill de che loi cua thanh phan khac" noi toi: sua skill o day
    se che mat mot lo hong cua repository, va lan sau se khong ai tim lai duoc no.

    **Bang chung phai duoc neo.** Ban dau ham nay quet ca trace tim mot `command not found` bat ky
    va doi chu so huu ca chan doan sang `repository`. Do do duoc la sai bang mot probe: buoc sai
    dau tien o buoc 0 vi mot loi thu tu cua skill, mot lenh phu khong lien quan thieu binary o buoc
    2, va ca chan doan bi chuyen sang `repository`. Mot lenh phu that bai o cuoi trace khong noi gi
    ve mot buoc sai o dau trace.

    Gio co hai muc, va chung khac nhau o `confidence`:

    * lenh thieu nam dung tai buoc sai dau tien  -> `high`
    * lenh thieu nam cho khac, NHUNG check da vo la loai phu thuoc vao viec lenh chay duoc
      (`evidence_backed` chang han, vo o lan ghi cuoi trong khi lenh kiem chung thieu o cho khac)
      -> `medium`, va bao cao noi ro bang chung khong neo.
    """
    if diag.first_error_step is None:
        return False

    anchored = result_of(steps, diag.first_error_step)
    if anchored is not None and anchored.ok is False and _looks_missing(anchored.detail):
        _apply_repository(diag, anchored, confidence=HIGH, anchored=True)
        return True

    if first_kind not in COMMAND_DEPENDENT_KINDS:
        return False
    for step in steps:
        if step.type == "tool_result" and step.ok is False and _looks_missing(step.detail):
            _apply_repository(diag, step, confidence=MEDIUM, anchored=False)
            return True
    return False


def _apply_repository(diag: Diagnosis, step: Step, *, confidence: str, anchored: bool) -> None:
    diag.reattributed_from = diag.category
    diag.category = "repository.command_missing"
    diag.owner = taxonomy.owner_of(diag.category)
    diag.confidence = confidence
    where = "dung tai buoc sai dau tien" if anchored else f"o buoc {step.of_step}, khong phai buoc sai dau tien"
    diag.evidence.append(f"buoc {step.of_step} tra ve: {step.detail[:160]} ({where})")
    diag.summary = (
        "Skill yeu cau mot lenh ma repo nay khong chay duoc. Sua repo hoac sua case; sua skill o "
        "day chi giau lo hong di."
    )
    if not anchored:
        diag.summary += (
            " Bang chung khong neo vao buoc sai dau tien, nen day la gia thuyet chu chua phai ket luan."
        )
    diag.suggested_change = taxonomy.suggestion(diag.category)
    diag.suggestion = diag.suggested_change


#: Verdict rieng cho "khong ghi duoc bang chung nao". Khong phai `PASS` (khong co gi duoc chung
#: minh) va khong phai `FAIL` (khong co gi bi bac bo) -- gop vao mot trong hai deu la noi nhieu hon
#: bang chung. Tach ra la de mot scheduled job gui no cho nguoi bao tri bo do, khong cho nguoi viet
#: skill.
NO_EVIDENCE = "NO_EVIDENCE"


def _no_trajectory(
    record: RunRecord, checks: Sequence[CheckResult], steps: Sequence[Step]
) -> bool:
    """Actor CHAY XONG, trace rong, VA case nay co hoi mot cau ma chi trajectory tra loi duoc.

    Ba ve, va bo bat ve nao cung sai:

    * **`record.completed`** -- mot lan chay bi cat giua chung cung de lai trace rong, nhung o do
      *co* bang chung: chinh ma exit cua tien trinh. `termination.aborted` neo vao no voi do tin
      cay `high`, con `no_trajectory` thi `unknown`/`low`. Doi mot chan doan neo lay mot chan doan
      khong neo la di lui. Ve nay tung thieu, va no bien moi lan actor bi giet thanh "khong co
      bang chung".
    * **`not steps`** -- hien nhien.
    * **co check `UNDECIDED`** -- mot case chi gom `completed` va ngan sach khong doc trajectory
      dong nao, nen mot trace rong o do la binh thuong chu khong phai mot lo hong.
    """
    if not record.completed or steps:
        return False
    return any(c.status == UNDECIDED for c in checks)


def _no_trajectory_diagnosis(record: RunRecord, diag: Diagnosis) -> Diagnosis:
    """Khong quy trach nhiem. Hai cach doc deu con song, va bao cao phai noi ra ca hai.

    Tu mot trace rong khong the tach duoc "actor that su khong goi tool nao" khoi "host khong goi
    hook". Probe o `fixture.probe_hook` loai duoc kha nang thu hai o muc *hook chay duoc*, nhung no
    khong chung minh duoc rang host da THUC SU goi hook trong lan chay -- nen `owner` o day la
    `unknown`, va do la cau tra loi dung chu khong phai mot cho trong.
    """
    diag.verdict = NO_EVIDENCE
    diag.category = "harness.no_trajectory"
    diag.owner = UNKNOWN_OWNER
    diag.confidence = LOW
    diag.evidence.append(
        f"actor exit {record.exit_code} sau {record.num_turns} turn, nhung trace co 0 dong"
    )
    if record.actor_output:
        diag.evidence.append(f"actor van tra ve {len(record.actor_output)} ky tu output")
    diag.summary = (
        "Lan chay khong ghi duoc tool call nao, nen khong co gi de cham. Day khong phai mot phat "
        "bieu ve skill: mot trace rong va mot skill dung trong y het nhau tu phia bo cham."
    )
    diag.hypothesis = (
        "Gia thuyet (low): hoac actor that su khong goi tool nao, hoac host khong goi hook trace. "
        "Probe truoc khi chay da chung minh hook chay duoc, nhung khong chung minh duoc host da goi "
        "no -- nen hai kha nang nay chua tach duoc bang du lieu cua lan chay nay."
    )
    diag.suggested_change = taxonomy.suggestion(diag.category)
    diag.suggestion = diag.suggested_change
    return diag


def diagnose(
    record: RunRecord, checks: Sequence[CheckResult], steps: Sequence[Step]
) -> Diagnosis:
    diag = Diagnosis(run_id=record.run_id)
    diag.undecided = [c.id for c in checks if c.undecided and c.status != WEAK_EVIDENCE]
    diag.weak_evidence = [c.id for c in checks if c.status == WEAK_EVIDENCE]

    # Truoc moi phan quyet khac: lan chay nay co ghi lai duoc gi khong. Mot case hoi ve trajectory
    # ma trajectory rong thi moi cau tra loi sau do deu la cau tra loi tren tap rong -- ke ca cau
    # "khong co gi sai ca". Nhanh nay chan dung ket qua da do duoc trong lan E2E that: `8 xanh /
    # 1 do` cong `verdict: PASS` tren mot trace 0 byte.
    if _no_trajectory(record, checks, steps):
        return _no_trajectory_diagnosis(record, diag)

    failed = _failed(checks)
    if not failed and record.completed:
        diag.verdict = "PASS"
        diag.confidence = HIGH if not diag.undecided and not diag.weak_evidence else MEDIUM
        diag.summary = "Moi check tat dinh deu xanh va actor ket thuc binh thuong."
        if diag.weak_evidence:
            diag.summary += (
                " Nhung bang chung cho tuyen bo hoan thanh la bang chung yeu -- xem `weak_evidence`."
            )
        return diag

    diag.verdict = "FAIL"
    anchored = [c for c in failed if c.at_step is not None]
    first: CheckResult | None = None
    if anchored:
        first = min(anchored, key=lambda c: c.at_step)
        diag.first_error_step = first.at_step
    elif failed:
        first = failed[0]
    if first is not None:
        diag.first_error_check = first.id
        diag.category = first.category or taxonomy.category_for(first.kind)
    diag.owner = taxonomy.owner_of(diag.category)

    for check in failed:
        where = f"buoc {check.at_step}" if check.at_step is not None else "khong neo duoc vao buoc nao"
        diag.evidence.append(f"[{check.id}] {check.why} ({where})")

    calls = call_steps(steps)
    if diag.first_error_step is not None:
        diag.downstream_steps = len([s for s in calls if s.index > diag.first_error_step])

    # Do tin cay den tu do neo cua bang chung, va chi tu do. Khong neo duoc vao mot buoc nao thi
    # khong co gi de chi tay vao, va mot chan doan khong chi tay duoc vao dau la mot gia thuyet.
    if diag.first_error_step is None:
        diag.confidence = LOW
        diag.owner = UNKNOWN_OWNER
        diag.category = diag.category or "unknown"
    elif first is not None and not first.deterministic:
        # Phan quyet den tu judge. No co the dung, nhung no khong phai mot phep do.
        diag.confidence = LOW
    else:
        diag.confidence = HIGH

    if not diag.summary:
        diag.summary = taxonomy.describe(diag.category)
        diag.suggested_change = taxonomy.suggestion(diag.category)
        diag.suggestion = diag.suggested_change

    # Thu tu quan trong: tran turn cat ca lan chay nen no thang; sau do la mot gate da chan dung
    # buoc do; cuoi cung la mot lenh repo khong co. Moi buoc deu chi doi chu so huu khi trace noi
    # nguoc lai voi doc mac dinh, va deu ghi lai nhan cu vao `reattributed_from`.
    if not _override_turn_limit(record, diag, steps):
        if not _override_blocked(diag, steps):
            _override_repository(diag, steps, first.kind if first is not None else "")

    diag.hypothesis = _hypothesis(diag)
    return diag


def _hypothesis(diag: Diagnosis) -> str:
    """Mot cau, viet duoi dang co the bac bo duoc.

    Khac biet voi `summary` khong phai van phong: `summary` mo ta cai da quan sat, `hypothesis` noi
    cai duoc suy ra tu do va ai phai kiem lai no. Gop hai thu lam mot la cach mot quan sat am tham
    len cap thanh mot ket luan.
    """
    if diag.verdict == "PASS":
        return ""
    if diag.confidence == LOW:
        return (
            "Chua du bang chung de quy trach nhiem. Can them lan chay, hoac them check neo duoc "
            "vao mot buoc cu the, truoc khi sua bat cu thanh phan nao."
        )
    where = f"buoc {diag.first_error_step}"
    return (
        f"Gia thuyet ({diag.confidence}): nguyen nhan nam o `{diag.owner}` -- {taxonomy.describe(diag.category)}. "
        f"Kiem bang cach doc lai {where} trong trajectory va doi chieu voi `{diag.owner}`."
    )


@dataclass
class Cluster:
    category: str
    count: int
    runs: list[str]
    sample_evidence: list[str]
    owner: str
    suggestion: str


def cluster(diagnoses: Sequence[Diagnosis], *, support: int = 2) -> list[Cluster]:
    """Gom cac chan doan theo nhan, va **chi tra ve nhung nhom dat nguong ho tro**.

    Nguong la toan bo diem cua ham nay. Mot that bai don le la mot giai thoai: no co the la phuong
    sai cua model, mot lan goi tool xui, hay mot cau hoi mo ho. Sua than skill theo mot giai thoai
    la cach nhanh nhat de bao mon nhung chi tiet hiem ma quan trong trong do. Mot dang lap lai qua
    nhieu lan chay thi khac -- do la thu dang duoc viet vao.
    """
    by_category: dict[str, list[Diagnosis]] = {}
    for diag in diagnoses:
        if diag.verdict == "PASS":
            continue
        by_category.setdefault(diag.category, []).append(diag)

    clusters = []
    for category, group in by_category.items():
        if len(group) < support:
            continue
        evidence: list[str] = []
        for diag in group:
            evidence.extend(diag.evidence[:1])
        clusters.append(
            Cluster(
                category=category,
                count=len(group),
                runs=[d.run_id for d in group],
                sample_evidence=evidence[:5],
                owner=taxonomy.owner_of(category),
                suggestion=taxonomy.suggestion(category),
            )
        )
    return sorted(clusters, key=lambda c: c.count, reverse=True)


def below_support(diagnoses: Sequence[Diagnosis], *, support: int = 2) -> list[tuple[str, int]]:
    """Nhung nhan chua dat nguong, kem so lan. In ra de nguoi doc biet chung ton tai ma chua duoc
    hanh dong theo -- im lang ve chung se bien nguong thanh mot bo loc giau thong tin."""
    counts = Counter(d.category for d in diagnoses if d.verdict != "PASS")
    return sorted([(k, v) for k, v in counts.items() if v < support], key=lambda kv: -kv[1])
