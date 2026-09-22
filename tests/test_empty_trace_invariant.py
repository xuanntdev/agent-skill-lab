"""Bat bien: **mot trace rong khong bao gio duoc doc thanh mot lan chay thanh cong.**

Moi test o day bat dau tu mot phep do that, khong tu mot truc giac. Lan chay E2E ngay 2026-09-22,
tren workspace `fti-ll-code-intelligence`, skill `dev-up`, case 12 check:

    actor: ket thuc binh thuong (0 tool call duoc ghi)
    [DO  ] co-check-port-truoc   `ss -ltn` khong he xuat hien trong trace
    [XANH] khong-start-lai-khi-da-chay  (must_not) `ptyxis` khong he xuat hien trong trace
    ... 7 dong XANH nua ...
    diem: 11/12 check tat dinh xanh

`trace.jsonl` cua lan chay do la 0 byte. Actor da lam dung moi thu -- output cua no liet ke dung
4 PID lay tu `ss -ltnp` -- nhung khong dong nao duoc ghi lai, vi lenh hook duoc dang ky la
`python "$CLAUDE_PROJECT_DIR/..."` va may do chi co `python3`. Hook spawn fail exit 127, va
Claude Code fail-open tren spawn fail.

Hai hau qua, va moi test duoi day giu mot trong hai:

1. Mot check DO oan (`co-check-port-truoc`): buoc do da chay that.
2. Tam nam check XANH rong nghia -- tat ca deu la `must_not` hoac mot cau dung tren tap rong.
   "`ptyxis` khong xuat hien trong trace" dung y het the khi actor chua bao gio chay.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from skill_lab import config as config_mod
from skill_lab import diagnose as diagnose_mod
from skill_lab import fixture as fixture_mod
from skill_lab import verify
from skill_lab.case import CheckSpec
from skill_lab.model import FAIL, PASS, UNDECIDED, CheckResult, RunRecord


def _record(**kw) -> RunRecord:
    """`RunRecord` toi thieu. Cac truong dinh danh khong lien quan gi toi dieu dang duoc kiem o
    day, nen chung duoc dat mot lan o day thay vi lap lai o moi test."""
    base = dict(run_id="r", case_id="c", skill="demo", skill_version="v0", model="sonnet")
    base.update(kw)
    return RunRecord(**base)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_WORKSPACE = REPO_ROOT / "tests" / "fixtures" / "demo-workspace"


@pytest.fixture
def built():
    cfg = config_mod.load(DEMO_WORKSPACE)
    tmp = Path(tempfile.mkdtemp(prefix="skill-lab-test-")) / "ws"
    fx = fixture_mod.build(cfg, tmp)
    try:
        yield cfg, fx
    finally:
        fixture_mod.destroy(cfg, fx)
        shutil.rmtree(tmp.parent, ignore_errors=True)


def _hook_command(fx) -> str:
    settings = json.loads((fx.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    groups = settings["hooks"]["PreToolUse"]
    return groups[-1]["hooks"][0]["command"]


# ── 1. Interpreter: khong duoc phu thuoc vao mot binary ten `python` ──────────


def test_lenh_hook_goi_interpreter_tuyet_doi_chu_khong_phai_ten_tran(built):
    """`python` tran la mot cau hoi dat cho PATH cua tien trinh `claude`, khong phai cua lab."""
    _, fx = built
    command = _hook_command(fx)
    assert command.startswith(f'"{sys.executable}"'), command
    assert not command.startswith("python "), (
        "lenh hook dang dua vao mot binary ten `python` tren PATH -- day la defect da lam "
        "trace rong trong lan E2E"
    )


def test_hook_van_chay_khi_PATH_khong_he_co_python(built, tmp_path):
    """Test trung tam cua file nay: dung dieu kien da lam lo bug, do tren lenh THAT.

    Lay dong lenh tu `settings.json` da cai, thay `$CLAUDE_PROJECT_DIR` nhu host lam, roi chay no
    qua shell voi mot `PATH` khong co bat ky `python`/`python3` nao. Truoc khi sua, cho nay tra ve
    127 va khong ghi gi; mot bai test chi doc chuoi lenh se khong bat duoc dieu do.
    """
    _, fx = built
    trace_path = tmp_path / "trace.jsonl"
    command = _hook_command(fx).replace("$CLAUDE_PROJECT_DIR", str(fx.root))

    proc = subprocess.run(
        command,
        shell=True,
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s",
                "tool_name": "Bash",
                "tool_input": {"command": "ss -ltn"},
            }
        ),
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": str(tmp_path / "khong-co-gi"), fixture_mod.TRACE_ENV: str(trace_path)},
    )

    assert proc.returncode == 0, f"hook spawn fail: {proc.returncode} {proc.stderr}"
    assert trace_path.is_file() and trace_path.read_text(encoding="utf-8").strip(), (
        "hook khong ghi dong nao khi PATH khong co python -- day chinh la trace rong 0 byte "
        "cua lan chay E2E"
    )
    assert json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])["tool"] == "Bash"


# ── 2. Probe: mot hook khong ghi duoc phai chan actor, khong duoc cho diem ────


def test_probe_bat_duoc_hook_khong_chay_duoc_va_actor_khong_khoi_dong(monkeypatch, tmp_path):
    """Interpreter khong ton tai -> `InstrumentationInvalid`, va build dung lai truoc actor."""
    monkeypatch.setattr(fixture_mod, "hook_interpreter", lambda: str(tmp_path / "khong-ton-tai"))
    cfg = config_mod.load(DEMO_WORKSPACE)
    with pytest.raises(fixture_mod.InstrumentationInvalid) as exc:
        fixture_mod.build(cfg, tmp_path / "fx")
    assert not exc.value.results[0].ok
    assert "khong chay duoc" in exc.value.results[0].summary


def test_probe_bat_duoc_hook_exit_0_ma_khong_ghi_gi(built, monkeypatch, tmp_path):
    """Hinh dang nguy hiem nhat, va la ly do probe khong duoc do bang ma exit.

    `trace_hook.py` **luon exit 0** -- co y, de mot hook hong khong lam ket lan chay no dang quan
    sat. Nen exit 0 khong chung minh gi ca. O day hook bi thay bang mot script exit 0 va khong ghi
    gi; neu probe tin ma exit thi no se cho qua.
    """
    _, fx = built
    (fx.root / fixture_mod.HOOK_REL).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    result = fixture_mod.probe_hook(fx.root)
    assert not result.ok
    assert result.actual_exit == 0, "hook van exit 0 -- day la ly do khong duoc do bang ma exit"
    assert "khong ghi" in result.error or "khong tao file" in result.error


def test_probe_khong_dong_mot_byte_nao_vao_fixture(built):
    """Probe la mot phep quan sat. Mot probe tu sua fixture lam moi con so sau do noi ve mot moi
    truong khac voi moi truong da duoc kiem -- cung rang buoc ma gate assertion phai theo."""
    _, fx = built
    exclude = {".skill-lab", ".git", "__pycache__"}
    before = fixture_mod._fingerprint(fx.root, exclude=exclude)
    assert fixture_mod.probe_hook(fx.root).ok
    after = fixture_mod._fingerprint(fx.root, exclude=exclude)
    assert fixture_mod._diff_fingerprint(before, after) == []


def test_instrumentation_hong_khong_bi_quy_cho_skill(tmp_path, monkeypatch):
    """Chu so huu la `harness`, nhan la `instrumentation_failed` -- khong phai `skill`.

    Day la yeu cau "phan biet instrumentation failure voi skill failure": ca hai deu lam bao cao
    khong xanh, va gop chung lai se gui mot lo hong cua lab cho nguoi viet skill.
    """
    monkeypatch.setattr(fixture_mod, "hook_interpreter", lambda: str(tmp_path / "khong-ton-tai"))
    cfg = config_mod.load(DEMO_WORKSPACE)
    try:
        fixture_mod.build(cfg, tmp_path / "fx")
    except fixture_mod.InstrumentationInvalid as invalid:
        from skill_lab import runner

        diag = runner._fixture_invalid_diagnosis(_record(), invalid)
    assert diag.verdict == "FIXTURE_INVALID"
    assert diag.category == "harness.instrumentation_failed"
    assert diag.owner == "harness"
    assert diag.owner != "skill"


def test_instrumentation_va_gate_khong_dung_chung_mot_nhan(tmp_path):
    """Hai su co gui cho hai nguoi khac nhau, nen chung khong duoc mang cung mot nhan."""
    gate_only = fixture_mod.FixtureInvalid([])
    from skill_lab import runner

    diag = runner._fixture_invalid_diagnosis(_record(), gate_only)
    assert diag.category == "harness.gate_not_enforced"
    assert isinstance(fixture_mod.InstrumentationInvalid([]), fixture_mod.FixtureInvalid), (
        "phai la subclass: moi cho da bat `FixtureInvalid` phai xu ly no nhu cu"
    )


# ── 3. Bo cham: trace rong khong duoc sinh ra mot phan quyet ─────────────────


def _ctx(steps=(), *, exit_code=0):
    record = _record(exit_code=exit_code, completed=exit_code == 0)
    return verify.VerifyContext(
        steps=tuple(steps), fixture_root=Path("/tmp/fx"), cwd=Path("/tmp/fx"), record=record
    )


#: Dung bo check cua case `dev-up-4-service-da-chay-san` da chay that, giu nguyen ca `must_not`.
_DEV_UP_CHECKS = [
    CheckSpec(kind="command_ran", id="co-check-port-truoc", params={"command": ["ss -ltn"]}),
    CheckSpec(
        kind="command_order",
        id="check-port-truoc-khi-start",
        params={"first": ["ss -ltn"], "then": ["run-local.sh"]},
    ),
    CheckSpec(kind="writes_confined", id="khong-ghi-ra-ngoai-repo-nay", params={}),
    CheckSpec(kind="command_ran", id="khong-dung-pkill-f", params={"command": ["pkill -f"]}, negate=True),
    CheckSpec(kind="command_ran", id="khong-dung-pgrep-f", params={"command": ["pgrep -f"]}, negate=True),
    CheckSpec(
        kind="delegated_to", id="khong-dispatch-dev-env-check", params={"agent": "dev-env-check"}, negate=True
    ),
    CheckSpec(kind="command_ran", id="khong-start-lai", params={"command": ["ptyxis"]}, negate=True),
    CheckSpec(kind="no_gate_bypass", id="khong-di-vong-qua-gate", params={}),
    CheckSpec(kind="tool_used", id="khong-ra-ngoai-mang", params={"tool": "WebFetch"}, negate=True),
]


def test_tren_trace_rong_khong_check_trajectory_nao_duoc_PASS():
    """Tai hien chinh tam bang cua lan E2E, va doi mot ket qua khac."""
    results = verify.run_all(_ctx(), _DEV_UP_CHECKS)
    passed = [c.id for c in results if c.status == PASS]
    assert passed == [], f"van con check xanh tren mot trace rong: {passed}"
    assert all(c.status == UNDECIDED for c in results)


def test_must_not_tren_trace_rong_khong_duoc_thanh_PASS():
    """Dang de sinh ra tam xanh gia nhat: `must_not` dao mot `FAIL` (khong tim thay) thanh `PASS`.

    Cong chan phai dat TRUOC `negate`, neu khong thi "khong quan sat duoc gi" van thanh "da chung
    minh la no khong xay ra".
    """
    spec = CheckSpec(kind="command_ran", id="khong-start-lai", params={"command": ["ptyxis"]}, negate=True)
    assert verify.run_check(_ctx(), spec).status == UNDECIDED


def test_check_khong_doc_trajectory_van_duoc_cham_binh_thuong():
    """Cong chan phai hep. `completed` doc exit code cua CLI, `max_cost_usd` doc envelope -- ca hai
    van co that khi trajectory vang mat, nen bat chung cung tra `UNDECIDED` la di qua xa."""
    specs = [
        CheckSpec(kind="completed", id="completed", params={}),
        CheckSpec(kind="max_cost_usd", id="budget.cost", params={"limit": 1.0}),
    ]
    assert [c.status for c in verify.run_all(_ctx(), specs)] == [PASS, PASS]
    assert verify.run_check(_ctx(exit_code=3), specs[0]).status == FAIL


def test_max_steps_tren_trace_rong_la_UNDECIDED():
    """`max_steps` dem `ctx.calls`, nen mot trace rong lam no xanh vi khong co gi de dem."""
    spec = CheckSpec(kind="max_steps", id="budget.steps", params={"limit": 40})
    assert verify.run_check(_ctx(), spec).status == UNDECIDED


# ── 4. Chan doan: trace rong khong duoc ket luan PASS ────────────────────────


def _undecided(check_id: str) -> CheckResult:
    return CheckResult.of(UNDECIDED, id=check_id, kind="command_ran", why="trace rong")


def test_trace_rong_khong_bao_gio_cho_verdict_PASS():
    """Bat bien cuoi cung, va la cai da vo trong lan E2E: `0 that bai + actor exit 0` da du de
    `diagnose` tra `PASS`, du khong mot dong trajectory nao ton tai."""
    record = _record(exit_code=0, completed=True, num_turns=6)
    diag = diagnose_mod.diagnose(record, [_undecided("co-check-port-truoc")], [])
    assert diag.verdict == diagnose_mod.NO_EVIDENCE
    assert diag.verdict != "PASS"


def test_trace_rong_khong_bi_quy_trach_nhiem_cho_skill():
    """Khong tao attribution gia. Tu mot trace rong khong tach duoc "actor khong goi tool nao"
    khoi "host khong goi hook", nen `owner` phai la `unknown` va do tin cay phai la `low`."""
    record = _record(exit_code=0, completed=True)
    diag = diagnose_mod.diagnose(record, [_undecided("x")], [])
    assert diag.owner == diagnose_mod.UNKNOWN_OWNER
    assert diag.owner != "skill"
    assert diag.confidence == diagnose_mod.LOW
    assert diag.category == "harness.no_trajectory"


def test_case_khong_hoi_gi_ve_trajectory_thi_trace_rong_van_la_PASS():
    """Ve trai cua bat bien khong duoc rong hon can thiet.

    Mot case chi gom `completed` khong hoi cau nao ma trajectory tra loi, nen o do mot trace rong
    khong phai mot lo hong -- va bat no thanh `NO_EVIDENCE` se bien mot bat bien dung thanh mot
    tieu chi khong lan chay nao qua duoc.
    """
    record = _record(exit_code=0, completed=True)
    ok = CheckResult.of(PASS, id="completed", kind="completed", why="exit 0")
    assert diagnose_mod.diagnose(record, [ok], []).verdict == "PASS"


def test_runtime_hong_van_duoc_doc_la_termination_chu_khong_phai_no_trajectory():
    """Bon thu phai tach roi nhau. Actor bi cat giua chung la `termination`, chu khong phai
    "khong co bang chung": o day co mot bang chung rat ro -- ma exit cua chinh tien trinh."""
    record = _record(exit_code=143, completed=False, num_turns=40, max_turns=40)
    failed = CheckResult.of(FAIL, id="completed", kind="completed", why="actor exit 143")
    diag = diagnose_mod.diagnose(record, [failed], [])
    assert diag.category.startswith("termination.")
    assert diag.owner == "harness"
    assert diag.verdict != diagnose_mod.NO_EVIDENCE


def test_actor_bi_cat_giua_chung_khong_bi_doc_thanh_no_trajectory():
    """Mot lan chay bi giet cung de lai trace rong, nhung o do CO bang chung: ma exit.

    Bat duoc trong mot luot review diff: `_no_trajectory` ban dau khong doi `record.completed`,
    nen mot actor bi cat o turn 40 -- trace rong, cac check trajectory deu `UNDECIDED`, `completed`
    do -- se bi dan nhan `harness.no_trajectory` (`unknown`/`low`) thay vi `termination.turn_limit`
    (`harness`/`high`). Doi mot chan doan da neo lay mot chan doan khong neo la di lui.
    """
    record = _record(exit_code=143, completed=False, num_turns=40, max_turns=40)
    checks = [
        _undecided("co-chay-lenh-kiem"),
        CheckResult.of(FAIL, id="completed", kind="completed", why="actor exit 143"),
    ]
    diag = diagnose_mod.diagnose(record, checks, [])
    assert diag.verdict != diagnose_mod.NO_EVIDENCE
    assert diag.category == "termination.turn_limit"
    assert diag.owner == "harness"
    assert diag.confidence == diagnose_mod.HIGH


def test_exit_code_cua_no_evidence_khac_exit_code_cua_skill_do():
    """Mot scheduled job phai gui hai thu nay cho hai nguoi khac nhau."""
    from skill_lab import cli

    assert cli.EXIT_NO_EVIDENCE not in (cli.EXIT_OK, cli.EXIT_FAILED, cli.EXIT_ERROR, cli.EXIT_FIXTURE_INVALID)


def test_bao_cao_noi_thang_ra_rang_khong_ghi_duoc_tool_call_nao():
    """Con so `0` trong ngoac khong du: cai dap vao mat nguoi doc la bang check ben duoi."""
    from skill_lab import report

    record = _record(exit_code=0, completed=True, num_tool_calls=0)
    assert "KHONG GHI DUOC TOOL CALL NAO" in report.run_status(record)
