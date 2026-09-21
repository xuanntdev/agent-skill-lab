"""Dung mot ban sao cach ly cua workspace de actor chay ben trong.

**Cach ly dat duoc bang cwd.** Actor chay `claude -p` voi cwd la fixture; hook, skill, cau hinh va
moi cong cu cua workspace deu phan giai tu do. Khong can co che nao khac, va do la dieu da do
duoc chu khong phai suy ra.

**Hook cua workspace duoc giu nguyen, hook cua lab duoc them vao.** Day la chi tiet de bo qua nhat
va no quyet dinh phep do co nghia hay khong. Neu fixture lam cac gate cua chinh workspace ngung
hoat dong -- vi thieu mot thu muc, vi package chua cai -- thi chung van co mat, van chay, va
khong gac gi ca. Luc do bo do khong con do "skill dan agent the nao duoi ap luc that", no do
"agent lam gi khi khong ai gac". Hai thu do khac nhau, va cai thu hai vo dung.

`setup:` trong `skill-lab.yaml` ton tai chinh vi ly do do: workspace nao can cai package cua no
vao fixture de gate chay duoc thi khai o day.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from skill_lab.config import Config, GateSpec

HOOK_SOURCE = Path(__file__).resolve().parent / "hooks" / "trace_hook.py"
HOOK_REL = ".claude/hooks/skill_lab_trace.py"
TRACE_REL = ".skill-lab/trace.jsonl"


class FixtureError(Exception):
    """Khong dung duoc fixture theo hinh dang da khai."""


@dataclass(frozen=True)
class GateResult:
    """Mot gate da chay ben trong fixture, va cai no tra ve."""

    spec: GateSpec
    actual_exit: int
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.actual_exit == self.spec.expected_exit

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        text = (self.stderr.strip() or self.stdout.strip()).replace("\n", " ")
        return text[:160]


class FixtureInvalid(FixtureError):
    """Fixture da dung xong nhung **khong con la moi truong ma workspace yeu cau**.

    Day khong phai mot that bai cua skill, va cung khong phai mot loi cua cong cu. No la mot cau
    tra loi thu ba: phep do nay khong thuc hien duoc, vi cai dang duoc do khong con o day. Gop no
    vao mot trong hai loai kia la cach mot bang ket qua bat dau noi doi -- hoac skill bi do oan,
    hoac mot lan chay khong do duoc gi bi ghi nhan nhu mot lan chay binh thuong.
    """

    def __init__(self, results: list["GateResult"], *, mutated: list[str] | None = None):
        self.results = results
        self.mutated = mutated or []
        failed = [r.spec.label for r in results if not r.ok]
        detail = ", ".join(failed) or "fixture bi thay doi boi chinh gate assertion"
        super().__init__(f"FIXTURE_INVALID: {detail}")


@dataclass(frozen=True)
class Fixture:
    root: Path
    strategy: str
    workspace_rev: str

    @property
    def trace_path(self) -> Path:
        return self.root / TRACE_REL


def _git(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, (proc.stdout or "").strip()


def workspace_rev(root: Path) -> str:
    """`<sha12>` cua HEAD, cong `+dirty` khi cay lam viec co thay doi chua commit.

    `+dirty` khong phai canh bao mang tinh phong cach. No la cau tra loi trung thuc cho cau hoi
    `replay` dat ra: lan chay nay co tai lap duoc khong. Mot commit thi co; mot cay ban thi khong,
    va noi ro con hon de nguoi doc tuong la co.
    """
    code, head = _git(root, "rev-parse", "--short=12", "HEAD")
    if code != 0 or not head:
        return ""
    code, status = _git(root, "status", "--porcelain")
    return f"{head}+dirty" if (code == 0 and status) else head


def _resolve_strategy(config: Config) -> str:
    """`auto` chon worktree khi repo la git **va da co it nhat mot commit**.

    Ve thu hai khong phai chi tiet vun: mot repo vua `git init` co `.git`, nen kiem tra "day co
    phai git khong" se noi co, roi `git worktree add HEAD` do vi chua co HEAD nao. Loi luc do noi
    ve worktree chu khong noi ve dieu that su dang xay ra, va no xuat hien dung o lan chay dau tien
    cua mot nguoi moi.
    """
    strategy = config.fixture.strategy
    if strategy != "auto":
        return strategy
    code, _ = _git(config.root, "rev-parse", "HEAD")
    return "git-worktree" if code == 0 else "copy"


def _copy_tree(config: Config, dest: Path) -> None:
    exclude = set(config.fixture.exclude)

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {n for n in names if n in exclude}

    if config.fixture.include:
        dest.mkdir(parents=True, exist_ok=True)
        for rel in config.fixture.include:
            src = config.root / rel
            if not src.exists():
                raise FixtureError(f"`fixture.include` tro toi thu khong ton tai: {rel}")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, ignore=ignore, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
        return
    shutil.copytree(config.root, dest, ignore=ignore, dirs_exist_ok=True)


def _git_worktree(config: Config, dest: Path, rev: str) -> None:
    base = rev.split("+", 1)[0] or "HEAD"
    code, out = _git(config.root, "worktree", "add", "--detach", str(dest), base)
    if code != 0:
        raise FixtureError(f"`git worktree add` that bai: {out}")


def remove_worktree(config: Config, dest: Path) -> None:
    """Go worktree khoi so dang ky cua git, khong chi xoa thu muc.

    Mot thu muc bi xoa tay de lai mot muc mo con trong `git worktree list`, va sau vai chuc lan
    chay thi repo that mang mot danh sach rac ma khong ai lan ra nguon goc.
    """
    _git(config.root, "worktree", "remove", "--force", str(dest))
    _git(config.root, "worktree", "prune")


def _merge_hooks(settings: dict, command: str) -> dict:
    """Them hook cua lab vao ma khong dung toi hook san co cua workspace.

    Doc `settings["hooks"][event]` nhu mot danh sach matcher-group, dung hinh dang Claude Code
    dung, va chi *them* mot group. Ghi de ca khoa `hooks` se tat moi gate cua workspace, va bo do
    se im lang do mot moi truong khong con giong moi truong that o dung diem quan trong nhat.
    """
    hooks = settings.setdefault("hooks", {})
    for event in ("PreToolUse", "PostToolUse"):
        groups = hooks.setdefault(event, [])
        groups.append(
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": command, "timeout": 15}],
            }
        )
    return settings


def install_hook(root: Path) -> Path:
    """Chep hook vao fixture va dang ky no trong `.claude/settings.json` cua fixture."""
    hook_path = root / HOOK_REL
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SOURCE, hook_path)

    settings_path = root / ".claude" / "settings.json"
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as exc:
            raise FixtureError(f"`.claude/settings.json` cua workspace khong phai JSON: {exc}") from exc

    # `$CLAUDE_PROJECT_DIR` duoc host thay bang goc project, tuc la fixture -- khong phai repo that.
    # Duong dan tuyet doi cua may nguoi viet se tro nguoc ve repo that va ghi trace ra ngoai fixture.
    command = f'python "$CLAUDE_PROJECT_DIR/{HOOK_REL}"'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(_merge_hooks(settings, command), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return hook_path


def _run_setup(config: Config, root: Path) -> None:
    for argv in config.fixture.setup:
        proc = subprocess.run(
            list(argv),
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={**os.environ, **config.fixture.env},
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            raise FixtureError(f"lenh setup {' '.join(argv)} exit {proc.returncode}: {detail}")


def _fingerprint(root: Path, *, exclude: set[str]) -> dict[str, tuple[int, int]]:
    """`{duong dan tuong doi: (kich thuoc, mtime_ns)}` cua moi file trong fixture.

    Dung de chung minh dieu ma muc 4 doi hoi: gate assertion chi QUAN SAT. Mot assertion tu sua
    fixture de minh xanh -- tao file con thieu, tat mot hook, cai them mot package -- se lam moi
    con so sau do noi ve mot moi truong khac voi moi truong da duoc kiem, va khong co dong nao
    trong bao cao chi ra dieu do.

    So sanh bang `(size, mtime_ns)` chu khong bang noi dung: doc lai toan bo cay hai lan cho moi
    lan chay la mot cai gia khong tuong xung voi thu can bat, va mot thay doi giu nguyen ca hai
    truong nay la thu khong the xay ra do mot lenh vo tinh.
    """
    found: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if any(part in exclude for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return found


def _diff_fingerprint(before: dict, after: dict) -> list[str]:
    changed = [f"them: {p}" for p in sorted(set(after) - set(before))]
    changed += [f"xoa: {p}" for p in sorted(set(before) - set(after))]
    changed += [f"sua: {p}" for p in sorted(p for p in set(before) & set(after) if before[p] != after[p])]
    return changed


def check_gates(config: Config, root: Path) -> list[GateResult]:
    """Chay tung gate **ben trong fixture**, va tra ve cai chung noi.

    `cwd` la goc fixture, khong phai goc workspace that. Do la ca diem cua ham nay: mot gate chay
    tren host se tra loi mot cau hoi ve host, va cau hoi dang duoc dat la ve chinh moi truong ma
    actor sap chay trong do.
    """
    results: list[GateResult] = []
    env = {**os.environ, **config.fixture.env}
    for spec in config.fixture.assert_gates:
        try:
            proc = subprocess.run(
                list(spec.command),
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=spec.timeout,
                check=False,
                env=env,
            )
        except FileNotFoundError:
            # Mot gate khong chay duoc la mot gate khong gac. Day chinh la dang fail-open ma ca co
            # che nay ton tai de bat, nen no la mot ket qua chu khong phai mot ngoai le.
            results.append(
                GateResult(spec=spec, actual_exit=-1, error=f"khong chay duoc: {spec.command[0]!r} khong ton tai")
            )
            continue
        except subprocess.SubprocessError as exc:
            results.append(GateResult(spec=spec, actual_exit=-1, error=f"khong chay duoc: {exc}"))
            continue
        results.append(
            GateResult(
                spec=spec,
                actual_exit=proc.returncode,
                stdout=(proc.stdout or "")[-400:],
                stderr=(proc.stderr or "")[-400:],
            )
        )
    return results


def build(config: Config, dest: Path) -> Fixture:
    """Dung fixture tai `dest`, ma nguoi goi so huu vong doi.

    `dest` duoc cho la chua ton tai (git worktree doi the) hoac rong. Khong co gi o day xoa thu da
    co san: nguoi goi la cho duy nhat quyet dinh khi nao mot fixture bi xoa.
    """
    rev = workspace_rev(config.root)
    strategy = _resolve_strategy(config)

    if strategy == "none":
        fixture_root = config.root
    elif strategy == "git-worktree":
        _git_worktree(config, dest, rev)
        fixture_root = dest
    elif strategy == "copy":
        _copy_tree(config, dest)
        fixture_root = dest
    else:
        raise FixtureError(f"khong biet chien luoc fixture {strategy!r}")

    install_hook(fixture_root)
    _run_setup(config, fixture_root)
    (fixture_root / ".skill-lab").mkdir(parents=True, exist_ok=True)

    # Thu tu o day la toan bo hop dong: setup xong TRUOC, roi moi hoi "gate con song khong". Hoi
    # truoc setup se do mot moi truong chua duoc dung xong; hoi sau khi actor chay se la hoi mot
    # cau khong con dung de lam gi.
    if config.fixture.assert_gates:
        exclude = {".skill-lab", ".git", "__pycache__"}
        before = _fingerprint(fixture_root, exclude=exclude)
        gates = check_gates(config, fixture_root)
        mutated = _diff_fingerprint(before, _fingerprint(fixture_root, exclude=exclude))

        # Gate do truoc, roi moi toi chuyen chung co tu sua fixture khong. Thu tu nay de bao cao
        # tra loi dung cau hoi nguoi doc dang hoi -- "gate con song khong" -- thay vi mo dau bang
        # mot chi tiet ve chinh bo do.
        if not all(result.ok for result in gates):
            raise FixtureInvalid(gates, mutated=mutated)
        if mutated:
            raise FixtureInvalid(gates, mutated=mutated)

    return Fixture(root=fixture_root, strategy=strategy, workspace_rev=rev)


def destroy(config: Config, fixture: Fixture) -> None:
    if fixture.strategy == "none":
        return
    if fixture.strategy == "git-worktree":
        remove_worktree(config, fixture.root)
    shutil.rmtree(fixture.root, ignore_errors=True)
