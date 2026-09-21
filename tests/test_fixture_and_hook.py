"""Fixture va hook -- duong ma neu hong am tham thi moi phep do deu vo nghia.

Mot fixture lam cac gate cua chinh workspace ngung hoat dong van chay binh thuong, van cho ra mot
bang toan mau xanh, va do mot thu khac han voi thu no tuyen bo dang do. Khong co bang chung nao
trong bao cao chi ra dieu do, nen no phai duoc kiem o day.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from skill_lab import config as config_mod
from skill_lab import fixture as fixture_mod

REPO_ROOT = Path(__file__).resolve().parent.parent
#: Workspace gia ma cong cu do. KHONG phai repo nay: repo nay la cong cu, thu muc kia la du lieu
#: thu. Tron hai thu lam mot la cach khong ai con doc ra duoc cai nao dang do cai nao.
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


def _run_hook(hook: Path, payload: dict, trace_path: Path | None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("SKILL_LAB_TRACE", None)
    if trace_path is not None:
        env["SKILL_LAB_TRACE"] = str(trace_path)
    return subprocess.run(
        ["python", str(hook)],
        input=json.dumps(payload),
        text=True,
        env=env,
        capture_output=True,
        check=False,
    )


def test_hook_duoc_them_vao_chu_khong_ghi_de_settings_cua_workspace(built):
    """Ghi de khoa `hooks` se tat moi gate cua workspace, va bo do se im lang do mot moi truong
    khong con giong moi truong that o dung diem quan trong nhat."""
    _, fx = built
    settings = json.loads((fx.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert sorted(settings["hooks"]) == ["PostToolUse", "PreToolUse"]
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "$CLAUDE_PROJECT_DIR" in command, (
        "duong dan tuyet doi cua may nguoi viet se tro nguoc ve repo that va ghi trace ra ngoai fixture"
    )


def test_hook_chay_duoc_mot_minh_trong_fixture(built):
    """Hook duoc chep nguyen vao fixture nen no khong duoc `import skill_lab`: mot hook goi bang
    `python` tran hiem khi thay duoc moi truong da cai package."""
    _, fx = built
    hook = fx.root / fixture_mod.HOOK_REL
    assert hook.is_file()

    # Doc cac lenh import that bang `ast`, khong tim chuoi con: docstring cua chinh hook giai thich
    # vi sao no khong duoc `import skill_lab`, nen mot phep tim chuoi se bat dung cau giai thich do.
    tree = ast.parse(hook.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "skill_lab" not in imported
    assert imported <= {"__future__", "hashlib", "json", "os", "sys", "datetime", "pathlib"}, imported


def test_khong_co_bien_moi_truong_thi_hook_khong_lam_gi(built):
    """Moi phien binh thuong deu khong dat `SKILL_LAB_TRACE`, nen hook khong duoc ton gi cua no."""
    _, fx = built
    result = _run_hook(
        fx.root / fixture_mod.HOOK_REL,
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "x"}},
        None,
    )
    assert result.returncode == 0
    assert not fx.trace_path.exists()


def test_hook_ghi_mot_dong_moi_su_kien_va_tach_command_khoi_paths(built):
    _, fx = built
    hook = fx.root / fixture_mod.HOOK_REL
    _run_hook(
        hook,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_use_id": "x1",
            "session_id": "s",
            "tool_input": {"command": "make test"},
        },
        fx.trace_path,
    )
    _run_hook(
        hook,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": "x1",
            "session_id": "s",
            "tool_input": {"command": "make test"},
            "tool_response": {"exit_code": 1},
        },
        fx.trace_path,
    )
    rows = [json.loads(x) for x in fx.trace_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [r["event"] for r in rows] == ["tool_call", "tool_result"]
    assert rows[0]["command"] == "make test"
    assert rows[0]["paths"] == [], "`command` khong duoc lan vao `paths`"
    assert rows[1]["ok"] is False and rows[1]["detail"] == "exit 1"


def test_hook_khong_bao_gio_lam_hong_lan_chay_no_dang_quan_sat(built):
    """Mot hook lam ket lan chay bien chinh phep do thanh bien gay nhieu, te hon la khong do."""
    _, fx = built
    result = _run_hook(fx.root / fixture_mod.HOOK_REL, {}, fx.trace_path)
    assert result.returncode == 0

    proc = subprocess.run(
        ["python", str(fx.root / fixture_mod.HOOK_REL)],
        input="{khong phai json}",
        text=True,
        env={**os.environ, "SKILL_LAB_TRACE": str(fx.trace_path)},
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0


def test_fixture_chep_du_workspace_va_loai_tru_dung_thu(built):
    _, fx = built
    assert (fx.root / ".claude" / "skills" / "tidy-a-module" / "SKILL.md").is_file()
    assert (fx.root / "cases" / "demo" / "tidy-pass.yaml").is_file()
    assert not (fx.root / ".git").exists(), "`.git` nam trong danh sach loai tru mac dinh"


def test_repo_chua_co_commit_thi_auto_chon_copy_chu_khong_chon_worktree(tmp_path):
    """Mot repo vua `git init` co `.git`, nen kiem tra "day co phai git khong" se noi co, roi
    `git worktree add HEAD` do vi chua co HEAD nao."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "skill-lab.yaml").write_text("workspace:\n  id: x\n", encoding="utf-8")
    cfg = config_mod.load(tmp_path)
    assert fixture_mod._resolve_strategy(cfg) == "copy"
