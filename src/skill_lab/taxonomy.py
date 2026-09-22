"""Chuyen gi da sai -- co y giu nong.

Mot taxonomy chi dang gia bang bang chung dung sau no. Bia ra bon muoi nhanh con tu dau se cho ra
mot bo tu vung khong ai gan nhat quan duoc, va trieu chung dau tien la hai nguoi dan hai nhan khac
nhau len cung mot trace. Nen tang tren la day du -- day la nhung noi mot that bai co the thuc su
nam -- con tang duoi chi giu nhung nhanh **suy thang ra duoc tu mot check da that bai**, cong
nhung nhanh da tung quan sat duoc it nhat mot lan.

Bo them mot nhanh thu nam can mot trace, khong phai mot truc giac.
"""

from __future__ import annotations

#: Muoi mot noi mot that bai co the nam. `unknown` khong phai mot lo hong can lap: mot chan doan
#: trung thuc noi "chua du bang chung" dang gia hon mot chan doan goi ten thanh phan hop ly nhat o
#: gan do, vi loai thu hai se duoc hanh dong theo.
CATEGORIES = (
    "skill",
    "knowledge",
    "context",
    "tool",
    "harness",
    "repository",
    "execution",
    "verification",
    "termination",
    "model",
    "unknown",
)

#: nhan -> (nghia mot dong, buoc sua thuong dung)
SUBCATEGORIES: dict[str, tuple[str, str]] = {
    "skill.step_missing": (
        "mot buoc skill yeu cau khong he xuat hien trong trace",
        "noi ro buoc do la bat buoc, va noi ro dau hieu nao cho phep bo qua no",
    ),
    "skill.step_out_of_order": (
        "buoc co chay nhung sau buoc ma le ra no phai di truoc",
        "viet rang buoc thu tu thanh mot cau menh lenh, khong de nguoi doc suy ra tu danh so",
    ),
    "skill.premature_completion": (
        "actor tuyen bo xong truoc khi co bang chung thuc thi",
        "them tieu chi hoan thanh tuong minh va doi bang chung kem theo",
    ),
    "skill.over_triggering": (
        "actor lam viec ma case nay khong doi -- kich hoat thua",
        "viet ro dieu kien KHONG ap dung, khong chi dieu kien ap dung",
    ),
    "tool.wrong_tool": ("dung tool khong phu hop cho viec do", "chi dinh tool cho buoc do trong than skill"),
    "tool.broad_sweep": (
        "quet rong tu phien chinh thay vi uy nhiem",
        "uy nhiem buoc do cho subagent, hoac thu hep pham vi tim kiem",
    ),
    "verification.self_asserted": (
        "ket qua kiem chung do chinh agent dat thay vi do exit code dat",
        "chan duong ghi tay vao ban ghi ket qua o tang harness, dung o tang chi dan",
    ),
    "verification.missing_evidence": (
        "khong co lan thuc thi nao chong lung cho tuyen bo da xong",
        "doi mot lenh chay that va exit code cua no truoc khi cho phep ket thuc",
    ),
    "harness.gate_bypass": (
        "agent di vong qua mot co che cuong che thay vi lam theo no",
        "vá chinh gate; mot chi dan khong bit duoc lo ma gate de ho",
    ),
    "harness.gate_not_enforced": (
        "gate ma workspace yeu cau khong con hieu luc ben trong fixture",
        "bo sung buoc cai dat con thieu vao `fixture.setup`; dung chay actor cho toi khi gate xanh",
    ),
    "harness.instrumentation_failed": (
        "hook ghi trajectory cua chinh lab khong chay duoc, nen lan chay se khong ghi lai gi",
        "sua duong cai hook (interpreter, quyen chay, duong dan); dung chay actor khi probe con do",
    ),
    "harness.no_trajectory": (
        "actor ket thuc nhung khong mot tool call nao duoc ghi",
        "kiem hook truoc (probe co qua khong), roi moi hoi actor co that su khong goi tool nao",
    ),
    "harness.tool_failure": (
        "tool that bai lap lai va lan chay khong hoi phuc duoc",
        "sua tool hoac them duong hoi phuc; day khong phai loi cua skill",
    ),
    "termination.aborted": (
        "lan chay bi cat giua chung: bi giet, timeout, hoac tien trinh cha chet",
        "chay lai; khong ket luan gi ve skill tu mot lan chay bi cat",
    ),
    "termination.turn_limit": (
        "lan chay bi cat vi cham tran turn, khong phai vi skill sai",
        "nang tran turn roi do lai truoc khi ket luan bat cu dieu gi ve skill",
    ),
    "repository.command_missing": (
        "skill bao chay mot lenh ma repo nay khong co",
        "sua repo hoac sua case; dung sua skill de che lo nay",
    ),
    "execution.out_of_bounds": ("ghi ra ngoai pham vi cho phep", "thu hep pham vi ghi o tang harness"),
    "execution.over_budget": ("vuot ngan sach buoc, tien hoac thoi gian", "cat viec thua, hoac noi lai ngan sach"),
}

