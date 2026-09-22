"""Moi loi do dot audit tim ra, moi loi mot test.

Cac test o day khong nham vao tinh nang. Chung nham vao **nhung cho bo do noi mot dieu ma no
khong lam**, vi do la loai loi duy nhat mot phong thi nghiem khong duoc phep co: mot tinh nang
thieu thi nguoi dung biet, con mot phep do sai thi nguoi dung tin.

Moi test mo dau bang cau da do duoc truoc khi sua.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from skill_lab import case as case_mod
from skill_lab import compare as compare_mod
from skill_lab import config as config_mod
from skill_lab import diagnose as diagnose_mod
from skill_lab import experiment as experiment_mod
from skill_lab import model as model_mod
from skill_lab import runner, store, trace, verify
from skill_lab.model import CheckResult, RunRecord, build_trajectory

REPO_ROOT = Path(__file__).resolve().parent.parent
#: Workspace gia ma cong cu do. KHONG phai repo nay: repo nay la cong cu, thu muc kia la du lieu
#: thu. Tron hai thu lam mot la cach khong ai con doc ra duoc cai nao dang do cai nao.
DEMO_WORKSPACE = REPO_ROOT / "tests" / "fixtures" / "demo-workspace"


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


def ctx_for(steps, root, *, environment=True, **record_kw):
    record = RunRecord(run_id="r", case_id="c", skill="s", skill_version="v", model="m", **record_kw)
    return verify.VerifyContext(
        steps=tuple(steps), fixture_root=root, cwd=root, record=record, environment=environment
    )


def check(kind, **params):
    return case_mod.CheckSpec(id=kind, kind=kind, params=params)


def record_of(**kw):
    base = dict(run_id="r", case_id="c", skill="s", skill_version="v", model="m", completed=True)
    base.update(kw)
    return RunRecord(**base)


# ── A1/A2/A3: `--rescore` khong duoc cham vao the gioi ben ngoai ────────────────


def test_check_moi_truong_khong_chay_subprocess_khi_fixture_da_mat(tmp_path):
    """Da do duoc: mot check `shell` VAN chay `subprocess` that trong `--rescore`. Mot lenh tu nhan
    la "chi cham lai trajectory" van tao duoc file tren dia."""
    marker = tmp_path / "khong-duoc-tao.txt"
    spec = check("shell", command=[sys.executable, "-c", f"open(r'{marker}','w').write('x')"])
    result = verify.run_check(ctx_for([], tmp_path, environment=False), spec)
    assert result.status == model_mod.NOT_EVALUATED
    assert not marker.exists(), "`--rescore` da chay mot lenh that"


def test_check_file_tra_khong_do_duoc_chu_khong_tra_mau_do(tmp_path):
    """Da do duoc: `file_exists` tra MAU DO voi ly do "file khong ton tai trong fixture", trong khi
    su that la fixture da bi xoa -- bien "khong do duoc" thanh "skill sai"."""
    result = verify.run_check(
        ctx_for([], tmp_path, environment=False), check("file_exists", path="README.md")
    )
    assert result.status == model_mod.NOT_EVALUATED
    assert not result.passed and result.undecided


def test_check_moi_truong_van_chay_binh_thuong_khi_fixture_con_song(tmp_path):
    (tmp_path / "co-that.txt").write_text("x", encoding="utf-8")
    result = verify.run_check(
        ctx_for([], tmp_path, environment=True), check("file_exists", path="co-that.txt")
    )
    assert result.status == model_mod.PASS


def test_bo_cham_tu_khai_bao_khi_no_khong_tat_dinh():
    """Da do duoc: cung mot trajectory, cung mot bo cham, hai ket qua khac nhau -- vi case co
    `shell:`. Tuyen bo "bo cham tat dinh" trong truong hop do la mot loi hua khong giu duoc."""
    assert verify.is_deterministic([check("command_ran", command=["x"])])
    assert not verify.is_deterministic([check("command_ran", command=["x"]), check("shell", command=["x"])])


# ── A4: `evidence_backed` co bon trang thai ────────────────────────────────────


def _write_then(command: str, ok: bool = True):
    return steps_from(
        row(tool="Edit", paths=["a.py"], tool_use_id="w"),
        row(event="tool_result", tool="Edit", tool_use_id="w", ok=True),
        row(tool="Bash", command=command, tool_use_id="c"),
        row(event="tool_result", tool="Bash", tool_use_id="c", ok=ok),
    )


def test_lenh_vo_thuong_sau_lan_ghi_la_bang_chung_yeu_chu_khong_phai_pass(tmp_path):
    """Da do duoc: `git status` chay sau lan ghi cuoi lam `evidence_backed` XANH. `git status`
    khong kiem chung gi ca."""
    result = verify.run_check(ctx_for(_write_then("git status"), tmp_path), check("evidence_backed"))
    assert result.status == model_mod.WEAK_EVIDENCE
    assert not result.passed
    assert "khong khai `commands`" in result.why


def test_lenh_duoc_goi_ten_va_thanh_cong_la_bang_chung_that(tmp_path):
    result = verify.run_check(
        ctx_for(_write_then("make test"), tmp_path), check("evidence_backed", commands=["make test"])
    )
    assert result.status == model_mod.PASS


def test_lenh_duoc_goi_ten_nhung_khong_chay_la_that_bai(tmp_path):
    result = verify.run_check(
        ctx_for(_write_then("git status"), tmp_path), check("evidence_backed", commands=["make test"])
    )
    assert result.status == model_mod.FAIL
    assert "make test" in result.why


def test_khong_ghi_gi_thi_yeu_cau_bang_chung_la_khong_ap_dung(tmp_path):
    steps = steps_from(
        row(tool="Bash", command="ls", tool_use_id="a"),
        row(event="tool_result", tool="Bash", tool_use_id="a", ok=True),
    )
    result = verify.run_check(ctx_for(steps, tmp_path), check("evidence_backed"))
    assert result.status == model_mod.NOT_APPLICABLE
    assert result.passed, "khong co tuyen bo nao can chong lung thi khong co gi sai"


def test_must_not_khong_dao_nguoc_mot_check_chua_phan_quyet_duoc(tmp_path):
    """Dao nguoc "khong cham duoc" van la "khong cham duoc". Bien no thanh pass la bien mot cho
    trong thanh mot khang dinh."""
    spec = case_mod.CheckSpec(id="x", kind="evidence_backed", params={}, negate=True)
    steps = steps_from(row(tool="Edit", paths=["a.py"]))
    result = verify.run_check(ctx_for(steps, tmp_path), spec)
    assert result.status == model_mod.UNDECIDED
    assert not result.passed


# ── A5/A8: quy trach nhiem phai duoc neo, va phai noi ro do tin cay ────────────


def test_mot_lenh_thieu_khong_lien_quan_khong_cuop_duoc_chan_doan():
    """Da do duoc: buoc sai dau tien o buoc 0 vi loi thu tu cua skill, mot lenh phu thieu binary o
    buoc 2, va ca chan doan bi chuyen sang `repository`."""
    steps = steps_from(
        row(tool="Edit", paths=["a.py"], tool_use_id="w"),
        row(event="tool_result", tool="Edit", tool_use_id="w", ok=True),
        row(tool="Bash", command="lenh-phu", tool_use_id="z"),
        row(event="tool_result", tool="Bash", tool_use_id="z", ok=False, detail="zzz: command not found"),
    )
    checks = [
        CheckResult.of(
            model_mod.FAIL,
            id="x",
            kind="no_broad_discovery",
            why="",
            at_step=0,
            category="tool.broad_sweep",
        )
    ]
    diag = diagnose_mod.diagnose(record_of(), checks, steps)
    assert diag.category == "tool.broad_sweep"
    assert diag.reattributed_from == ""
    assert diag.confidence == diagnose_mod.HIGH


def test_lenh_thieu_khong_neo_van_doi_chu_so_huu_nhung_ha_do_tin_cay():
    """Khi check da vo la loai phu thuoc vao viec lenh chay duoc, mot lenh thieu o cho khac van la
    manh moi dang ke -- nhung bao cao phai noi ro no khong neo."""
    steps = steps_from(
        row(tool="Edit", paths=["a.py"], tool_use_id="w"),
        row(event="tool_result", tool="Edit", tool_use_id="w", ok=True),
        row(tool="Bash", command="make test", tool_use_id="z"),
        row(event="tool_result", tool="Bash", tool_use_id="z", ok=False, detail="make: command not found"),
    )
    checks = [
        CheckResult.of(
            model_mod.FAIL, id="e", kind="evidence_backed", why="", at_step=0, category="verification"
        )
    ]
    diag = diagnose_mod.diagnose(record_of(), checks, steps)
    assert diag.category == "repository.command_missing"
    assert diag.owner == "repository"
    assert diag.confidence == diagnose_mod.MEDIUM
    assert any("khong phai buoc sai dau tien" in e for e in diag.evidence)


def test_khong_neo_duoc_vao_buoc_nao_thi_owner_la_unknown():
    """Mot chan doan khong chi tay duoc vao dau la mot gia thuyet, va no phai tu noi nhu vay."""
    checks = [CheckResult.of(model_mod.FAIL, id="x", kind="command_ran", why="", category="skill")]
    diag = diagnose_mod.diagnose(record_of(), checks, steps_from(row()))
    assert diag.owner == diagnose_mod.UNKNOWN_OWNER
    assert diag.confidence == diagnose_mod.LOW
    assert "Chua du bang chung" in diag.hypothesis


def test_phan_quyet_cua_judge_khong_bao_gio_duoc_do_tin_cay_cao():
    """Judge co the dung, nhung no khong phai mot phep do."""
    checks = [
        CheckResult.of(
            model_mod.FAIL, id="Q1", kind="judge", why="", at_step=2, category="skill", deterministic=False
        )
    ]
    diag = diagnose_mod.diagnose(record_of(), checks, steps_from(row(), row(), row()))
    assert diag.confidence == diagnose_mod.LOW


def test_bang_chung_yeu_duoc_bao_cao_rieng_chu_khong_bi_nuot():
    checks = [CheckResult.of(model_mod.WEAK_EVIDENCE, id="e", kind="evidence_backed", why="")]
    diag = diagnose_mod.diagnose(record_of(), checks, steps_from(row()))
    assert diag.verdict == "PASS"
    assert diag.weak_evidence == ["e"]
    assert diag.confidence == diagnose_mod.MEDIUM, "co bang chung yeu thi khong the la do tin cay cao"


# ── A6/A7: identity cua thi nghiem ─────────────────────────────────────────────


def test_effort_nam_trong_identity_cua_lan_chay():
    record = record_of(model="opus", effort="high")
    assert record.identity()["effort"] == "high"
    assert record.model_config == "opus/high"


def test_lan_chay_dry_khong_ghi_ten_model_nao(tmp_path, capsys):
    """Da do duoc: `--dry` ghi `model=sonnet` vao ban ghi du khong goi model nao -- mot su kien
    chua xay ra, va no se lam ban bang model matrix."""
    from skill_lab.cli import main as cli_main

    cli_main(["--workspace", str(DEMO_WORKSPACE), "run", "tidy-pass", "--dry"])
    capsys.readouterr()
    config = config_mod.load(DEMO_WORKSPACE)
    latest = store.list_runs(config.runs_dir, case_id="tidy-pass")[-1]
    assert latest.dry is True
    assert latest.model == ""
    assert latest.effort == ""


def _side(label, rates, *, identity=None, boundary=()):
    side = compare_mod.Side(label=label)
    for case_id, (passed, runs) in rates.items():
        side.stats[case_id] = compare_mod.CaseStat(
            case_id=case_id, runs=runs, passed=passed, boundary=case_id in boundary
        )
    side.identity = {k: {v} for k, v in (identity or {}).items()}
    return side


def test_doi_ca_skill_lan_model_thi_khong_ket_luan_duoc():
    """Da do duoc: `compare` gom lan chay theo nhan skill va khong he nhin `model`, nen mot
    baseline Sonnet so voi mot candidate Opus van duoc doc nhu mot cai thien cua skill."""
    rates = {f"c{i}": (0, 4) for i in range(20)}
    better = {f"c{i}": (4, 4) for i in range(20)}
    base = _side("v1", rates, identity={"skill_version": "aaa", "model": "sonnet"})
    cand = _side("v2", better, identity={"skill_version": "bbb", "model": "opus"})
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.INSUFFICIENT_EVIDENCE
    assert result.subject == "confounded"
    assert set(result.confounders) == {"skill_version", "model"}


def test_chi_doi_model_thi_phep_so_duoc_goi_la_do_cau_hinh_chay():
    rates = {f"c{i}": (0, 4) for i in range(20)}
    better = {f"c{i}": (4, 4) for i in range(20)}
    base = _side("v1", rates, identity={"skill_version": "aaa", "model": "sonnet"})
    cand = _side("v2", better, identity={"skill_version": "aaa", "model": "opus"})
    result = compare_mod.compare(base, cand)
    assert result.subject == "runtime"
    assert result.verdict == compare_mod.IMPROVED
    assert any("khong noi ve chat luong skill" in r for r in result.reasons)


def test_qua_it_lan_chay_la_chua_du_bang_chung_chu_khong_phai_khong_khac_biet():
    """Hai cau nay khac nhau, va gop chung lai la cach mot bo so sanh noi "khong khac biet" trong
    khi su that la "chua do du de biet"."""
    base = _side("v1", {"a": (0, 1)}, identity={"skill_version": "aaa"})
    cand = _side("v2", {"a": (1, 1)}, identity={"skill_version": "bbb"})
    result = compare_mod.compare(base, cand, min_runs=3)
    assert result.verdict == compare_mod.INSUFFICIENT_EVIDENCE
    assert any("it nhat 3 lan chay" in r for r in result.reasons)


def test_mot_ben_tron_nhieu_cau_hinh_thi_duoc_noi_ro():
    base = compare_mod.Side(label="v1")
    base.stats["a"] = compare_mod.CaseStat(case_id="a", runs=4, passed=2)
    base.identity = {"skill_version": {"aaa"}, "model": {"sonnet", "opus"}}
    cand = _side("v2", {"a": (3, 4)}, identity={"skill_version": "aaa", "model": "sonnet"})
    result = compare_mod.compare(base, cand)
    assert any("tron nhieu cau hinh" in r for r in result.reasons)


def test_ty_le_giam_vuot_nhieu_la_regressed():
    base = _side("v1", {f"c{i}": (4, 4) for i in range(20)}, identity={"skill_version": "aaa"})
    cand = _side("v2", {f"c{i}": (1, 4) for i in range(20)}, identity={"skill_version": "bbb"})
    result = compare_mod.compare(base, cand)
    assert result.verdict == compare_mod.REGRESSED


# ── A9/experiment: thiet ke phai khop voi thuc te ──────────────────────────────


def test_thi_nghiem_khong_co_gia_thuyet_bi_tu_choi(tmp_path):
    """Khi gia thuyet duoc viet sau, moi ket qua deu xac nhan mot gia thuyet nao do."""
    path = tmp_path / "e.yaml"
    path.write_text("id: e\ndataset: demo\nbaseline: v1\ncandidate: v2\n", encoding="utf-8")
    with pytest.raises(experiment_mod.ExperimentError) as exc:
        experiment_mod.load(path)
    assert "hypothesis" in str(exc.value)


def test_thi_nghiem_bao_khi_bien_doi_khong_khop_thiet_ke(tmp_path):
    path = tmp_path / "e.yaml"
    path.write_text(
        "id: e\nhypothesis: co gi do\ndataset: demo\nbaseline: v1\ncandidate: v2\n"
        "changed: [skill_version]\nfixed: [model]\n",
        encoding="utf-8",
    )
    exp = experiment_mod.load(path)
    problems = exp.mismatch({"skill_version": ("a", "b"), "model": ("sonnet", "opus")})
    assert any("`model` duoc khai la `fixed` nhung da doi" in p for p in problems)
    assert exp.mismatch({"skill_version": ("a", "b")}) == []


# ── duong ong: cham lai khong duoc doi y ───────────────────────────────────────


def test_cham_lai_lan_chay_khong_giu_fixture_khong_bien_thanh_mau_do(tmp_path):
    """Ghep lai A2 o muc duong ong, qua dung ham ma `--rescore` goi."""
    config = config_mod.load(DEMO_WORKSPACE)
    record = RunRecord(
        run_id=store.new_run_id("probe"), case_id="probe", skill="tidy-a-module",
        skill_version="v", model="m",
    )
    directory = store.create(tmp_path, record)
    (directory / "trace.jsonl").write_text("", encoding="utf-8")
    (directory / "trajectory.jsonl").write_text("", encoding="utf-8")
    case_path = tmp_path / "probe.yaml"
    case_path.write_text(
        "id: probe\nskill: tidy-a-module\ntask: x\n"
        "expect:\n  must:\n    - check: file_exists\n      path: README.md\n",
        encoding="utf-8",
    )
    checks, _ = runner.rescore(config, directory, case_mod.load(case_path))
    assert checks[0].status == model_mod.NOT_EVALUATED


# ── A10: lan chay chua xong khong duoc dem nhu mot lan that bai ────────────────


def test_lan_chay_dang_chay_khong_bi_dem_vao_bang_gop(tmp_path):
    """Da do duoc: `matrix` in `claude-opus-5/high  1 lan chay  0.0% ty le xanh` cho mot lan chay
    van dang chay. Con so 0% do khong sai ve co hoc va hoan toan sai ve y nghia."""
    for status in ("running", "error", "complete"):
        store.create(
            tmp_path,
            RunRecord(
                run_id=store.new_run_id(status),
                case_id="c",
                skill="s",
                skill_version="v",
                model="m",
                status=status,
            ),
        )
    assert len(store.list_runs(tmp_path)) == 3
    complete = store.list_runs(tmp_path, only_complete=True)
    assert [r.status for r in complete] == ["complete"]


def test_ban_ghi_cu_khong_co_truong_status_duoc_doc_la_da_xong(tmp_path):
    """Mac dinh phai la `complete`, neu khong moi lan chay viet truoc khi co truong nay se bi doc
    thanh "dang chay" vinh vien va bien mat khoi moi bang gop."""
    directory = store.run_dir(tmp_path, "cu")
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps({"run_id": "cu", "case_id": "c", "skill": "s", "skill_version": "v", "model": "m"}),
        encoding="utf-8",
    )
    assert store.load_record(directory).status == "complete"


def test_case_digest_duoc_so_theo_tung_case_chu_khong_theo_ben():
    """Da do duoc: mot dataset hai case sinh canh bao "ben nay tron nhieu cau hinh o case_digest"
    tren MOI lan so -- dung ve co hoc, vo nghia ve noi dung, va loai canh bao do day nguoi ta toi
    cho thoi doc canh bao."""
    base = compare_mod.Side(label="v1")
    cand = compare_mod.Side(label="v2")
    for side in (base, cand):
        side.stats["a"] = compare_mod.CaseStat(case_id="a", runs=3, passed=3, digest="aaa")
        side.stats["b"] = compare_mod.CaseStat(case_id="b", runs=3, passed=3, digest="bbb")
        side.identity = {"skill_version": {"v"}, "case_digest": {"aaa", "bbb"}}
    result = compare_mod.compare(base, cand)
    assert result.baseline.mixed_identity == []
    assert not any("tron nhieu cau hinh" in r for r in result.reasons)


def test_mot_case_doi_noi_dung_giua_hai_ben_thi_duoc_noi_ro():
    """Truong hop ma `case_digest` THUC SU dang de: hai ben chay hai phien ban khac nhau cua cung
    mot case, nen chung khong con tra loi cung mot cau hoi."""
    base = compare_mod.Side(label="v1")
    cand = compare_mod.Side(label="v2")
    base.stats["a"] = compare_mod.CaseStat(case_id="a", runs=3, passed=3, digest="aaa")
    cand.stats["a"] = compare_mod.CaseStat(case_id="a", runs=3, passed=1, digest="ZZZ")
    base.identity = cand.identity = {"skill_version": {"v"}}
    result = compare_mod.compare(base, cand)
    assert any("doi noi dung giua hai ben" in r for r in result.reasons)


# ── A11: "bi cat" khong duoc dan nhan "cham tran turn" ────────────────────────


def test_lan_chay_bi_giet_khong_bi_dan_nhan_cham_tran_turn():
    """Da do duoc trong mot lan chay THAT: actor bi giet o phut 40 sau 0 turn, va bao cao dan nhan
    `termination.turn_limit` kem huong sua "nang tran turn" -- dung huong, sai ly do, va mot huong
    sua khong chua duoc gi."""
    checks = [CheckResult.of(model_mod.FAIL, id="c", kind="completed", why="", category="termination")]
    diag = diagnose_mod.diagnose(
        record_of(completed=False, exit_code=-1, num_turns=0, max_turns=40), checks, []
    )
    assert diag.category == "termination.aborted"
    assert "Chay lai" in diag.suggested_change
    assert "0/40 turn" in " ".join(diag.evidence)


def test_cham_tran_turn_that_thi_van_duoc_dan_dung_nhan():
    checks = [CheckResult.of(model_mod.FAIL, id="c", kind="completed", why="", category="termination")]
    diag = diagnose_mod.diagnose(
        record_of(completed=False, exit_code=1, num_turns=40, max_turns=40), checks, []
    )
    assert diag.category == "termination.turn_limit"
    assert "Nang tran turn" in diag.suggested_change
