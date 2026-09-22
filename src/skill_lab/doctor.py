"""`skill-lab doctor` -- moi tien de mot lan chay can, kiem truoc khi ton tien.

**Chi kiem, khong sua, khong dung fixture cua workspace.** Doctor khong tao `skill-lab.yaml`,
khong cai package, khong chay actor. Cho duy nhat no ghi la mot thu muc tam cua he dieu hanh, de
tra loi cau hoi "hook co chay duoc khong" -- va thu muc do bi xoa truoc khi ham tra ve. Workspace
khong doi mot byte; do la dieu kien de chay doctor giua mot phien dang lam viec ma khong so.

Hai check dang noi, va ca hai deu den tu mot lan chay that chu khong tu mot danh sach mong uoc:

* **`hook`** -- cai hook vao mot ban sao rong roi chay no. Lan E2E ngay 2026-09-22 hong dung o day:
  lenh hook dung binary `python`, may chi co `python3`, hook spawn fail 127, Claude Code fail-open,
  va `trace.jsonl` ra 0 byte ma khong mot dong nao bao. Doctor tra loi cau do trong mot giay, truoc
  khi ai do tra tien cho mot lan chay khong do duoc gi.
* **`fixture.setup` / `assert_gates`** -- chi kiem binary dau tien cua moi lenh co ton tai khong.
  KHONG chay chung: `setup` cai package va `assert_gates` co the doi trang thai, va mot lenh chan
  doan gay side effect la mot lenh khong ai dam chay.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from skill_lab import config as config_mod
from skill_lab import fixture as fixture_mod

OK = "OK"
WARN = "CANH BAO"
BAD = "HONG"


@dataclass(frozen=True)
class Finding:
    """Mot cau hoi, cau tra loi, va -- khi hong -- buoc lam tiep.

    `fix` chi duoc dien khi co mot viec cu the de lam. Mot goi y chung chung ("kiem lai cau hinh")
    ton cho ma khong chuyen duoc ai di dau.
    """

    name: str
    status: str
    detail: str
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.status != BAD


def _version_of(binary: str, *args: str) -> str:
    try:
        proc = subprocess.run(
            [binary, *args], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"!{exc}"
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0] if proc.returncode == 0 else ""


def check_python() -> Finding:
    if sys.version_info < (3, 11):
        return Finding(
            "python",
            BAD,
            f"{sys.version.split()[0]} tai {sys.executable}",
            "agent-skill-lab can Python >= 3.11 (xem `requires-python`)",
        )
    return Finding("python", OK, f"{sys.version.split()[0]} tai {sys.executable}")


def check_skill_lab() -> Finding:
    return Finding("skill-lab", OK, f"nap tu {Path(__file__).resolve().parent}")


def check_git() -> Finding:
    """`git` khong bat buoc cho moi workspace -- chi cho `git-worktree` va cho `workspace_rev`."""
    version = _version_of("git", "--version")
    if not version or version.startswith("!"):
        return Finding(
            "git",
            WARN,
            "khong thay `git`",
            "fixture `git-worktree` se khong dung duoc, va `workspace_rev` se rong -- "
            "`replay` sau nay khong ghim duoc dung commit nao",
        )
    return Finding("git", OK, version)


def check_runtime(cli_name: str) -> Finding:
    """Runtime la Claude Code, va `actor.cli` chi dat ten binary chu khong phai mot adapter.

    Neu ai do doi `cli:` sang thu khac, doctor noi ra o day -- chu khong de lan chay tra ve mot
    diem so. Do da do duoc: dat `cli: codex` roi chay cho ra `diem: 5/7` kem
    `termination.aborted`, huong quy trach nhiem dung nhung ly do sai.
    """
    if cli_name != "claude":
        return Finding(
            "runtime",
            BAD,
            f"`actor.cli` dang la {cli_name!r}",
            "chi Claude Code duoc ho tro: `agent.py` dung co rieng cua no "
            "(`--output-format json`, `--permission-mode`, `--max-turns`). Dat lai `cli: claude`",
        )
    binary = shutil.which(cli_name)
    if not binary:
        return Finding(
            "runtime",
            BAD,
            f"khong thay `{cli_name}` tren PATH",
            f"cai Claude Code roi chay `{cli_name}` mot lan de dang nhap",
        )
    version = _version_of(binary, "--version")
    return Finding("runtime", OK, f"{version or cli_name} tai {binary}")


def check_workspace(config: config_mod.Config) -> Finding:
    where = f"{config.root}" + (f" (tu {config.path.name})" if config.path else " (mac dinh, khong co skill-lab.yaml)")
    if not config.skills_dir.is_dir():
        return Finding(
            "workspace",
            BAD,
            f"{where} -- khong co thu muc skill tai {config.skills_dir}",
            "tro `workspace.skills` toi dung cho, hoac chay `skill-lab init` o goc workspace",
        )
    return Finding("workspace", OK, where)


def check_skills(config: config_mod.Config) -> Finding:
    skills = config.skills()
    if not skills:
        return Finding(
            "skill",
            BAD,
            f"khong thay SKILL.md nao duoi {config.skills_dir}",
            "mot skill la mot thu muc co `SKILL.md` ben trong `workspace.skills`",
        )
    head = ", ".join(skills[:6]) + (f", ... (+{len(skills) - 6})" if len(skills) > 6 else "")
    return Finding("skill", OK, f"{len(skills)} skill: {head}")


def check_cases(config: config_mod.Config) -> Finding:
    if not config.cases_dir.is_dir():
        return Finding(
            "case",
            WARN,
            f"chua co thu muc case tai {config.cases_dir}",
            "`skill-lab evaluate <skill> --task \"...\"` sinh mot case toi thieu de bat dau",
        )
    found = list(config.cases_dir.rglob("*.yaml"))
    if not found:
        return Finding("case", WARN, f"{config.cases_dir} rong", "xem `skill-lab evaluate --help`")
    return Finding("case", OK, f"{len(found)} case duoi {config.cases_dir}")


def check_hook() -> Finding:
    """Cai hook vao mot thu muc tam rong roi chay that. Day la check dat gia nhat cua doctor.

    Khong dung workspace va khong dung fixture cua no: cau hoi o day la ve interpreter va ve chinh
    file hook, khong ve noi dung repo -- nen mot thu muc rong tra loi dung cau do va khong dung
    toi cua ai.
    """
    with tempfile.TemporaryDirectory(prefix="skill-lab-doctor-") as tmp:
        root = Path(tmp)
        try:
            fixture_mod.install_hook(root)
        except fixture_mod.FixtureError as exc:
            return Finding("hook", BAD, str(exc), "kiem `sys.executable` cua tien trinh dang chay skill-lab")
        result = fixture_mod.probe_hook(root)
    if not result.ok:
        return Finding(
            "hook",
            BAD,
            f"hook khong ghi duoc trajectory: {result.summary}",
            "khong co hook thi `trace.jsonl` se rong, va mot trace rong doc giong het mot lan chay sach",
        )
    return Finding("hook", OK, f"ghi duoc trajectory bang {fixture_mod.hook_interpreter()}")


def check_fixture(config: config_mod.Config) -> list[Finding]:
    """Tien de cua chien luoc fixture, cong binary dau tien cua `setup`/`assert_gates`."""
    findings: list[Finding] = []
    strategy = config.fixture.strategy
    resolved = strategy
    if strategy == "auto":
        resolved = "git-worktree" if (config.root / ".git").exists() else "copy"
    if resolved == "none":
        # `none` nghia la actor chay THANG trong workspace. Goi no la `copy` -- dieu nhanh `else`
        # ben duoi tung lam -- la noi sai theo dung huong khong duoc phep sai: nguoi doc tin rang
        # cay lam viec cua ho duoc bao ve trong khi khong co gi bao ve ca.
        findings.append(
            Finding(
                "fixture",
                WARN,
                f"{strategy} -> none: actor chay THANG trong {config.root}, khong co cach ly",
                "moi thay doi cua actor roi vao chinh workspace, va `writes_confined` khong con "
                "ranh gioi nao de do. Dat `copy` hoac `git-worktree` tru khi ban co chu y",
            )
        )
    elif resolved == "git-worktree":
        if not (config.root / ".git").exists():
            findings.append(
                Finding(
                    "fixture",
                    BAD,
                    f"chien luoc `{strategy}` can mot git repo, ma {config.root} khong phai",
                    "dat `fixture.strategy: copy`",
                )
            )
        else:
            rev = fixture_mod.workspace_rev(config.root)
            findings.append(
                Finding(
                    "fixture",
                    OK,
                    f"{strategy} -> git-worktree @ {rev or '?'}"
                    + (" -- worktree ghim HEAD, thay doi CHUA COMMIT se khong co trong fixture" if rev.endswith("+dirty") else ""),
                )
            )
    else:
        findings.append(Finding("fixture", OK, f"{strategy} -> copy (chep ca thay doi chua commit)"))

    for label, commands in (
        ("fixture.setup", [c for c in config.fixture.setup]),
        ("assert_gates", [g.command for g in config.fixture.assert_gates]),
    ):
        for argv in commands:
            if not argv:
                continue
            binary = argv[0]
            # Duong dan tuong doi duoc phan giai trong fixture, khong tren host -- doctor khong
            # phan quyet duoc no, va doan bua o day se ra mot canh bao sai.
            if "/" in binary or "\\" in binary:
                continue
            if shutil.which(binary) is None:
                findings.append(
                    Finding(
                        label,
                        BAD,
                        f"`{binary}` (trong `{' '.join(argv)}`) khong co tren PATH",
                        "doi sang mot binary co that -- vi du `python3` thay cho `python`, "
                        "hoac duong dan tuyet doi",
                    )
                )
    return findings


def run(config: config_mod.Config | None, *, config_error: str = "") -> list[Finding]:
    """Moi check, theo thu tu tu 'chinh bo do' ra 'workspace'.

    Thu tu nay de nguoi doc dung ngay o dong hong dau tien: khong co runtime thi moi dong ve
    workspace ben duoi deu khong con quan trong.
    """
    findings = [check_skill_lab(), check_python(), check_git(), check_hook()]
    if config is None:
        findings.append(
            Finding("workspace", BAD, config_error or "khong doc duoc cau hinh", "chay `skill-lab init`")
        )
        return findings
    findings.append(check_runtime(config.actor.cli))
    findings.append(check_workspace(config))
    findings.append(check_skills(config))
    findings.append(check_cases(config))
    findings.extend(check_fixture(config))
    return findings


def render(findings: list[Finding]) -> str:
    width = max(len(f.status) for f in findings)
    name_width = max(len(f.name) for f in findings)
    lines = []
    for f in findings:
        lines.append(f"  [{f.status:<{width}}] {f.name:<{name_width}}  {f.detail}")
        if f.fix:
            lines.append(f"  {' ' * (width + 2)} {' ' * name_width}  -> {f.fix}")
    bad = sum(1 for f in findings if f.status == BAD)
    warn = sum(1 for f in findings if f.status == WARN)
    lines.append("")
    if bad:
        lines.append(f"{bad} muc HONG, {warn} canh bao -- chua chay duoc `skill-lab run`.")
    elif warn:
        lines.append(f"0 muc hong, {warn} canh bao -- chay duoc.")
    else:
        lines.append("moi tien de dat -- chay duoc.")
    return "\n".join(lines)
