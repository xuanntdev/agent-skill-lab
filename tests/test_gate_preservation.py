"""Gate preservation: chung minh rang gate cua workspace CON HIEU LUC ben trong fixture.

Day la lo hong duy nhat ma dot audit truoc de lai o trang thai UNKNOWN, va ly do no nguy hiem hon
moi lo hong khac trong kit nay: **no hong theo huong im lang va cho ra toan mau xanh.** Mot fixture
lam gate ngung cuong che van chay binh thuong, van sinh trajectory, van cham diem -- chi la no do
"agent lam gi khi khong ai gac" thay vi "skill dan agent the nao duoi ap luc that". Hai thu do
khac nhau, va khong co dong nao trong bao cao phan biet chung.

Cac test o day dung mot workspace tho that: mot script gate that, mot exit code that, mot fixture
that duoc dung ra va xoa di. Khong mock `subprocess`, vi thu dang duoc kiem chinh xac la "lenh nay
chay trong moi truong nao va tra ve gi".
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from skill_lab import agent as agent_mod
from skill_lab import case as case_mod
from skill_lab import config as config_mod
from skill_lab import fixture as fixture_mod
from skill_lab import runner, store

GATE_SCRIPT = "gate.py"


def _workspace(
    tmp_path: Path,
    *,
    gate_exit: int,
    expected_exit: int,
    setup: list | None = None,
    gate_body: str = "",
    extra_gates: list | None = None,
) -> Path:
    """Mot workspace toi thieu nhung THAT: co skill, co gate chay duoc, co case.

    `gate.py` la "gate cua workspace". No khong biet gi ve skill-lab, va skill-lab khong biet gi ve
    no ngoai dong lenh trong `assert_gates` -- dung quan he ma mot workspace that co.
    """
    root = tmp_path / "ws"
    (root / ".claude" / "skills" / "demo").mkdir(parents=True)
    (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: skill toi thieu cho test gate\n---\n\n# Demo\n",
        encoding="utf-8",
    )

    body = gate_body or f"raise SystemExit({gate_exit})"
    (root / GATE_SCRIPT).write_text(
        textwrap.dedent(f"""\
            import os, sys
            print(os.getcwd())
            {body}
            """),
        encoding="utf-8",
    )

    gates = [{"command": [sys.executable, GATE_SCRIPT], "expected_exit": expected_exit, "name": "gate-cua-workspace"}]
    gates += extra_gates or []
    config = {
        "workspace": {"id": "ws-test", "skills": ".claude/skills"},
        "fixture": {"strategy": "copy", "assert_gates": gates},
        "cases": "cases",
        "runs": ".skill-lab/runs",
    }
    if setup is not None:
        config["fixture"]["setup"] = setup

    import yaml

    (root / "skill-lab.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    cases = root / "cases"
    cases.mkdir()
    (cases / "c1.yaml").write_text(
        "id: c1\nskill: demo\ntask: lam gi do\nexpect:\n  must:\n    - completed\n",
        encoding="utf-8",
    )
    (cases / "c1.trace.jsonl").write_text(
        json.dumps(
            {
                "at": "2026-09-21T10:00:00.000+00:00",
                "event": "tool_call",
                "session_id": "t",
                "agent_id": None,
                "agent_type": None,
                "tool": "Bash",
                "tool_use_id": "a",
                "args_digest": "",
                "paths": [],
                "command": "echo hi",
                "ok": None,
                "blocked": False,
                "detail": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _run(root: Path, monkeypatch, *, dry: bool = False):
    config = config_mod.load(root)
    case = case_mod.find("c1", root=config.cases_dir)

    started = []

    def _never(*args, **kwargs):
        started.append(True)
        raise AssertionError("actor da duoc khoi dong -- le ra khong duoc")

    monkeypatch.setattr(agent_mod, "run", _never)
    monkeypatch.setattr(runner.agent_mod, "run", _never)
    return config, case, started


# ── Yeu cau 5: fail-open PHAI bi bat ───────────────────────────────────────────


def test_gate_khong_con_cuong_che_thi_fixture_bi_tu_choi_va_actor_khong_chay(tmp_path, monkeypatch):
    """Test quan trong nhat trong ca kit.

    Workspace khai: gate nay phai tra exit 1. Ben trong fixture no tra 0 -- gate da fail-open. Neu
    khong co co che nay, actor se chay trong mot moi truong khong ai gac va moi con so sau do se
    duoc doc nhu mot phat bieu ve skill.
    """
    root = _workspace(tmp_path, gate_exit=0, expected_exit=1)
    config, case, started = _run(root, monkeypatch)

    with pytest.raises(fixture_mod.FixtureInvalid) as exc:
        runner.execute(config, case, dry=False)

    assert not started, "actor KHONG duoc khoi dong khi fixture khong hop le"
    failed = [r for r in exc.value.results if not r.ok]
    assert len(failed) == 1
    assert failed[0].spec.expected_exit == 1
    assert failed[0].actual_exit == 0


def test_fixture_bi_tu_choi_duoc_ghi_lai_la_fixture_invalid_chu_khong_phai_skill_that_bai(
    tmp_path, monkeypatch
):
    """Ba ket qua khac nhau, ba nhan khac nhau. Gop `FIXTURE_INVALID` vao `FAIL` la do oan skill;
    gop no vao `error` la doi loi cho cong cu."""
    root = _workspace(tmp_path, gate_exit=0, expected_exit=1)
    config, case, _ = _run(root, monkeypatch)

    with pytest.raises(fixture_mod.FixtureInvalid):
        runner.execute(config, case, dry=False)

    record = store.list_runs(config.runs_dir)[-1]
    assert record.status == "fixture_invalid"
    assert record.status != "error"

    directory = store.run_dir(config.runs_dir, record.run_id)
    diagnosis = store.load_diagnosis(directory)
    assert diagnosis["verdict"] == "FIXTURE_INVALID"
    assert diagnosis["owner"] == "harness"
    assert diagnosis["category"] == "harness.gate_not_enforced"
    assert store.load_evaluation(directory)["checks"] == [], "khong duoc cham skill khi chua do duoc"

    gates = store.load_gates(directory)
    assert gates["gates"][0]["expected_exit"] == 1
    assert gates["gates"][0]["actual_exit"] == 0


def test_bang_gop_bo_qua_lan_chay_fixture_invalid(tmp_path, monkeypatch):
    """Mot lan chay khong do duoc gi khong duoc gop vao ty le xanh cua bat ky ai."""
    root = _workspace(tmp_path, gate_exit=0, expected_exit=1)
    config, case, _ = _run(root, monkeypatch)
    with pytest.raises(fixture_mod.FixtureInvalid):
        runner.execute(config, case, dry=False)
    assert store.list_runs(config.runs_dir, only_complete=True) == []


# ── Yeu cau 6: fail-closed thi cho chay ────────────────────────────────────────


def test_gate_dung_exit_code_thi_fixture_hop_le_va_actor_duoc_chay(tmp_path, monkeypatch):
    root = _workspace(tmp_path, gate_exit=1, expected_exit=1)
    config = config_mod.load(root)
    case = case_mod.find("c1", root=config.cases_dir)

    record, directory = runner.execute(config, case, dry=True)

    assert record.status == "complete"
    assert store.load_diagnosis(directory)["verdict"] == "PASS"
    assert record.num_tool_calls == 1, "trace dong hop da duoc phat lai -- tuc la actor da chay"


def test_khong_khai_gate_nao_thi_khong_co_gi_thay_doi(tmp_path):
    """`assert_gates` la thu ban them vao khi can, khong phai thu ban phai viet de chay lenh dau."""
    root = _workspace(tmp_path, gate_exit=1, expected_exit=1)
    text = (root / "skill-lab.yaml").read_text(encoding="utf-8").replace("assert_gates", "_tat")
    (root / "skill-lab.yaml").write_text(text, encoding="utf-8")

    config = config_mod.load(root)
    assert config.fixture.assert_gates == ()
    record, _ = runner.execute(config, case_mod.find("c1", root=config.cases_dir), dry=True)
    assert record.status == "complete"


# ── Yeu cau 2: gate chay TRONG fixture, khong tren host ───────────────────────


def test_gate_chay_trong_fixture_chu_khong_chay_tren_workspace_goc(tmp_path):
    """Mot gate chay tren host tra loi mot cau hoi ve host. Cau hoi dang duoc dat la ve chinh moi
    truong ma actor sap chay trong do."""
    root = _workspace(tmp_path, gate_exit=1, expected_exit=1)
    dest = tmp_path / "fx"

    with pytest.raises(fixture_mod.FixtureInvalid) as exc:
        # Ep gate hong de lay duoc `results` ra doc; `gate.py` in cwd ra stdout.
        broken = config_mod.load(root)
        object.__setattr__(
            broken.fixture,
            "assert_gates",
            (config_mod.GateSpec(command=(sys.executable, GATE_SCRIPT), expected_exit=99),),
        )
        fixture_mod.build(broken, dest)

    printed = exc.value.results[0].stdout.strip()
    assert Path(printed).resolve() == dest.resolve(), f"gate chay o {printed}, khong phai trong fixture"
    assert Path(printed).resolve() != root.resolve()


# ── Yeu cau 1: setup chay TRUOC, gate chay SAU ────────────────────────────────


def test_setup_chay_truoc_gate(tmp_path):
    """Gate nay chi tra dung exit code khi mot file do `setup` tao ra da ton tai. Neu thu tu bi
    dao, gate se hong -- va do la cach duy nhat kiem duoc thu tu ma khong phai doc code."""
    root = _workspace(
        tmp_path,
        gate_exit=0,
        expected_exit=7,
        gate_body="raise SystemExit(7 if os.path.exists('san-sang.txt') else 0)",
        setup=[[sys.executable, "-c", "open('san-sang.txt','w').write('x')"]],
    )
    config = config_mod.load(root)
    fx = fixture_mod.build(config, tmp_path / "fx")
    assert (fx.root / "san-sang.txt").is_file()


# ── Yeu cau 3: phai khai ro exit code, khong duoc dung co nhi phan ────────────


def test_thieu_expected_exit_bi_tu_choi(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "skill-lab.yaml").write_text(
        "fixture:\n  assert_gates:\n    - command: [python, gate.py]\n", encoding="utf-8"
    )
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load(root)
    assert "expected_exit" in str(exc.value)


def test_co_must_fail_bi_tu_choi_kem_ly_do(tmp_path):
    """`exit 1`, `exit 2` va `exit 126` mang ba nghia khac nhau. Mot co nhi phan gop ca ba lai, nen
    mot gate DA HONG se qua duoc dung nhu mot gate DANG CHAY."""
    root = tmp_path / "ws"
    root.mkdir()
    (root / "skill-lab.yaml").write_text(
        "fixture:\n  assert_gates:\n    - command: [python, gate.py]\n      must_fail: true\n",
        encoding="utf-8",
    )
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load(root)
    assert "must_fail" in str(exc.value)
    assert "expected_exit" in str(exc.value)


def test_exit_code_khac_nhau_khong_duoc_coi_la_nhu_nhau(tmp_path):
    """Gate tra 2 trong khi workspace khai 1: van la FIXTURE_INVALID. "Khac 0" khong phai mot cau
    tra loi du."""
    root = _workspace(tmp_path, gate_exit=2, expected_exit=1)
    config = config_mod.load(root)
    with pytest.raises(fixture_mod.FixtureInvalid) as exc:
        fixture_mod.build(config, tmp_path / "fx")
    assert exc.value.results[0].actual_exit == 2


def test_gate_khong_chay_duoc_la_mot_ket_qua_chu_khong_phai_mot_ngoai_le(tmp_path):
    """Mot gate khong chay duoc la mot gate khong gac -- dung dang fail-open can bat nhat."""
    root = _workspace(tmp_path, gate_exit=1, expected_exit=1)
    config = config_mod.load(root)
    object.__setattr__(
        config.fixture,
        "assert_gates",
        (config_mod.GateSpec(command=("lenh-khong-ton-tai-o-dau-ca",), expected_exit=1),),
    )
    with pytest.raises(fixture_mod.FixtureInvalid) as exc:
        fixture_mod.build(config, tmp_path / "fx")
    assert "khong chay duoc" in exc.value.results[0].error


# ── Yeu cau 4: assertion chi duoc QUAN SAT ────────────────────────────────────


def test_gate_tu_sua_fixture_bi_bat(tmp_path):
    """Mot assertion tu sua fixture de minh xanh lam moi con so sau do noi ve mot moi truong khac
    voi moi truong da duoc kiem."""
    root = _workspace(
        tmp_path,
        gate_exit=0,
        expected_exit=5,
        gate_body="open('gate-da-ghi.txt','w').write('x'); raise SystemExit(5)",
    )
    config = config_mod.load(root)
    with pytest.raises(fixture_mod.FixtureInvalid) as exc:
        fixture_mod.build(config, tmp_path / "fx")
    assert exc.value.results[0].ok, "gate dung exit code, nhung no da sua fixture"
    assert any("gate-da-ghi.txt" in item for item in exc.value.mutated)


# ── Yeu cau 7: hieu luc den tu WORKSPACE, khong tu hook cua Lab ───────────────


def test_hook_cua_lab_co_mat_nhung_khong_phai_thu_lam_gate_dat(tmp_path):
    """Hook cua Lab duoc cai vao fixture, nen cau hoi "co phai chinh no lam gate xanh khong" la
    mot cau hoi that.

    Cau tra loi duoc chung minh bang cach giu moi thu co dinh va **chi doi hanh vi cua workspace**:
    cung mot fixture, cung mot hook cua Lab, gate tra 1 -> hop le; gate tra 0 -> FIXTURE_INVALID.
    Phan quyet di theo workspace, nen no khong the den tu hook cua Lab.
    """
    strict = _workspace(tmp_path / "a", gate_exit=1, expected_exit=1)
    fx = fixture_mod.build(config_mod.load(strict), tmp_path / "a" / "fx")
    assert (fx.root / fixture_mod.HOOK_REL).is_file(), "hook cua Lab phai co mat trong fixture"

    lax = _workspace(tmp_path / "b", gate_exit=0, expected_exit=1)
    with pytest.raises(fixture_mod.FixtureInvalid):
        fixture_mod.build(config_mod.load(lax), tmp_path / "b" / "fx")


def test_hook_cua_lab_khong_bao_gio_tra_ma_exit_khac_0(tmp_path):
    """Manh con lai cua cung lap luan, doc thang tu hook: no luon `sys.exit(0)`, nen no khong the
    la nguon cua mot ma exit khac 0 ma mot gate nhin thay."""
    import ast

    tree = ast.parse(fixture_mod.HOOK_SOURCE.read_text(encoding="utf-8"))
    exits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
    ]
    assert exits, "khong tim thay lenh thoat nao trong hook"
    for node in exits:
        arg = node.args[0]
        assert isinstance(arg, ast.Constant) and arg.value == 0 or isinstance(arg, ast.Call), ast.dump(arg)


def test_gate_thay_duoc_ca_hook_cua_workspace_lan_hook_cua_lab(tmp_path):
    """Gate chay trong fixture, nen no nhin thay dung cai actor se nhin thay: `settings.json` giu
    nguyen hook cua workspace VA mang them hook cua Lab."""
    root = _workspace(tmp_path, gate_exit=1, expected_exit=1)
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "cua-workspace"}]}]}}),
        encoding="utf-8",
    )
    config = config_mod.load(root)
    fx = fixture_mod.build(config, tmp_path / "fx")
    settings = json.loads((fx.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for g in settings["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert "cua-workspace" in commands
    assert any("skill_lab_trace.py" in c for c in commands)


# ── git-worktree: cai bay ma chien luoc nay mang theo ────────────────────────


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def _git_workspace(tmp_path: Path, *, commit_gate: bool) -> Path:
    root = _workspace(tmp_path, gate_exit=1, expected_exit=1)
    import yaml

    config = yaml.safe_load((root / "skill-lab.yaml").read_text(encoding="utf-8"))
    config["fixture"]["strategy"] = "git-worktree"
    (root / "skill-lab.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    if commit_gate:
        _git(root, "add", "-A")
    else:
        # Moi thu TRU gate script. Day la tinh huong that: mot file chua commit.
        _git(root, "add", "skill-lab.yaml", ".claude", "cases")
    _git(root, "commit", "-qm", "init")
    return root


def test_gate_chay_duoc_trong_worktree_khi_da_commit(tmp_path):
    root = _git_workspace(tmp_path, commit_gate=True)
    config = config_mod.load(root)
    fx = fixture_mod.build(config, tmp_path / "fx")
    try:
        assert fx.strategy == "git-worktree"
        assert (fx.root / GATE_SCRIPT).is_file()
    finally:
        fixture_mod.remove_worktree(config, fx.root)


def test_gate_chua_commit_bi_mat_trong_worktree_va_bi_bat(tmp_path):
    """Cai bay that cua `git-worktree`: no ghim mot commit, nen file chua commit **khong co** trong
    fixture.

    Truoc khi co `assert_gates`, tinh huong nay im lang hoan toan: gate bien mat, khong ai gac, va
    actor van chay den cuoi voi mot bang diem trong nhu that. Gio no dung lai ngay o day.
    """
    root = _git_workspace(tmp_path, commit_gate=False)
    config = config_mod.load(root)
    with pytest.raises(fixture_mod.FixtureInvalid) as exc:
        fixture_mod.build(config, tmp_path / "fx")
    fixture_mod.remove_worktree(config, tmp_path / "fx")

    result = exc.value.results[0]
    assert not result.ok
    assert result.actual_exit != result.spec.expected_exit
