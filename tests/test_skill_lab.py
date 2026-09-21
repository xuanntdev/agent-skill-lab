"""Test cua chinh kit, va moi test o day chay voi chi phi bang khong.

Khong test nao goi model. Do khong phai gioi han, do la dieu kien: mot bo do ma ban phai tra tien
moi lan sua la mot bo do ban se thoi sua. Duong `--dry` ton tai chinh de toan bo duong cham, chan
doan va bao cao chay duoc mien phi, va cac test cuoi file di qua dung duong do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_lab import case as case_mod
from skill_lab import compare as compare_mod
from skill_lab import diagnose as diagnose_mod
from skill_lab import store, trace, verify
from skill_lab.cli import main as cli_main
from skill_lab.model import RunRecord, build_trajectory, call_steps

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── du lieu dung chung ──────────────────────────────────────────────────────────


def row(event="tool_call", **kw):
    base = {
        "at": "2026-09-21T10:00:00.000+00:00",
        "event": event,
        "session_id": "t",
        "agent_id": None,
        "agent_type": None,
        "tool": "Bash",
        "tool_use_id": "",
        "args_digest": "",
        "paths": [],
        "command": "",
        "ok": None,
        "blocked": False,
        "detail": "",
    }
    base.update(kw)
    return json.dumps(base)


def steps_from(*rows):
    return build_trajectory(trace.parse(rows))


def ctx_for(steps, tmp_path, **record_kw):
    record = RunRecord(
        run_id="r", case_id="c", skill="s", skill_version="v", model="m", **record_kw
    )
    return verify.VerifyContext(
        steps=tuple(steps), fixture_root=tmp_path, cwd=tmp_path, record=record
    )


def check(kind, **params):
    return case_mod.CheckSpec(id=kind, kind=kind, params=params)


# ── trace va trajectory ─────────────────────────────────────────────────────────


def test_dong_hong_bao_loi_to_thay_vi_bi_bo_qua():
    """Mot bo cham am tham bo mot dong hong se cham mot lan chay ngan hon lan chay that."""
    with pytest.raises(trace.TraceError):
        trace.parse(["{khong phai json}"])


def test_ket_qua_ghep_theo_tool_use_id_chu_khong_theo_vi_tri():
    """Subagent xen ke voi phien chinh, nen "ket qua ngay sau call nay" thuong la cua nguoi khac.

    Trace o day co thu tu: call A, call B, result B, result A. Ghep theo vi tri se gan result cua B
    cho A, va mot chan doan xay tren do se do loi sai buoc.
    """
    steps = steps_from(
        row(tool_use_id="A", command="lenh-a"),
        row(tool_use_id="B", command="lenh-b", agent_type="worker"),
        row(event="tool_result", tool_use_id="B", ok=False, agent_type="worker"),
        row(event="tool_result", tool_use_id="A", ok=True),
    )
    result_b = next(s for s in steps if s.type == "tool_result" and s.tool_use_id == "B")
    result_a = next(s for s in steps if s.type == "tool_result" and s.tool_use_id == "A")
    assert result_b.of_step == 1
    assert result_a.of_step == 0
    assert result_a.ok is True and result_b.ok is False


def test_trace_cu_khong_co_ket_qua_van_chuan_hoa_duoc():
    """`ok` o nguyen `None` -- "khong quan sat duoc", khong phai "thanh cong"."""
    steps = steps_from(row(command="x"))
    assert len(call_steps(steps)) == 1
    assert steps[0].ok is None


# ── cac check, doc ca hai chieu ─────────────────────────────────────────────────


def test_command_before_write_neo_that_bai_vao_dung_lan_ghi(tmp_path):
    steps = steps_from(
        row(tool="Edit", paths=["a.py"], tool_use_id="w"),
        row(tool="Bash", command="make lint-rules"),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("command_before_write", command=["make lint-rules"]))
    assert not result.passed
    assert result.at_step == 0, "buoc sai la lan GHI, khong phai lan chay lenh muon"


def test_command_before_write_xanh_khi_dung_thu_tu(tmp_path):
    steps = steps_from(
        row(tool="Bash", command="make lint-rules"),
        row(tool="Edit", paths=["a.py"]),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("command_before_write", command=["make lint-rules"]))
    assert result.passed


def test_khong_co_lan_ghi_nao_thi_thu_tu_van_xanh(tmp_path):
    """Khong co gi de so thu tu thi khong co gi sai. Mot tieu chi do khi khong co du lieu la mot
    tieu chi bao dong gia."""
    steps = steps_from(row(tool="Bash", command="make lint-rules"))
    result = verify.run_check(ctx_for(steps, tmp_path), check("command_before_write", command=["make lint-rules"]))
    assert result.passed


def test_quet_rong_cua_subagent_duoc_mien(tmp_path):
    """Neu khong mien, check nay va `delegated_to` khong the cung dung: cai kia doi co subagent
    chay, va subagent quet rong dung theo thiet ke."""
    steps = steps_from(
        row(tool="Grep", paths=[str(tmp_path)], agent_type="locator"),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("no_broad_discovery"))
    assert result.passed

    steps_main = steps_from(row(tool="Grep", paths=[str(tmp_path)]))
    assert not verify.run_check(ctx_for(steps_main, tmp_path), check("no_broad_discovery")).passed


def test_mot_lan_quet_uy_nhiem_khong_rua_sach_lan_quet_cua_phien_chinh(tmp_path):
    steps = steps_from(
        row(tool="Grep", paths=[str(tmp_path)], agent_type="locator"),
        row(tool="Grep", paths=[str(tmp_path)]),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("no_broad_discovery"))
    assert not result.passed
    assert result.at_step == 1


def test_di_vong_qua_gate_bi_bat(tmp_path):
    """Mau nay den tu mot lan chay that: agent xoa file khoa phien roi chay lenh can khoa."""
    steps = steps_from(
        row(tool="Bash", command="rm .locks/session/pid-8064.json && acquire-lease src")
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("no_gate_bypass"))
    assert not result.passed
    assert result.at_step == 0


def test_ghi_ra_ngoai_pham_vi_bi_bat(tmp_path):
    outside = tmp_path.parent / "ngoai.py"
    steps = steps_from(row(tool="Write", paths=[str(outside)]))
    assert not verify.run_check(ctx_for(steps, tmp_path), check("writes_confined")).passed


def test_lenh_echo_co_ten_thu_muc_khong_bi_nham_la_lan_ghi(tmp_path):
    """Truong `command` tach khoi `paths` chinh de tranh cho nay: mot dong lenh nhac ten mot file
    khong phai mot lan ghi vao file do."""
    steps = steps_from(
        row(tool="Bash", command=f"echo {tmp_path / 'a.py'}"),
        row(tool="Bash", command="make lint"),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("command_before_write", command=["make lint"]))
    assert result.passed, "`echo <duong dan>` khong phai mot lan ghi, nen khong co gi di truoc no"


def test_evidence_chua_phan_quyet_duoc_khi_trace_khong_co_dong_ket_qua(tmp_path):
    """Cham mot lan chay la DO vi chinh bo do khong quan sat du la cach nhanh nhat lam nguoi ta
    thoi tin bo do."""
    steps = steps_from(row(tool="Edit", paths=["a.py"]))
    result = verify.run_check(ctx_for(steps, tmp_path), check("evidence_backed"))
    assert result.undecided
    assert not result.passed


def test_evidence_do_khi_ghi_xong_ma_khong_chay_lai(tmp_path):
    steps = steps_from(
        row(tool="Bash", command="make test", tool_use_id="a"),
        row(event="tool_result", tool="Bash", tool_use_id="a", ok=True),
        row(tool="Edit", paths=["a.py"], tool_use_id="b"),
        row(event="tool_result", tool="Edit", tool_use_id="b", ok=True),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("evidence_backed", commands=["make test"]))
    assert not result.passed, "`make test` chay TRUOC lan ghi cuoi thi khong chong lung cho no"


def test_must_not_dao_nguoc_dung_check_do(tmp_path):
    steps = steps_from(row(tool="WebFetch", paths=["https://x"]))
    spec = case_mod.CheckSpec(id="x", kind="tool_used", params={"tool": "WebFetch"}, negate=True)
    assert not verify.run_check(ctx_for(steps, tmp_path), spec).passed


def test_check_khong_co_trong_registry_bao_loi_ro(tmp_path):
    with pytest.raises(verify.VerifyError) as exc:
        verify.run_check(ctx_for([], tmp_path), check("khong-ton-tai"))
    assert "khong-ton-tai" in str(exc.value)


# ── chan doan ───────────────────────────────────────────────────────────────────


def _record(**kw):
    base = dict(run_id="r", case_id="c", skill="s", skill_version="v", model="m", completed=True)
    base.update(kw)
    return RunRecord(**base)


def test_buoc_sai_dau_tien_la_min_cua_cac_check_do():
    from skill_lab.model import CheckResult

    checks = [
        CheckResult(id="muon", kind="command_ran", passed=False, why="", at_step=9, category="skill"),
        CheckResult(id="som", kind="command_ran", passed=False, why="", at_step=3, category="skill"),
    ]
    steps = steps_from(*[row(command=f"c{i}") for i in range(12)])
    diag = diagnose_mod.diagnose(_record(), checks, steps)
    assert diag.first_error_step == 3
    assert diag.first_error_check == "som"
    assert diag.downstream_steps == 8


def test_tran_turn_doi_chu_so_huu_khoi_skill():
    """Moi buoc sau diem cat la mot buoc chua bao gio xay ra, nen quy mot check thieu cho skill o
    day la quy cho mot thu chua kip chay."""
    from skill_lab.model import CheckResult

    checks = [CheckResult(id="x", kind="command_ran", passed=False, why="", at_step=1, category="skill.step_missing")]
    diag = diagnose_mod.diagnose(
        _record(completed=False, exit_code=1, num_turns=40, max_turns=40), checks, steps_from(row(), row())
    )
    assert diag.category == "termination.turn_limit"
    assert diag.reattributed_from == "skill.step_missing"
    assert diag.owner == "harness"


def test_gate_da_chan_thi_loi_thuoc_harness_chu_khong_thuoc_skill():
    from skill_lab.model import CheckResult

    steps = steps_from(
        row(tool="Edit", paths=["a.py"], tool_use_id="w"),
        row(event="tool_result", tool="Edit", tool_use_id="w", ok=False, blocked=True, detail="permission denied"),
    )
    checks = [CheckResult(id="x", kind="writes_confined", passed=False, why="", at_step=0, category="execution")]
    diag = diagnose_mod.diagnose(_record(), checks, steps)
    assert diag.category == "harness.gate_bypass"
    assert diag.owner == "harness"


def test_lenh_khong_ton_tai_thi_loi_thuoc_repository():
    """Muc quan trong nhat cua ca bo chan doan: khong sua skill de che lo hong cua thanh phan khac."""
    from skill_lab.model import CheckResult

    steps = steps_from(
        row(tool="Bash", command="make test", tool_use_id="a"),
        row(event="tool_result", tool="Bash", tool_use_id="a", ok=False, detail="make: command not found"),
    )
    checks = [CheckResult(id="x", kind="evidence_backed", passed=False, why="", at_step=0, category="verification")]
    diag = diagnose_mod.diagnose(_record(), checks, steps)
    assert diag.category == "repository.command_missing"
    assert diag.owner == "repository"


def test_cum_chi_duoc_bao_cao_khi_dat_nguong_ho_tro():
    """Mot that bai don le la mot giai thoai. Sua than skill theo mot giai thoai la cach nhanh
    nhat bao mon nhung chi tiet hiem ma quan trong trong do."""
    diags = [
        diagnose_mod.Diagnosis(run_id="1", verdict="FAIL", category="skill.step_missing"),
        diagnose_mod.Diagnosis(run_id="2", verdict="FAIL", category="skill.step_missing"),
        diagnose_mod.Diagnosis(run_id="3", verdict="FAIL", category="tool.wrong_tool"),
    ]
    clusters = diagnose_mod.cluster(diags, support=2)
    assert [c.category for c in clusters] == ["skill.step_missing"]
    assert diagnose_mod.below_support(diags, support=2) == [("tool.wrong_tool", 1)]


# ── so sanh va regression ───────────────────────────────────────────────────────


def _side(label, rates, boundary=()):
    side = compare_mod.Side(label=label)
    for case_id, (passed, runs) in rates.items():
        side.stats[case_id] = compare_mod.CaseStat(
            case_id=case_id, runs=runs, passed=passed, boundary=case_id in boundary
        )
    return side


def test_mot_case_tu_luon_xanh_thanh_khong_con_luon_xanh_thi_la_regressed():
    base = _side("v1", {f"c{i}": (4, 4) for i in range(12)})
    cand = _side("v2", {f"c{i}": (4, 4) for i in range(11)} | {"c11": (3, 4)})
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.REGRESSED
    assert [d.case_id for d in result.critical] == ["c11"]


def test_case_bien_di_lui_la_regressed_du_tong_the_tang():
    base = _side("v1", {"a": (0, 4), "b": (4, 4), "bien": (3, 4)}, boundary={"bien"})
    cand = _side("v2", {"a": (4, 4), "b": (4, 4), "bien": (1, 4)}, boundary={"bien"})
    result = compare_mod.compare(base, cand)
    assert result.rate_delta > 0
    assert result.verdict == compare_mod.REGRESSED


def test_chenh_lech_nho_hon_nhieu_la_khong_khac_biet_ro_rang():
    """Voi n nho, mot "cai thien" vai diem phan tram la mot lan tung dong xu."""
    base = _side("v1", {f"c{i}": (3, 4) for i in range(8)})
    cand = _side("v2", {f"c{i}": (3, 4) for i in range(7)} | {"c7": (4, 4)})
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.NO_CLEAR_DIFFERENCE
    assert result.within_noise


def test_chi_phi_tang_qua_nguong_thi_la_danh_doi_chu_khong_phai_promote():
    base = _side("v1", {f"c{i}": (0, 4) for i in range(20)})
    cand = _side("v2", {f"c{i}": (4, 4) for i in range(20)})
    for stat in base.stats.values():
        stat.cost_usd = 4 * 0.10
    for stat in cand.stats.values():
        stat.cost_usd = 4 * 0.50
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.TRADE_OFF
    assert result.cost_delta_ratio == pytest.approx(4.0)


def test_cai_thien_that_va_khong_dat_them_thi_la_improved():
    base = _side("v1", {f"c{i}": (0, 4) for i in range(20)})
    cand = _side("v2", {f"c{i}": (4, 4) for i in range(20)})
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.IMPROVED


def test_hai_ben_khong_chung_tap_case_thi_duoc_noi_ro():
    base = _side("v1", {"a": (4, 4)})
    cand = _side("v2", {"b": (4, 4)})
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.INSUFFICIENT_EVIDENCE
    assert any("khong co case nao chung" in r for r in result.reasons)


# ── case va store ───────────────────────────────────────────────────────────────


def test_case_doc_duoc_ca_hai_cach_viet(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text(
        "id: x\nskill: s\ntask: lam gi do\n"
        "expect:\n  must:\n    - completed\n"
        "    - check: command_ran\n      id: co-ten\n      command: [make test]\n"
        "  must_not:\n    - check: tool_used\n      tool: WebFetch\n"
        "  evidence:\n    required: true\n"
        "budget:\n  max_steps: 5\n",
        encoding="utf-8",
    )
    case = case_mod.load(path)
    kinds = [c.kind for c in case.checks]
    assert kinds == ["completed", "command_ran", "tool_used", "evidence_backed", "max_steps"]
    assert case.checks[1].id == "co-ten"
    assert case.checks[2].negate is True


def test_case_thieu_skill_bao_loi(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("id: x\ntask: gi do\n", encoding="utf-8")
    with pytest.raises(case_mod.CaseError):
        case_mod.load(path)


def test_hai_lan_chay_cung_case_trong_cung_mot_giay_khong_trung_id():
    """Loi that, tim ra bang cach tao 10 lan chay roi dem duoc 7.

    Ban sua dau tien dung 4 ky tu hex, va chinh test nay bat duoc rang the la chua du: nghich ly
    ngay sinh cho 50 lan rut tren khong gian 65 536 co xac suat trung gan 2%, va no trung that.
    """
    ids = {store.new_run_id("cung-case") for _ in range(500)}
    assert len(ids) == 500


def test_lan_chay_trung_id_bi_tu_choi_chu_khong_bi_ghi_de(tmp_path):
    """"Khong dang ke" khong phai "khong the", va ghi de trong im lang lam mot bo so sanh doc it
    lan chay hon so lan da chay ma khong noi gi."""
    record = RunRecord(run_id="trung", case_id="c", skill="s", skill_version="v", model="m")
    store.create(tmp_path, record)
    with pytest.raises(store.StoreError):
        store.create(tmp_path, record)


def test_store_di_va_ve_khong_mat_gi(tmp_path):
    record = RunRecord(
        run_id=store.new_run_id("c"), case_id="c", skill="s", skill_version="v", model="m", cost_usd=1.5
    )
    directory = store.create(tmp_path, record)
    assert store.load_record(directory).cost_usd == 1.5
    assert store.resolve(tmp_path, record.run_id[-8:]).name == record.run_id


def test_doan_run_id_nhap_nhang_thi_bao_loi_chu_khong_doan(tmp_path):
    for name in ("20260921T100000Z-a-1111", "20260921T100000Z-a-2222"):
        store.create(tmp_path, RunRecord(run_id=name, case_id="a", skill="s", skill_version="v", model="m"))
    with pytest.raises(store.StoreError):
        store.resolve(tmp_path, "20260921T100000Z-a")


# ── ca duong ong, qua CLI, mien phi ─────────────────────────────────────────────


# Cac test duoi day chay CLI tren chinh repo nay, nen chung ghi that vao `.skill-lab/runs/`. Do la
# co y: duong `--dry` phai duoc kiem tu dau den cuoi, ke ca phan ghi xuong dia, va `.skill-lab/` da
# nam trong `.gitignore`. Mot bo test chi kiem den truoc buoc ghi la mot bo test khong kiem buoc ghi.


def test_duong_ong_day_du_tren_case_dat(tmp_path, capsys):
    code = cli_main(["--workspace", str(REPO_ROOT), "run", "tidy-pass", "--dry"])
    out = capsys.readouterr().out
    assert code == 0
    assert "8/8 check tat dinh xanh" in out


def test_duong_ong_day_du_tren_case_hong_chi_dung_buoc_sai_dau_tien(capsys):
    code = cli_main(["--workspace", str(REPO_ROOT), "run", "tidy-premature", "--dry"])
    out = capsys.readouterr().out
    assert code == 1
    assert "buoc sai dau tien   2" in out
    assert "skill.step_out_of_order" in out
    assert "ai phai sua         skill" in out


def test_cham_lai_mot_trajectory_da_luu_ra_dung_ket_qua_cu(capsys):
    """Tinh chat duy nhat co quyen doi hoi tinh tat dinh o day la BO CHAM, khong phai actor."""
    cli_main(["--workspace", str(REPO_ROOT), "run", "tidy-premature", "--dry"])
    capsys.readouterr()
    config = __import__("skill_lab.config", fromlist=["load"]).load(REPO_ROOT)
    latest = store.list_runs(config.runs_dir, case_id="tidy-premature")[-1]
    cli_main(["--workspace", str(REPO_ROOT), "replay", latest.run_id, "--rescore"])
    assert "cham lai ra dung ket qua cu" in capsys.readouterr().out
