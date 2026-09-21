"""Hinh dang chinh tac ma mot lan chay de lai, va mot so hieu phien ban cai quan chung.

Moi thu phia sau -- `debug`, `compare`, `replay`, va bat ky bo du lieu huan luyen nao sau nay --
chi doc nhung hinh dang nay. Do la ly do viet chung ra mot lan: mot bo chay xong roi vut di co the
truyen tuple qua lai, nhung mot ban ghi nam tren dia se duoc doc boi code viet sau no, nen hinh
dang cua no phai la mot loi hua chu khong phai mot thoi quen.

**Vi sao `Step` khong phai la `TraceRow`.** `trace.TraceRow` la dong cua hook, nguyen van, va no
nen o nguyen nhu the -- do la bang chung, va bang chung khong duoc nan lai cho tien dung. `Step`
la *cach doc* dong do: call ghep voi result, chi so duoc danh, actor duoc goi ten. Giu ca hai
nghia la moi ket luan trong mot chan doan deu lan nguoc ve duoc dong chua ai dong toi.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

#: Tang khi mot ban ghi cu khong con doc duoc bang code doc phien ban nay. Lan chay mang theo so
#: nay de `compare` tu choi hai ban ghi ma no se doc lech -- mot so sanh vat qua mot lan doi schema
#: la kieu ket qua sai trong y het mot ket qua dung.
SCHEMA_VERSION = 1

MAIN_SESSION = "main"


@dataclass(frozen=True)
class Step:
    """Mot khoanh khac da duoc doc, danh so tu 0 theo dung thu tu da xay ra."""

    index: int
    type: str
    at: str = ""
    actor: str = MAIN_SESSION
    tool: str = ""
    paths: tuple[str, ...] = ()
    command: str = ""
    args_digest: str = ""
    tool_use_id: str = ""
    ok: bool | None = None
    blocked: bool = False
    of_step: int | None = None
    detail: str = ""

    @property
    def is_subagent(self) -> bool:
        return self.actor != MAIN_SESSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["paths"] = list(self.paths)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["paths"] = tuple(kwargs.get("paths") or ())
        return cls(**kwargs)


#: Trang thai cua mot check. `passed` mot minh khong du: no gop "do vi skill sai" voi "khong cham
#: duoc" va voi "bang chung yeu", ba thu doi hoi ba hanh dong khac han nhau. Mot bang chi co
#: xanh/do se day ca ba vao cung mot cot va nguoi doc khong con cach nao tach chung ra.
PASS = "PASS"
FAIL = "FAIL"
#: Case doi bang chung, co mot lan thuc thi thanh cong sau lan ghi cuoi, nhung case khong goi ten
#: lenh nao -- nen "bang chung" o day co the chi la mot lenh vo thuong. Khong phai pass, khong phai
#: loi cua skill.
WEAK_EVIDENCE = "WEAK_EVIDENCE"
#: Dieu kien cua check khong ton tai trong lan chay nay (vi du: doi bang chung cho lan ghi, ma
#: khong co lan ghi nao). Khong co gi sai, va cung khong co gi duoc chung minh.
NOT_APPLICABLE = "NOT_APPLICABLE"
#: Thieu du lieu de phan quyet -- trace khong co dong ket qua, hoac judge khong tra loi.
UNDECIDED = "UNDECIDED"
#: Check can mot moi truong song (chay lenh, doc file) va moi truong do khong con. Khac han
#: `FAIL`: mot check cham vao fixture da bi xoa khong noi duoc gi ve skill.
NOT_EVALUATED = "NOT_EVALUATED"

#: Trang thai duoc tinh la "khong that bai" khi cong diem. `WEAK_EVIDENCE` khong nam trong day va
#: cung khong nam trong nhom that bai -- no duoc dem rieng, vi day chinh la cho mot bang toan mau
#: xanh bat dau khong con nghia gi.
PASSING = (PASS, NOT_APPLICABLE)
INCONCLUSIVE_STATUSES = (WEAK_EVIDENCE, UNDECIDED, NOT_EVALUATED)


@dataclass(frozen=True)
class CheckResult:
    """Mot phan quyet, cong hai thu bien phan quyet thanh hanh dong duoc.

    `at_step` la thu ma `diagnose.py` lay min de tim buoc sai dau tien, va no la ly do kieu nay ton
    tai thay vi mot tuple `(passed, why)`. Bo cham cu *da* biet chi so dong -- no viet chi so vao
    trong cau `why` -- nhung biet duoi dang van xuoi thi cach duy nhat lay lai la phan tich tieng
    Anh, va do khong phai thu de xay tiep len tren.

    `category` la mot khoa taxonomy, gan ngay tai cho that bai noi co bang chung, chu khong suy ra
    ve sau tu mot bao cao.
    """

    id: str
    kind: str
    passed: bool
    why: str
    at_step: int | None = None
    category: str = ""
    #: Mot trong cac hang so o tren. `passed` va `undecided` duoc suy ra tu day chu khong nguoc
    #: lai -- xem `CheckResult.of`.
    status: str = PASS
    #: Dat khi mot check khong the phan quyet duoc. Mot check khong phan quyet duoc khong bao gio
    #: la pass, va cung khong phai loi cua skill, nen no duoc bao cao tach khoi ca hai. Nguyen tac:
    #: tu choi cham con hon doan.
    undecided: bool = False
    #: Kiem chung duoc bang code, khong can model. `compare` xep hang bang chung theo truong nay:
    #: mot khac biet do check tat dinh chi ra nang hon mot khac biet do judge chi ra.
    deterministic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def of(
        cls,
        status: str,
        *,
        id: str,
        kind: str,
        why: str,
        at_step: int | None = None,
        category: str = "",
        deterministic: bool = True,
    ) -> "CheckResult":
        """Dung mot ket qua tu trang thai, de `passed`/`undecided` khong bao gio lech voi `status`.

        Truoc day ba truong nay duoc dat tay o tung cho, va mot cho quen dat la mot dong bao cao
        noi mot dang ma diem lai cong mot dang khac.
        """
        return cls(
            id=id,
            kind=kind,
            passed=status in PASSING,
            why=why,
            at_step=at_step,
            category=category if status == FAIL else "",
            status=status,
            undecided=status in INCONCLUSIVE_STATUSES,
            deterministic=deterministic,
        )


@dataclass
class RunRecord:
    """Moi thu ve mot lan chay ma khong phai chinh trajectory.

    Chi phi, thoi gian va so turn nam o day vi chung la ket qua hang nhat chu khong phai chu thich:
    `compare.py` tu choi goi mot candidate la tot hon chi dua tren do chinh xac, va no chi tu choi
    duoc neu nhung so nay ton tai. Chung co san trong chinh envelope JSON cua CLI.

    `workspace_rev` la manh con lai cua tinh tai lap: mot lan chay duoc xac dinh boi bo bon
    (skill_version, workspace_rev, case_digest, model). Thieu bat ky manh nao thi `replay` chi la
    "chay lai mot thu na na".
    """

    run_id: str
    case_id: str
    skill: str
    skill_version: str
    model: str
    #: Muc effort cua phien actor. Cung mot model o hai muc effort la hai cau hinh khac nhau, va
    #: gop chung lai se lam mot thay doi harness trong giong mot thay doi skill.
    effort: str = ""
    fixture: str = "copy"
    workspace_rev: str = ""
    case_digest: str = ""
    #: Ba truong con lai cua "cai gi da thay doi giua hai lan chay". Chung la chuoi tu do va rong
    #: theo mac dinh: phan lon workspace khong danh phien ban cho harness hay bo tool cua minh, va
    #: mot truong rong noi dung su that do -- ro hon la mot con so bia ra nghe co ve chinh xac.
    harness_version: str = ""
    toolset_version: str = ""
    knowledge_revision: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    exit_code: int = 0
    completed: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    #: Tran turn da dat cho lan chay nay. Ghi lai vi khong co no thi khong phan biet duoc "cham
    #: tran" voi "bi giet" -- ca hai deu chi la mot ma exit khac 0.
    max_turns: int = 0
    num_steps: int = 0
    num_tool_calls: int = 0
    actor_output: str = ""
    dry: bool = False
    #: `running` | `complete` | `error`. Ban ghi duoc tao TRUOC khi actor chay, de mot lan chay
    #: sap chet van de lai dau vet -- nhung hau qua la mot lan chay dang chay do va mot lan chay
    #: da that bai trong y het nhau trong moi bang gop: ca hai deu khong co diem.
    #:
    #: Do do duoc: `matrix` in ra `claude-opus-5/high  1 lan chay  0.0% ty le xanh` cho mot lan
    #: chay dang chay gio thu nhat. Con so 0% do khong sai ve co hoc va hoan toan sai ve y nghia.
    #:
    #: Mac dinh la `complete` de cac ban ghi cu -- viet truoc khi co truong nay -- khong bi doc
    #: thanh "dang chay" vinh vien.
    status: str = "complete"
    label: str = ""
    schema_version: int = SCHEMA_VERSION
    tags: tuple[str, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)

    #: Cac truong xac dinh mot lan chay. Hai lan chay khac nhau o bat ky truong nao trong day la
    #: hai thi nghiem khac nhau, va so sanh chung ma khong noi ro da doi gi la cach nhanh nhat quy
    #: mot cai thien cua model thanh mot cai thien cua skill.
    IDENTITY_FIELDS = (
        "skill_version",
        "workspace_rev",
        "case_digest",
        "model",
        "effort",
        "harness_version",
        "toolset_version",
        "knowledge_revision",
    )

    def identity(self) -> dict[str, str]:
        return {field: str(getattr(self, field) or "") for field in self.IDENTITY_FIELDS}

    @property
    def model_config(self) -> str:
        """`<model>/<effort>` -- don vi cua mot o trong bang model matrix."""
        return f"{self.model}/{self.effort}" if self.effort else self.model

    @property
    def version_label(self) -> str:
        """`<skill>@<hash>`, hoac `<skill>@<label>` khi nguoi chay dat ten cho phien ban.

        Mot hash noi chinh xac *cai gi* da chay nhung khong noi duoc y dinh; mot nhan noi y dinh
        nhung co the noi doi. In ca hai canh nhau la cach duy nhat khong phai chon.
        """
        if self.label:
            return f"{self.skill}@{self.label}"
        return f"{self.skill}@{self.skill_version}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["tags"] = tuple(kwargs.get("tags") or ())
        return cls(**kwargs)


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def skill_version(skill_dir: Path) -> str:
    """`<sha12>` cua `SKILL.md`, hoac `missing` khi khong co file do.

    Phan lon workspace khong danh phien ban cho skill, nen mot phong thi nghiem can noi "lan chay
    nay dung skill khac lan chay kia" phai tu suy ra cau tra loi. Hash noi dung la cach suy trung
    thuc: no doi dung luc byte ma actor doc doi, no khong can mot file moi ma ai do phai nho tang,
    va hai nguoi chua bao gio ban bac se tinh ra cung mot gia tri. No khong dien dat duoc y dinh
    (`1.8.3` noi "ban sua thu ba"; mot hash khong noi gi), va do la ly do `--label` ton tai.
    """
    body = skill_dir / "SKILL.md"
    if not body.is_file():
        return "missing"
    return hashlib.sha256(body.read_bytes()).hexdigest()[:12]


def build_trajectory(rows: Iterable[Any]) -> list[Step]:
    """Row cua hook -> step co chi so, ghep moi `tool_result` ve dung call ma no tra loi.

    Ghep bang `tool_use_id`, do host cap va hook ghi lai. Vi tri co y khong duoc dung lam duong
    lui: subagent xen ke voi phien chinh, nen "ket qua ngay sau call nay" thuong xuyen la ket qua
    cua nguoi khac, va mot chan doan xay tren do se do loi sai buoc -- te hon la khong co ket qua.

    Row do mot hook cu ghi (khong `tool_use_id`, khong dong result) van chuan hoa duoc, thanh
    rieng cac call; `ok` o nguyen `None`, va `diagnose.py` doc `None` la "khong quan sat duoc" chu
    khong phai "thanh cong".
    """
    steps: list[Step] = []
    call_index: dict[str, int] = {}
    for row in rows:
        use_id = row.tool_use_id
        index = len(steps)
        if row.event == "tool_result":
            steps.append(
                Step(
                    index=index,
                    type="tool_result",
                    at=row.at,
                    actor=row.actor,
                    tool=row.tool,
                    tool_use_id=use_id,
                    ok=row.ok,
                    blocked=row.blocked,
                    of_step=call_index.get(use_id),
                    detail=row.detail,
                )
            )
            continue
        if use_id:
            call_index[use_id] = index
        steps.append(
            Step(
                index=index,
                type="tool_call",
                at=row.at,
                actor=row.actor,
                tool=row.tool,
                paths=row.paths,
                command=row.command,
                args_digest=row.args_digest,
                tool_use_id=use_id,
            )
        )
    return steps


def call_steps(steps: Sequence[Step]) -> list[Step]:
    """Chi cac step `tool_call`, van mang chi so trajectory cua chinh chung.

    Moi tieu chi so sanh thu tu deu phai nhin cung mot day con, neu khong thi "buoc 7" mang hai
    nghia khac nhau tuy ai noi.
    """
    return [s for s in steps if s.type == "tool_call"]


def result_of(steps: Sequence[Step], call_index: int) -> Step | None:
    for step in steps:
        if step.type == "tool_result" and step.of_step == call_index:
            return step
    return None