#: Mot check that bai thi mac dinh chi vao thanh phan nao. Day la *cach doc mac dinh*; mot trace co
#: the lat no -- `diagnose.py` chuyen mot that bai khoi `skill` sang `harness` hoac `repository`
#: khi trace cho thay agent da lam dung va moi truong tu choi. Do la ly do co che lat nay ton tai:
#: mot skill bi sua de che loi cua thanh phan khac la mot skill gio co hai loi.
KIND_CATEGORY: dict[str, str] = {
    "command_ran": "skill.step_missing",
    "command_order": "skill.step_out_of_order",
    "command_before_write": "skill.step_out_of_order",
    "delegated_to": "skill.step_missing",
    "no_broad_discovery": "tool.broad_sweep",
    "no_main_edit": "verification.self_asserted",
    "no_gate_bypass": "harness.gate_bypass",
    "writes_confined": "execution.out_of_bounds",
    "tool_used": "tool.wrong_tool",
    "file_exists": "execution",
    "file_contains": "execution",
    "shell": "repository",
    "evidence_backed": "verification.missing_evidence",
    "max_steps": "execution.over_budget",
    "max_cost_usd": "execution.over_budget",
    "max_duration_s": "execution.over_budget",
    "completed": "termination",
    "judge": "skill",
}

_TOP_LEVEL_TEXT = {
    "skill": "than skill: thieu buoc, sai thu tu, hoac cau lenh mo ho",
    "knowledge": "tri thuc: thieu context, hoac context da cu",
    "context": "context dua vao phien khong du hoac sai",
    "tool": "tool: chon sai tool, hoac tham so sai",
    "harness": "harness: vong lap, gate, hoac co che cuong che",
    "repository": "repository: thieu lenh, thieu file, moi truong khong chay duoc",
    "execution": "thuc thi: ghi sai cho, vuot ngan sach, ket qua khong dung",
    "verification": "kiem chung: thieu bang chung, hoac bang chung tu khai",
    "termination": "ket thuc: dung som, hoac bi cat vi tran turn",
    "model": "nang luc model",
    "unknown": "chua du bang chung de quy trach nhiem cho thanh phan nao",
}


def top_level(label: str) -> str:
    return (label or "unknown").split(".", 1)[0]


def describe(label: str) -> str:
    entry = SUBCATEGORIES.get(label)
    if entry:
        return entry[0]
    return _TOP_LEVEL_TEXT.get(top_level(label), "chua phan loai")


def suggestion(label: str) -> str:
    entry = SUBCATEGORIES.get(label)
    return entry[1] if entry else ""


def category_for(kind: str) -> str:
    return KIND_CATEGORY.get(kind, "unknown")


def owner_of(label: str) -> str:
    """Ai phai sua. Day la cau hoi ma mot chan doan ton tai de tra loi, va no khong phai luc nao
    cung la "skill" -- do chinh la diem cua muc 15 trong de bai."""
    return {
        "skill": "skill",
        "knowledge": "knowledge",
        "context": "knowledge",
        "tool": "tool",
        "harness": "harness",
        "repository": "repository",
        "execution": "skill",
        "verification": "harness",
        "termination": "harness",
        "model": "model",
    }.get(top_level(label), "chua ro")
