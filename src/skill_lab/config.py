"""`skill-lab.yaml`: thu duy nhat bo do nay biet ve workspace no dang do.

Day la duong bien giu cho kit nay dung duoc o repo khac. Moi thu rieng cua mot workspace -- skill
nam o dau, fixture dung the nao, lenh nao phai chay truoc khi actor bat dau -- deu di qua file
nay, va khong co dong code nao trong package biet ten mot repo cu the.

Mac dinh duoc chon de mot repo Claude Code binh thuong chay duoc ma khong can file nay: skill o
`.claude/skills`, fixture chep, actor la `claude`. File cau hinh la thu ban viet khi mac dinh sai,
khong phai thu ban phai viet de bat dau.

```yaml
workspace:
  id: my-workspace
  skills: .claude/skills
fixture:
  strategy: git-worktree
  exclude: [".venv", "node_modules"]
  setup:
    - ["python", "-m", "pip", "install", "-e", "."]
actor:
  model: sonnet
  max_turns: 40
```
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_NAME = "skill-lab.yaml"

#: Chep gi khi `strategy: copy`. Khong co danh sach `include` mac dinh: mot fixture thieu thu ma
#: skill can se hong theo kieu kho doc (agent lam dung, moi truong khong co gi), nen mac dinh la
#: chep tat tru nhung thu chac chan khong can. Danh sach loai tru thi nguoc lai -- de doan, de sua,
#: va sai lam o day chi ton dia.
DEFAULT_EXCLUDE = (
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".skill-lab",
    "dist",
    "build",
    ".next",
    ".turbo",
)


class ConfigError(Exception):
    """Khong tim thay workspace, hoac `skill-lab.yaml` khong dung hinh dang."""


@dataclass(frozen=True)
class GateSpec:
    """Mot gate, va **dung mot ma exit** ma no phai tra ve.

    `expected_exit` la mot con so bat buoc, khong phai mot co `must_fail: true`. Ly do khong phai
    su ty mi: `1`, `2` va `126` mang ba nghia khac nhau -- mot gate tu choi, mot gate loi cau hinh,
    va mot file khong chay duoc. Mot co nhi phan gop ca ba thanh "co, no that bai", va mot fixture
    co gate HONG se qua duoc dung nhu mot fixture co gate DANG CHAY. Do la dung cai lo hong ma
    `assert_gates` ton tai de bit.
    """

    command: tuple[str, ...]
    expected_exit: int
    name: str = ""
    timeout: int = 120

    @property
    def label(self) -> str:
        return self.name or " ".join(self.command)


@dataclass(frozen=True)
class FixtureConfig:
    #: `git-worktree` | `copy` | `none`.
    #:
    #: `git-worktree` la mac dinh khi repo la git, va do la lua chon co y nghia ky thuat chu khong
    #: phai toi uu toc do: mot worktree ghim dung mot commit, nen lan chay ghi lai duoc
    #: `workspace_rev`, va `replay` sau ba tuan dung tren dung bay nhieu byte ma lan dau da dung.
    #: `copy` chep trang thai lam viec hien tai, ke ca thay doi chua commit -- tien khi dang sua,
    #: nhung khong tai lap duoc, va `replay` se noi ro dieu do thay vi im lang.
    strategy: str = "auto"
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    #: Lenh chay trong fixture sau khi dung xong, dang argv. Vi du: cai package o che do edit de
    #: cac hook cua chinh workspace khong fail open ben trong fixture.
    setup: tuple[tuple[str, ...], ...] = ()
    #: Cac gate ma workspace doi hoi phai CON HIEU LUC ben trong fixture. Chay sau `setup`, truoc
    #: actor; mot gate khong dung exit code lam ca lan chay dung lai voi `FIXTURE_INVALID`.
    #:
    #: Day la cau tra loi cho lo hong lon nhat cua thiet ke: neu fixture lam gate cua workspace
    #: ngung cuong che -- vi thieu mot thu muc, vi package chua cai -- thi chung van co mat, van
    #: chay, va khong gac gi ca. Luc do bo do khong con do "skill dan agent the nao duoi ap luc
    #: that", no do "agent lam gi khi khong ai gac", va khong co dong nao trong bao cao noi rang
    #: hai thu do da bi trao doi cho nhau.
    assert_gates: tuple["GateSpec", ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActorConfig:
    cli: str = "claude"
    model: str = "sonnet"
    #: Muc effort truyen cho CLI. Rong nghia la khong truyen `--effort` va de CLI tu chon -- khac
    #: han voi viec bo do tu ghi mot muc mac dinh ma no chua bao gio gui di.
    effort: str = ""
    max_turns: int = 40
    timeout_seconds: int = 20 * 60
    permission_mode: str = "bypassPermissions"
    #: Duong dan toi mot file chi dan nap bang `--append-system-prompt`. Chi dan do KHONG duoc
    #: nhac toi thang cham: mot actor biet rubric se dien lai checklist thay vi hanh xu nhu mot
    #: phien that, va phep do mat nghia ngay tai do.
    system_prompt: str = ""


@dataclass(frozen=True)
class JudgeConfig:
    cli: str = "claude"
    #: Co y dat khac ho voi model cua actor. Judge thien vi van phong cung ho, thien vi cau dai, va
    #: thien vi vi tri trong mot so sanh cap.
    model: str = "claude-haiku-4-5"
    timeout_seconds: int = 180


@dataclass(frozen=True)
class Config:
    root: Path
    id: str
    skills_dir: Path
    cases_dir: Path
    runs_dir: Path
    fixture: FixtureConfig
    actor: ActorConfig
    judge: JudgeConfig
    path: Path | None = None

    def skill_dir(self, skill: str) -> Path:
        return self.skills_dir / skill

    def has_skill(self, skill: str) -> bool:
        return (self.skill_dir(skill) / "SKILL.md").is_file()

    def skills(self) -> list[str]:
        if not self.skills_dir.is_dir():
            return []
        return sorted(p.name for p in self.skills_dir.iterdir() if (p / "SKILL.md").is_file())


def find_root(start: Path | None = None) -> Path:
    """`skill-lab.yaml` o day hoac o thu muc cha; neu khong co thi goc git; neu khong nua thi cwd.

    Ba nac, va nac cuoi co y khong bao loi. Mot bo do bat nguoi ta viet file cau hinh truoc khi
    chay duoc lenh dau tien la mot bo do khong ai chay lenh dau tien.
    """
    # `Path(...)` bao quanh chu khong chi `start or Path.cwd()`: mot chuoi truyen vao day se no ra
    # `AttributeError: 'str' object has no attribute 'resolve'`, mot thong bao khong noi gi ve
    # dieu that su sai.
    here = Path(start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return here


def _argv_list(raw: Any) -> tuple[tuple[str, ...], ...]:
    """Chap nhan ca `["a", "b"]` lan `[["a","b"], ["c"]]`, va ca mot chuoi.

    Mot chuoi duoc tach bang `shlex` chu khong chay qua shell: mot lenh setup chay qua shell la mot
    cho cho quoting cua Windows va POSIX khac nhau, va khac biet do se hien ra o may cua nguoi
    khac chu khong phai o may nguoi viet.
    """
    import shlex

    if not raw:
        return ()
    if isinstance(raw, str):
        return (tuple(shlex.split(raw)),)
    out: list[tuple[str, ...]] = []
    for entry in raw:
        if isinstance(entry, str):
            out.append(tuple(shlex.split(entry)))
        else:
            out.append(tuple(str(x) for x in entry))
    return tuple(out)


def _gate_list(raw: Any) -> tuple[GateSpec, ...]:
    """Doc `fixture.assert_gates`, va tu choi moi cach viet khong noi ro ma exit mong doi."""
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("`fixture.assert_gates` phai la mot danh sach")

    gates = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"`assert_gates[{i}]` phai la mot mapping co `command` va `expected_exit`")
        for rejected in ("must_fail", "should_fail", "expect_failure"):
            if rejected in entry:
                raise ConfigError(
                    f"`assert_gates[{i}]` dung `{rejected}` -- hay khai `expected_exit: <so>`. "
                    "Mot co nhi phan gop exit 1, 2 va 126 lam mot, nen mot gate DA HONG se qua "
                    "duoc dung nhu mot gate DANG CHAY"
                )
        command = entry.get("command")
        if not command:
            raise ConfigError(f"`assert_gates[{i}]` thieu `command`")
        if isinstance(command, str):
            import shlex

            argv = tuple(shlex.split(command))
        else:
            argv = tuple(str(x) for x in command)
        if not argv:
            raise ConfigError(f"`assert_gates[{i}].command` rong")
        if "expected_exit" not in entry:
            raise ConfigError(
                f"`assert_gates[{i}]` ({' '.join(argv)}) thieu `expected_exit`. Khong co mac dinh: "
                "gia dinh 'khac 0 la gate con song' chinh la gia dinh can duoc kiem"
            )
        try:
            expected = int(entry["expected_exit"])
        except (TypeError, ValueError):
            raise ConfigError(
                f"`assert_gates[{i}].expected_exit` phai la mot so nguyen, nhan {entry['expected_exit']!r}"
            ) from None
        gates.append(
            GateSpec(
                command=argv,
                expected_exit=expected,
                name=str(entry.get("name") or ""),
                timeout=int(entry.get("timeout") or 120),
            )
        )
    return tuple(gates)


def load(start: Path | None = None) -> Config:
    root = find_root(start)
    path = root / CONFIG_NAME
    raw: dict[str, Any] = {}
    if path.is_file():
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        if parsed is not None and not isinstance(parsed, dict):
            raise ConfigError(f"{path} khong phai mot mapping YAML")
        raw = parsed or {}

    ws = raw.get("workspace") or {}
    fx = raw.get("fixture") or {}
    ac = raw.get("actor") or {}
    jd = raw.get("judge") or {}

    def _path(value: Any, default: str) -> Path:
        candidate = Path(str(value or default))
        return candidate if candidate.is_absolute() else root / candidate

    fixture = FixtureConfig(
        strategy=str(fx.get("strategy") or "auto"),
        include=tuple(str(x) for x in fx.get("include") or ()),
        exclude=tuple(str(x) for x in fx.get("exclude") or DEFAULT_EXCLUDE),
        setup=_argv_list(fx.get("setup")),
        assert_gates=_gate_list(fx.get("assert_gates")),
        env={str(k): str(v) for k, v in (fx.get("env") or {}).items()},
    )
    actor = ActorConfig(
        cli=str(ac.get("cli") or "claude"),
        model=str(ac.get("model") or os.environ.get("SKILL_LAB_MODEL") or "sonnet"),
        effort=str(ac.get("effort") or os.environ.get("SKILL_LAB_EFFORT") or ""),
        max_turns=int(ac.get("max_turns") or 40),
        timeout_seconds=int(ac.get("timeout_seconds") or 20 * 60),
        permission_mode=str(ac.get("permission_mode") or "bypassPermissions"),
        system_prompt=str(ac.get("system_prompt") or ""),
    )
    judge = JudgeConfig(
        cli=str(jd.get("cli") or "claude"),
        model=str(jd.get("model") or "claude-haiku-4-5"),
        timeout_seconds=int(jd.get("timeout_seconds") or 180),
    )
    return Config(
        root=root,
        id=str(ws.get("id") or root.name),
        skills_dir=_path(ws.get("skills"), ".claude/skills"),
        cases_dir=_path(raw.get("cases"), "cases"),
        runs_dir=_path(raw.get("runs"), ".skill-lab/runs"),
        fixture=fixture,
        actor=actor,
        judge=judge,
        path=path if path.is_file() else None,
    )
