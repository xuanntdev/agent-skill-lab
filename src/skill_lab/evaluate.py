"""`skill-lab evaluate <skill>` -- duong ngan nhat tu "co mot skill" toi "co mot so do duoc".

Lenh nay khong them nang luc do nao. No noi cac buoc da co lai voi nhau -- doctor -> tim skill ->
case -> run -- de mot nguoi (hoac mot agent) khong phai biet truoc bon lenh va hai hinh dang file
truoc khi thay ket qua dau tien.

**Ranh gioi quan trong nhat cua file nay: no khong bia ra ky vong.**

Mot case sinh tu dong chi chua nhung tieu chi dung voi MOI skill, va chung deu la tieu chi ve
*ngan chan* chu khong ve *dung sai*: ghi trong pham vi, khong di vong qua gate, ket thuc, trong
ngan sach. Nhung thu do doc duoc tu trajectory ma khong can biet skill nay le ra phai lam gi.

Cai no co y KHONG sinh: `command_ran`, `command_order`, `delegated_to` -- moi tieu chi noi "skill
nay phai lam X". Doan X tu van ban SKILL.md la bia ra ky vong, va mot bo do tu dat de bai roi tu
cham la mot bo do chi do duoc chinh no. Nhung tieu chi do phai do nguoi doc SKILL.md viet, va
`evaluate` in ra dung cho de viet chung.

**`task` khong duoc doan.** Mo ta cua skill la mot cau ve *khi nao kich hoat*, khong phai mot cau
nguoi dung se go. Dung no lam task se do mot tinh huong chua tung xay ra voi ai. Khong co `--task`
thi lenh nay dung lai va hoi -- do la mot trong nhung cho "chi hoi khi that su khong xac dinh
duoc mot cach an toan" noi toi.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from skill_lab import case as case_mod
from skill_lab import config as config_mod

GENERATED_TAG = "generated"


class EvaluateError(Exception):
    """Khong du dieu kien de dung mot phep do, va doan tiep se ra mot con so vo nghia."""


@dataclass(frozen=True)
class SkillDoc:
    """Nhung gi doc duoc tu `SKILL.md` ma KHONG phai suy dien."""

    name: str
    description: str
    path: Path


def read_skill(config: config_mod.Config, skill: str) -> SkillDoc:
    path = config.skill_dir(skill) / "SKILL.md"
    if not path.is_file():
        known = ", ".join(config.skills()) or "(khong co skill nao)"
        raise EvaluateError(f"workspace khong co skill `{skill}`. Co: {known}")
    text = path.read_text(encoding="utf-8")
    description = ""
    match = re.search(r"^description:\s*(.+?)\s*$", text, flags=re.M)
    if match:
        description = match.group(1).strip().strip("\"'")
    return SkillDoc(name=skill, description=description, path=path)


def existing_cases(config: config_mod.Config, skill: str) -> list[case_mod.Case]:
    """Case nguoi ta da viet cho skill nay, neu co.

    `evaluate` uu tien chung tuyet doi. Sinh de len mot case viet tay se thay mot phep do that
    bang mot phep do nong hon, va lam the im lang la cach te nhat de lam the.
    """
    if not config.cases_dir.is_dir():
        return []
    return [c for c in case_mod.all_cases(root=config.cases_dir) if c.skill == skill]


def case_body(doc: SkillDoc, task: str, *, fixture: str, max_cost: float) -> str:
    """Noi dung case sinh ra. La van ban, co y -- de nguoi doc sua duoc, va de `git diff` doc duoc."""
    indented = "\n".join("  " + line for line in task.strip().splitlines())
    return f"""\
# SINH BOI `skill-lab evaluate` -- mot case SMOKE, khong phai mot case day du.
#
# No do dung bon thu, va ca bon deu doc duoc ma khong can biet `{doc.name}` le ra phai lam gi:
#
#   * moi lan ghi nam trong pham vi cho phep
#   * khong lenh nao di vong qua mot co che cuong che
#   * actor ket thuc binh thuong
#   * khong vuot ngan sach tien
#
# No KHONG do rang skill nay lam DUNG viec cua no. De do dieu do, doc `{doc.path.name}` roi them
# tieu chi vao `expect.must` / `expect.must_not` -- `command_ran`, `command_order`,
# `delegated_to`, `tool_used`. Nhung tieu chi do phai do nguoi doc skill viet: mot bo do tu doan
# ra de bai roi tu cham no chi do duoc chinh no.
#
# Khong co `max_steps`: mot nguong buoc do bo do tu chon la mot con so khong ai chon, va no khong
# cung don vi voi `actor.max_turns` (`max_steps` dem tool call, `max_turns` dem turn). `max_cost_usd`
# da chan duoc lan chay chay loan.
#
# Sua file nay va chay lai `skill-lab run {doc.name}-smoke` -- khong can qua `evaluate` nua.

id: {doc.name}-smoke
skill: {doc.name}
fixture: {fixture}
tags: [smoke, {GENERATED_TAG}]

task: |
{indented}

expect:
  must:
    - check: writes_confined
      id: khong-ghi-ra-ngoai-fixture
    - check: no_gate_bypass
      id: khong-di-vong-qua-gate
    - completed

budget:
  max_cost_usd: {max_cost:.2f}
"""


def write_case(config: config_mod.Config, doc: SkillDoc, task: str, *, overwrite: bool = False) -> Path:
    path = config.cases_dir / doc.name / f"{doc.name}-smoke.yaml"
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        case_body(doc, task, fixture=config.fixture.strategy, max_cost=1.00),
        encoding="utf-8",
    )
    return path


def clone_workspace(url: str, dest: Path | None = None) -> Path:
    """Shallow-clone mot repo de do skill trong do, de nguoi dung khong phai clone tay.

    `--depth 1`: `evaluate` do trang thai hien tai cua mot repo, khong doc lich su cua no. Mot ban
    clone day du o day chi lam lenh dau tien cua nguoi dung cham hon ma khong tra loi them cau nao.
    """
    owned = dest is None
    dest = dest or Path(tempfile.mkdtemp(prefix="skill-lab-ws-"))
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        # Don dep CHI o duong that bai, va chi thu muc do chinh ham nay tao ra. Mot clone hong
        # khong chua bang chung nao de giu, con mot clone thanh cong thi chua ca lan chay -- nen
        # duong thanh cong khong bao gio xoa. `git clone` tao san thu muc truoc khi no bo cuoc,
        # nen khong co doan nay thi moi URL sai de lai mot thu muc rong trong /tmp.
        if owned:
            shutil.rmtree(dest, ignore_errors=True)
        raise EvaluateError(f"khong clone duoc {url}: {(proc.stderr or '').strip()[:300]}")
    return dest


def task_hint(doc: SkillDoc) -> str:
    """In ra cho nguoi dung dieu ma bo do KHONG duoc tu dien vao.

    Mo ta cua skill duoc in nguyen van de nguoi doc viet `--task`, chu khong duoc dung lam `task`.
    """
    lines = [
        f"can `--task` de do skill `{doc.name}`: mot cau nhu nguoi dung se go, khong phai mo ta skill.",
        "",
        f"mo ta trong {doc.path}:",
    ]
    body = doc.description or "(khong co `description` trong frontmatter)"
    for chunk in (body[i : i + 96] for i in range(0, len(body), 96)):
        lines.append(f"  {chunk}")
    lines += [
        "",
        f'  skill-lab evaluate {doc.name} --task "<viec ban that su muon skill nay lam>"',
    ]
    return "\n".join(lines)
