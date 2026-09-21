"""Day mot case qua ca duong ong, va de lai mot ban ghi co the doc lai sau nay.

    case -> fixture -> actor -> trace -> trajectory -> check -> chan doan -> luu

`--dry` chay het duong ong nay ma khong goi model mot lan nao: no phat lai mot trace dong hop nam
canh case. Do khong phai mot che do demo. Mot lan chay that ton tien that, va moi lan sua bo cham,
bo chan doan hay bao cao ma phai tra tien de kiem lai la mot lan sua khong ai muon lam. File
`<case>.trace.jsonl` cho toan bo duong cham chay mien phi, va do la ly do cac test cua chinh kit
nay khong bao gio cham toi mot model.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from skill_lab import agent as agent_mod
from skill_lab import diagnose as diagnose_mod
from skill_lab import fixture as fixture_mod
from skill_lab import judge as judge_mod
from skill_lab import store, trace, verify
from skill_lab.case import Case
from skill_lab.config import Config
from skill_lab.model import RunRecord, call_steps, skill_version

DEFAULT_ACTOR_MD = Path(__file__).resolve().parent / "actor.md"


class RunnerError(Exception):
    """Case, fixture hoac actor khong the chay duoc."""


def canned_trace_path(case: Case) -> Path | None:
    """`<case>.trace.jsonl` nam canh case file, neu co."""
    if case.path is None:
        return None
    candidate = case.path.with_suffix(".trace.jsonl")
    return candidate if candidate.is_file() else None


def _actor_instructions(config: Config) -> str:
    path = Path(config.actor.system_prompt) if config.actor.system_prompt else DEFAULT_ACTOR_MD
    if not path.is_absolute():
        path = config.root / path
    if not path.is_file():
        path = DEFAULT_ACTOR_MD
    return path.read_text(encoding="utf-8")


def _tail(path: Path, seen: int, emit: Callable[[str], None]) -> int:
    """In moi dong sau `seen`, tra ve tong moi. Goi ca luc actor con dang chay -- `--step` in ngay
    khi mot dong roi xuong chu khong doi het moi in -- va mot lan nua sau khi tien trinh chet, de
    bat nhung gi roi xuong giua lan doc cuoi va luc no thuc su dung."""
    if not path.is_file():
        return seen
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[seen:]:
        if line.strip():
            emit(line)
    return len(lines)


def _replay_canned(source: Path, dest: Path, *, on_line: Callable[[str], None] | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            fh.write(line + "\n")
            fh.flush()
            if on_line:
                on_line(line)


def _fixture_invalid_diagnosis(record: RunRecord, invalid) -> diagnose_mod.Diagnosis:
    """Chan doan cho mot fixture bi tu choi. Chu so huu la `harness`, khong bao gio la `skill`.

    Khong co trajectory nao de neo vao, nhung do tin cay van la `high`: bang chung la ma exit cua
    chinh cac gate, do truc tiep, khong suy dien.
    """
    diag = diagnose_mod.Diagnosis(run_id=record.run_id)
    diag.verdict = "FIXTURE_INVALID"
    diag.category = "harness.gate_not_enforced"
    diag.owner = "harness"
    diag.confidence = diagnose_mod.HIGH
    diag.summary = (
        "Fixture khong con la moi truong ma workspace yeu cau, nen actor khong duoc khoi dong. "
        "Day khong phai mot phat bieu ve skill."
    )
    for result in invalid.results:
        mark = "dat" if result.ok else "KHONG DAT"
        diag.evidence.append(
            f"gate `{result.spec.label}`: mong doi exit {result.spec.expected_exit}, "
            f"nhan {result.actual_exit} -- {mark}"
            + (f" ({result.summary})" if result.summary else "")
        )
    for item in invalid.mutated:
        diag.evidence.append(f"gate assertion da SUA fixture: {item}")
    diag.hypothesis = (
        "Gate cua workspace khong con hieu luc ben trong fixture. Kiem `fixture.setup` truoc, "
        "roi toi chinh gate."
    )
    diag.suggested_change = (
        "Bo sung buoc cai dat con thieu vao `fixture.setup`, hoac sua lai `expected_exit` neu gate "
        "da doi hanh vi mot cach co chu y."
    )
    diag.suggestion = diag.suggested_change
    return diag


def execute(
    config: Config,
    case: Case,
    *,
    model: str = "",
    effort: str = "",
    label: str = "",
    dry: bool = False,
    keep: bool = False,
    use_judge: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> tuple[RunRecord, Path]:
    if not config.has_skill(case.skill):
        raise RunnerError(
            f"workspace khong co skill `{case.skill}` tai {config.skill_dir(case.skill)}"
        )

    run_id = store.new_run_id(case.id)
    record = RunRecord(
        run_id=run_id,
        case_id=case.id,
        skill=case.skill,
        skill_version=skill_version(config.skill_dir(case.skill)),
        model="" if dry else (model or config.actor.model),
        effort="" if dry else (effort or config.actor.effort),
        fixture=case.fixture or config.fixture.strategy,
        case_digest=case.digest,
        label=label,
        dry=dry,
        tags=case.tags,
        status="running",
        max_turns=config.actor.max_turns,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    directory = store.create(config.runs_dir, record)
    store.snapshot_case(directory, case.path)

    fixture_config = config
    if case.fixture:
        fixture_config = replace(config, fixture=replace(config.fixture, strategy=case.fixture))

    tmp = Path(tempfile.mkdtemp(prefix="skill-lab-")) / "ws"
    fx = None
    try:
        try:
            fx = fixture_mod.build(fixture_config, tmp)
        except fixture_mod.FixtureInvalid as invalid:
            # Actor KHONG chay. Day la ca diem cua `assert_gates`: neu gate cua workspace khong con
            # cuong che ben trong fixture thi lan chay sap toi se do "agent lam gi khi khong ai
            # gac", va con so do se duoc doc nhu mot phat bieu ve skill. Dung lai o day dat hon
            # nhieu so voi mot bang ket qua noi sai.
            record.status = "fixture_invalid"
            record.ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            store.save_gates(directory, invalid.results, mutated=invalid.mutated)
            store.save_diagnosis(directory, _fixture_invalid_diagnosis(record, invalid))
            store.save_record(directory, record)
            raise
        record.workspace_rev = fx.workspace_rev

        if dry:
            canned = canned_trace_path(case)
            if canned is None:
                raise RunnerError(
                    f"`--dry` can mot trace dong hop tai {case.path.with_suffix('.trace.jsonl')} "
                    "-- day la cach chay ca duong ong voi chi phi bang khong"
                )
            _replay_canned(canned, fx.trace_path, on_line=on_step)
            result = agent_mod.AgentResult(
                output=f"[dry] phat lai {canned.name}", exit_code=0, num_turns=0
            )
        else:
            seen = 0

            def poll() -> None:
                nonlocal seen
                if on_step:
                    seen = _tail(fx.trace_path, seen, on_step)

            result = agent_mod.run(
                f"/{case.skill} {case.task}",
                cwd=fx.root,
                actor=config.actor,
                trace_path=fx.trace_path,
                model=model,
                effort=effort or config.actor.effort,
                system_prompt=_actor_instructions(config),
                on_poll=poll if on_step else None,
            )
            if on_step:
                _tail(fx.trace_path, seen, on_step)

        steps = store.capture_trace(directory, fx.trace_path)

        record.ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record.exit_code = result.exit_code
        record.completed = result.completed
        record.cost_usd = result.cost_usd
        record.duration_ms = result.duration_ms
        record.num_turns = result.num_turns
        record.usage = result.usage
        record.actor_output = result.output
        record.num_steps = len(steps)
        record.num_tool_calls = len(call_steps(steps))

        ctx = verify.VerifyContext(
            steps=tuple(steps), fixture_root=fx.root, cwd=fx.root, record=record, environment=True
        )
        checks = verify.run_all(ctx, case.checks)

        judge_payload = None
        if use_judge and case.judge and not dry:
            answers = judge_mod.ask_all(
                case.judge,
                skill=case.skill,
                actor_output=record.actor_output,
                steps=steps,
                config=config.judge,
            )
            checks.extend(judge_mod.as_checks(answers))
            judge_payload = {a.id: {"question": a.question, "verdict": a.verdict, "why": a.why} for a in answers}

        store.save_evaluation(directory, checks, judge=judge_payload)
        diagnosis = diagnose_mod.diagnose(record, checks, steps)
        store.save_diagnosis(directory, diagnosis)
        record.status = "complete"
        store.save_record(directory, record)
        return record, directory
    except fixture_mod.FixtureInvalid:
        # Da duoc ghi day du o tren, va `fixture_invalid` KHAC `error`: mot ben la "moi truong
        # khong dung", ben kia la "cong cu hong". Bat o day, truoc nhanh chung, de nhanh chung
        # khong ghi de nhan.
        raise
    except Exception:
        # Mot lan chay no giua chung van la mot su that ve lan chay do, nhung no khong phai mot
        # ket qua. Danh dau `error` de cac bang gop bo qua no thay vi dem no nhu mot lan that bai.
        record.status = "error"
        record.ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        store.save_record(directory, record)
        raise
    finally:
        if fx is not None:
            if keep:
                # Worktree phai duoc go khoi so dang ky cua git TRUOC khi thu muc bi chuyen di, neu
                # khong repo that se mang mot muc mo tro toi mot cho khong con gi.
                if fx.strategy == "git-worktree":
                    fixture_mod.remove_worktree(fixture_config, fx.root)
                if fx.strategy != "none":
                    store.keep_fixture(directory, fx.root)
            else:
                fixture_mod.destroy(fixture_config, fx)
        shutil.rmtree(tmp.parent, ignore_errors=True)


def rescore(config: Config, directory: Path, case: Case) -> tuple[list, object]:
    """Cham lai mot lan chay da luu: **trajectory da co -> bo cham hien tai**. Khong goi model, va
    khong cham vao the gioi ben ngoai.

    Day la tinh chat ma ca thiet ke nay dua vao, va la thu duy nhat o day co quyen doi hoi tinh tat
    dinh. Actor la mot model: hai lan chay sinh hai trajectory khac nhau, nen doi hai lan chay cho
    cung diem la doi bo di chinh thu dang duoc do. Thu *phai* tat dinh la bo cham.

    **`environment=False` la phan sua quan trong nhat cua ham nay.** Ban dau no truyen thu muc lan
    chay vao lam `fixture_root` khi fixture khong con, va hau qua do duoc bang hai probe:

    * mot check `shell` VAN chay `subprocess` that -- mot lenh `--rescore` tu nhan la khong chay gi
      van tao duoc file tren dia;
    * `file_exists` tra MAU DO voi ly do "file khong ton tai trong fixture", trong khi su that la
      fixture da bi xoa. Mot cau dung ve chu nghia va sai hoan toan ve y nghia, va no bien "khong
      do duoc" thanh "skill sai".

    Gio ca hai tra `NOT_EVALUATED`, tru khi lan chay goc duoc giu bang `--keep`.
    """
    record = store.load_record(directory)
    steps = store.load_trajectory(directory)
    fixture_root = directory / store.FIXTURE_DIR
    alive = fixture_root.is_dir()
    ctx = verify.VerifyContext(
        steps=tuple(steps),
        fixture_root=fixture_root if alive else directory,
        cwd=fixture_root if alive else directory,
        record=record,
        environment=alive,
    )
    checks = verify.run_all(ctx, case.checks)
    diagnosis = diagnose_mod.diagnose(record, checks, steps)
    return checks, diagnosis


def load_run_steps(directory: Path):
    return store.load_trajectory(directory)


def raw_rows(directory: Path):
    return trace.read(directory / store.TRACE_JSONL)
