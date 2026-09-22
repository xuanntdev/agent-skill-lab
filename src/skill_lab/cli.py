"""`skill-lab <lenh>` -- be mat duy nhat mot nguoi go bang tay.

`argparse` chu khong phai mot framework CLI: kit nay chay ben trong fixture cua repo khac, va moi
dependency them vao la mot thu co the xung dot voi repo do hoac vang mat trong CI cua no.

Ma tra ve: `0` khi lan chay dat va khong co gi di lui, `1` khi khong dat, `2` khi chinh cong cu
khong chay duoc. Ba muc, vi mot lan chay do va mot cau hinh sai la hai viec khac nhau ma mot
scheduled job phai phan biet duoc.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from skill_lab import case as case_mod
from skill_lab import compare as compare_mod
from skill_lab import config as config_mod
from skill_lab import diagnose as diagnose_mod
from skill_lab import doctor, evaluate, report, runner, store
from skill_lab import experiment as experiment_mod
from skill_lab import fixture as fixture_mod
from skill_lab import model as model_mod
from skill_lab.model import RunRecord

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERROR = 2
#: Ma rieng cho "khong do duoc", tach khoi "skill do" (1) va "cong cu hong" (2).
#:
#: Mot scheduled job phai phan biet duoc ba thu nay: mot skill di lui thi bao cho nguoi viet skill,
#: mot cong cu hong thi bao cho nguoi bao tri kit, con mot fixture khong hop le thi bao cho nguoi
#: giu workspace -- va gop chung vao mot ma se gui sai nguoi o hai trong ba truong hop.
EXIT_FIXTURE_INVALID = 3
#: Ma rieng cho "actor chay xong ma khong ghi duoc bang chung nao". Khong phai 1: khong co gi cua
#: skill bi bac bo. Khong phai 0: cung khong co gi duoc chung minh. Mot lan chay nhu the can mot
#: lan chay lai, khong can mot commit sua skill.
EXIT_NO_EVIDENCE = 4

STARTER_CONFIG = """\
# skill-lab.yaml -- thu duy nhat skill-lab biet ve workspace nay.
workspace:
  id: {id}
  skills: .claude/skills

fixture:
  # `git-worktree` ghim dung mot commit, nen lan chay tai lap duoc. `copy` chep ca thay doi chua
  # commit -- tien khi dang sua, nhung `replay` se noi ro la khong tai lap duoc.
  strategy: auto
  # Lenh chay trong fixture sau khi dung xong. Khai o day neu cac gate cua chinh workspace can mot
  # buoc cai dat de thuc su chay ben trong fixture -- mot gate im lang fail open bien ca phep do
  # thanh do "agent lam gi khi khong ai gac".
  setup: []

  # Chung minh rang gate cua workspace CON HIEU LUC ben trong fixture. Chay sau `setup`, truoc
  # actor; mot gate sai exit code lam ca lan chay dung lai voi FIXTURE_INVALID va actor khong
  # duoc khoi dong.
  #
  # `expected_exit` la bat buoc va phai la mot so. Khong co `must_fail: true`: exit 1, 2 va 126
  # mang ba nghia khac nhau, va mot co nhi phan se cho mot gate DA HONG qua duoc dung nhu mot
  # gate DANG CHAY.
  #
  # `command` chay nguyen van, khong qua shell va khong phan giai ho ten binary: dat `python` o
  # day tren mot may chi co `python3` se lam gate khong chay duoc, va mot gate khong chay duoc la
  # mot gate khong gac.
  #
  # assert_gates:
  #   - name: ghi vao repo bi chan khi chua co lease
  #     command: ["python3", "scripts/thu-ghi.py"]
  #     expected_exit: 2

actor:
  model: sonnet
  max_turns: 40

judge:
  # Co y khac ho voi actor: mot judge cung ho voi thu no cham la mot judge dang cham chinh giong
  # minh.
  model: claude-haiku-4-5

cases: cases
runs: .skill-lab/runs
"""


def _config(args: argparse.Namespace) -> config_mod.Config:
    return config_mod.load(Path(args.workspace) if args.workspace else None)


def _verdict_of(directory: Path) -> str:
    return str(store.load_diagnosis(directory).get("verdict") or "?")


def _cases_for(args: argparse.Namespace, config: config_mod.Config) -> list[case_mod.Case]:
    if args.dataset:
        return case_mod.dataset(args.dataset, root=config.cases_dir)
    if args.case:
        return [case_mod.find(args.case, root=config.cases_dir)]
    raise config_mod.ConfigError("can `<case>` hoac `--dataset`")


# ── run ─────────────────────────────────────────────────────────────────────────


def cmd_run(args: argparse.Namespace) -> int:
    config = _config(args)
    return _run_cases(config, _cases_for(args, config), args)


def _run_cases(
    config: config_mod.Config, cases: list[case_mod.Case], args: argparse.Namespace
) -> int:
    """Vong chay + bao cao + ma thoat, dung chung cho `run` va `evaluate`.

    Tach ra de `evaluate` khong co mot duong bao cao thu hai cua rieng no. Hai duong bao cao se
    lech nhau, va khi do cung mot lan chay se doc khac nhau tuy nguoi dung go lenh nao."""
    emit = (lambda line: print(f"  . {line[:150]}")) if args.step else None

    failures = 0
    invalid = 0
    #: Case chay xong ma khong ghi duoc trajectory nao -- dem rieng, khong gop vao `failures`.
    blind = 0
    for case in cases:
        try:
            record, directory = runner.execute(
                config,
                case,
                model=args.model or "",
                effort=getattr(args, "effort", "") or "",
                label=args.label or "",
                dry=args.dry,
                keep=args.keep,
                use_judge=args.judge,
                on_step=emit,
            )
        except fixture_mod.FixtureInvalid as exc:
            print()
            print(report.gates_block(exc.results, exc.mutated))
            print()
            print("FIXTURE_INVALID")
            print("Actor KHONG duoc khoi dong -- moi truong nay khong do duoc dieu case yeu cau.")
            invalid += 1
            continue
        checks = store.load_checks(directory)
        diagnosis = store.load_diagnosis(directory)

        print()
        print(report.run_header(record))
        print()
        print(report.run_status(record))
        print(report.metrics(record))
        print()
        print(report.checks_table(checks))
        print()
        print(report.score_line(checks))
        print()
        print(report.diagnosis_block(diagnose_mod.Diagnosis(**diagnosis)))
        print()
        print(f"luu tai: {directory}")
        verdict = diagnosis.get("verdict")
        if verdict == diagnose_mod.NO_EVIDENCE:
            blind += 1
        elif verdict != "PASS":
            failures += 1

    if len(cases) > 1:
        print()
        tail = f", {invalid} FIXTURE_INVALID" if invalid else ""
        tail += f", {blind} NO_EVIDENCE" if blind else ""
        print(f"tong: {len(cases) - failures - invalid - blind}/{len(cases)} case dat{tail}")
    if invalid:
        return EXIT_FIXTURE_INVALID
    if failures:
        return EXIT_FAILED
    # Sau `failures`, khong truoc: mot case do that van la tin quan trong hon mot case khong do
    # duoc, va mot lenh chi tra ve duoc mot ma.
    if blind:
        return EXIT_NO_EVIDENCE
    return EXIT_OK


# ── debug ───────────────────────────────────────────────────────────────────────


def cmd_debug(args: argparse.Namespace) -> int:
    config = _config(args)
    directory = store.resolve(config.runs_dir, args.run_id)
    record = store.load_record(directory)
    checks = store.load_checks(directory)
    diagnosis = diagnose_mod.Diagnosis(**store.load_diagnosis(directory))
    steps = store.load_trajectory(directory)

    print(report.run_header(record))
    print()
    print(report.run_status(record))
    print(report.metrics(record))
    print()
    print(report.checks_table(checks))
    print()
    print(report.diagnosis_block(diagnosis))
    print()
    print("trajectory (>> la buoc sai dau tien)")
    print(report.trajectory_block(steps, mark=diagnosis.first_error_step, limit=args.limit))
    if record.actor_output and args.output:
        print()
        print("dau ra cuoi cung cua actor")
        print(record.actor_output[:4000])
    return EXIT_OK if diagnosis.verdict == "PASS" else EXIT_FAILED


# ── replay ──────────────────────────────────────────────────────────────────────


def cmd_replay(args: argparse.Namespace) -> int:
    """Hai nghia cua "chay lai", va ca hai deu that.

    `--rescore` cham lai trajectory da luu ma khong goi model: mien phi, tat dinh, va la cach kiem
    rang bo cham khong tu doi y. Khong co co do, lenh nay dung mot fixture moi tu dung commit cu
    va chay lai case -- mot lan chay MOI, so sanh duoc, khong phai mot ban sao.
    """
    config = _config(args)
    directory = store.resolve(config.runs_dir, args.run_id)
    record = store.load_record(directory)
    snapshot = directory / store.CASE_SNAPSHOT
    case = case_mod.load(snapshot) if snapshot.is_file() else case_mod.find(record.case_id, root=config.cases_dir)

    if args.rescore:
        checks, diagnosis = runner.rescore(config, directory, case)
        print(report.run_header(record))
        print()
        print(report.checks_table(checks))
        print()
        print(report.score_line(checks))
        print()
        print(report.diagnosis_block(diagnosis))
        # Chi so cac check CHI DOC TRAJECTORY. Cac check cham vao moi truong khong duoc cham lai
        # khi fixture da mat, nen chung se khac ket qua da luu mot cach hoan toan hop le -- gop
        # chung vao phep so nay se in ra mot canh bao "khong tat dinh" cho mot he thong dang cu xu
        # dung nhu thiet ke.
        env_ids = {c.id for c in checks if c.status == model_mod.NOT_EVALUATED}
        stored = [c for c in store.load_checks(directory) if c.id not in env_ids]
        fresh = [c for c in checks if c.id not in env_ids]
        same = [c.to_dict() for c in fresh] == [c.to_dict() for c in stored]
        print()
        if env_ids:
            print(
                f"khong cham lai duoc {len(env_ids)} check can fixture: {', '.join(sorted(env_ids))} "
                "-- chay lai voi `--keep` neu can chung"
            )
        print(
            f"bo cham tat dinh tren {len(fresh)} check doc-trajectory: cham lai ra dung ket qua cu"
            if same
            else "CANH BAO: cham lai ra ket qua KHAC ket qua da luu -- bo cham khong tat dinh"
        )
        return EXIT_OK if diagnosis.verdict == "PASS" and same else EXIT_FAILED

    if record.workspace_rev and "+dirty" in record.workspace_rev:
        print(
            f"canh bao: lan chay goc dung cay lam viec ban ({record.workspace_rev}), nen khong tai "
            "lap duoc chinh xac. Lan chay moi se dung trang thai hien tai."
        )
    args.case = record.case_id
    args.dataset = ""
    return cmd_run(args)


# ── compare ─────────────────────────────────────────────────────────────────────


def _side(
    config: config_mod.Config, version: str, cases: Sequence[case_mod.Case]
) -> tuple[compare_mod.Side, list[RunRecord]]:
    wanted = {c.id for c in cases} if cases else set()
    # `only_complete`: mot lan chay dang chay hoac da no giua chung khong co diem, va dem no nhu
    # mot lan that bai la bia ra mot phep do. Do do duoc khi `matrix` in
    # `claude-opus-5/high  1 lan chay  0.0%` cho mot lan chay van dang chay.
    records = [
        r
        for r in store.list_runs(config.runs_dir, version=version, only_complete=True)
        if not wanted or r.case_id in wanted
    ]
    passed = {}
    for record in records:
        directory = store.run_dir(config.runs_dir, record.run_id)
        passed[record.run_id] = _verdict_of(directory) == "PASS"
    boundary = {c.id for c in cases if c.is_boundary}
    return compare_mod.side_of(version, records, passed, boundary), records


def cmd_compare(args: argparse.Namespace) -> int:
    config = _config(args)
    cases = case_mod.dataset(args.dataset, root=config.cases_dir) if args.dataset else []

    baseline, base_records = _side(config, args.baseline, cases)
    candidate, cand_records = _side(config, args.candidate, cases)

    if not base_records:
        print(f"khong co lan chay nao cho `{args.baseline}`", file=sys.stderr)
        return EXIT_ERROR
    if not cand_records:
        print(f"khong co lan chay nao cho `{args.candidate}`", file=sys.stderr)
        return EXIT_ERROR

    comparison = compare_mod.compare(
        baseline,
        candidate,
        cost_tolerance=args.cost_tolerance,
        latency_tolerance=args.latency_tolerance,
        min_runs=args.min_runs,
    )
    print(report.comparison_block(comparison))

    diagnoses = []
    for record in cand_records:
        raw = store.load_diagnosis(store.run_dir(config.runs_dir, record.run_id))
        if raw:
            diagnoses.append(diagnose_mod.Diagnosis(**raw))
    clusters = diagnose_mod.cluster(diagnoses, support=args.support)
    below = diagnose_mod.below_support(diagnoses, support=args.support)
    if diagnoses:
        print()
        print(report.clusters_block(clusters, below, args.support))

    return EXIT_OK if comparison.verdict == compare_mod.IMPROVED else EXIT_FAILED


# ── matrix ──────────────────────────────────────────────────────────────────────


def cmd_matrix(args: argparse.Namespace) -> int:
    """Cung mot dataset, nhieu `model/effort`, mot bang.

    Bang nay ton tai de tra loi mot cau hoi ma `compare` co y khong tra loi: chay bulk bang cau
    hinh nao. `compare` hoi "skill nay co tot len khong"; o day skill giu nguyen va cau hinh doi.
    Hai cau hoi khac nhau, va tron chung vao mot lenh la cach mot cai thien cua model duoc doc
    thanh mot cai thien cua skill.
    """
    config = _config(args)
    cases = case_mod.dataset(args.dataset, root=config.cases_dir) if args.dataset else []
    wanted = {c.id for c in cases} if cases else set()

    cells: dict[str, dict] = {}
    skipped = 0
    for record in store.list_runs(config.runs_dir, skill=args.skill or ""):
        if wanted and record.case_id not in wanted:
            continue
        if record.status != "complete":
            skipped += 1
            continue
        if record.dry and not args.include_dry:
            continue
        key = record.model_config or "(khong ghi)"
        cell = cells.setdefault(
            key, {"runs": 0, "passed": 0, "steps": 0.0, "tool_calls": 0.0, "cost": 0.0, "duration": 0.0}
        )
        cell["runs"] += 1
        cell["passed"] += 1 if _verdict_of(store.run_dir(config.runs_dir, record.run_id)) == "PASS" else 0
        cell["steps"] += record.num_steps
        cell["tool_calls"] += record.num_tool_calls
        cell["cost"] += record.cost_usd
        cell["duration"] += record.duration_ms / 1000.0

    for cell in cells.values():
        runs = cell["runs"] or 1
        cell["rate"] = cell["passed"] / runs
        for key in ("steps", "tool_calls", "cost", "duration"):
            cell[key] /= runs

    order = sorted(cells)
    print(report.matrix_block(cells, order))
    if skipped:
        print()
        print(f"bo qua {skipped} lan chay chua hoan tat hoac da no giua chung")
    thin = [k for k in order if cells[k]["runs"] < args.min_runs]
    if thin:
        print()
        print(
            f"canh bao: {', '.join(thin)} co duoi {args.min_runs} lan chay -- cac dong do chua doc "
            "duoc nhu mot phep do"
        )
    return EXIT_OK


# ── experiment ──────────────────────────────────────────────────────────────────


def cmd_experiment(args: argparse.Namespace) -> int:
    """Chay mot thi nghiem da khai bao: gia thuyet truoc, ket qua sau.

    Lenh nay khong toi uu gi va khong sinh candidate. No bat nguoi chay viet ra gia thuyet va bien
    nao doi TRUOC khi thay so, roi doi chieu thiet ke do voi identity that cua cac lan chay.
    """
    config = _config(args)
    exp = experiment_mod.load(Path(args.file))
    cases = case_mod.dataset(exp.dataset, root=config.cases_dir)

    print(report.experiment_block(exp, []))
    print()

    if not args.reuse:
        for arm in (exp.baseline, exp.candidate):
            for _ in range(exp.runs):
                for case in cases:
                    runner.execute(
                        config,
                        case,
                        model=arm.model,
                        effort=arm.effort,
                        label=arm.label,
                        dry=args.dry,
                        keep=False,
                    )
            print(f"da chay xong ben `{arm.label}`")
        print()

    baseline, base_records = _side(config, exp.baseline.label, cases)
    candidate, cand_records = _side(config, exp.candidate.label, cases)
    if not base_records or not cand_records:
        print("chua du lan chay cho ca hai ben -- bo `--reuse` de chay chung", file=sys.stderr)
        return EXIT_ERROR

    comparison = compare_mod.compare(baseline, candidate, min_runs=args.min_runs)
    problems = exp.mismatch(comparison.changed)
    if problems:
        print(report.experiment_block(exp, problems))
        print()
    print(report.comparison_block(comparison))
    return EXIT_OK if comparison.verdict == compare_mod.IMPROVED and not problems else EXIT_FAILED


# ── list / cases / skills / init ────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    config = _config(args)
    records = store.list_runs(
        config.runs_dir, case_id=args.case or "", skill=args.skill or "", limit=args.limit
    )
    verdicts = {}
    for r in records:
        # `list` co y KHONG loc lan chay chua xong -- day la cho de nhin thay chung. Chi cac bang
        # GOP moi loc, vi o do chung se bien thanh mot con so.
        verdicts[r.run_id] = (
            r.status.upper() if r.status != "complete" else _verdict_of(store.run_dir(config.runs_dir, r.run_id))
        )
    print(report.runs_table(records, verdicts))
    return EXIT_OK


def cmd_cases(args: argparse.Namespace) -> int:
    config = _config(args)
    cases = case_mod.all_cases(root=config.cases_dir)
    if not cases:
        print(f"chua co case nao duoi {config.cases_dir}")
        return EXIT_OK
    for case in cases:
        tags = f"  [{', '.join(case.tags)}]" if case.tags else ""
        canned = "  (co trace dong hop)" if runner.canned_trace_path(case) else ""
        print(f"{case.id:<32}{case.skill:<24}{len(case.checks):>3} check{tags}{canned}")
    return EXIT_OK


def cmd_skills(args: argparse.Namespace) -> int:
    config = _config(args)
    names = config.skills()
    if not names:
        print(f"khong thay skill nao duoi {config.skills_dir}")
        return EXIT_OK
    from skill_lab.model import skill_version

    for name in names:
        print(f"{name:<32}{skill_version(config.skill_dir(name))}")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Kiem tien de. Khong sua gi, khong chay actor, khong dung toi workspace."""
    config = None
    error = ""
    try:
        config = _config(args)
    except config_mod.ConfigError as exc:
        error = str(exc)
    findings = doctor.run(config, config_error=error)
    print(doctor.render(findings))
    return EXIT_OK if all(f.ok for f in findings) else EXIT_ERROR


def cmd_evaluate(args: argparse.Namespace) -> int:
    """skill -> case -> lan chay -> bao cao, trong mot lenh.

    Uu tien case da co. Chi sinh case khi chua co case nao cho skill do, va case sinh ra duoc ghi
    ra dia truoc khi chay -- de thu duoc cham la thu doc duoc, khong phai mot cau hinh trong bo nho.
    """
    workspace = args.workspace
    if args.from_git:
        target = evaluate.clone_workspace(args.from_git)
        print(f"da clone {args.from_git} -> {target}")
        # Ban clone nay la workspace, nen `cases/` va `.skill-lab/runs/` cua lan chay nam TRONG no.
        # Khong tu xoa sau khi chay: xoa la xoa chinh bang chung. Nhung mot thu muc tam ma nguoi
        # dung tuong la vinh vien cung te khong kem, nen no duoc noi ra o day.
        print(f"   case, trace va ban ghi lan chay se nam trong {target}")
        print("   day la thu muc TAM -- chep ra ngoai neu can giu, lab khong tu xoa no")
        workspace = str(target)
    config = config_mod.load(Path(workspace) if workspace else None)

    # Doctor truoc, va dung lai neu co muc HONG: moi muc hong o do deu lam lan chay sap toi tra ve
    # mot con so khong noi ve skill.
    findings = doctor.run(config)
    broken = [f for f in findings if not f.ok]
    if broken:
        print(doctor.render(findings))
        return EXIT_ERROR
    print(f"tien de: dat ({len(findings)} muc)")

    doc = evaluate.read_skill(config, args.skill)
    cases = evaluate.existing_cases(config, args.skill)
    if cases and not args.new_case:
        print(f"dung {len(cases)} case da co cho `{args.skill}`: {', '.join(c.id for c in cases)}")
    else:
        if not args.task:
            print(evaluate.task_hint(doc), file=sys.stderr)
            return EXIT_ERROR
        path = evaluate.write_case(config, doc, args.task, overwrite=args.new_case)
        print(f"case: {path}")
        cases = [case_mod.load(path)]

    args.label = ""
    args.keep = False
    args.judge = False
    args.effort = ""
    args.step = False
    return _run_cases(config, cases, args)


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.workspace) if args.workspace else Path.cwd()
    target = root / config_mod.CONFIG_NAME
    if target.exists() and not args.force:
        print(f"{target} da ton tai; dung --force de ghi de", file=sys.stderr)
        return EXIT_ERROR
    target.write_text(STARTER_CONFIG.format(id=root.name), encoding="utf-8")
    (root / "cases").mkdir(exist_ok=True)
    print(f"da tao {target}")
    print(f"da tao {root / 'cases'}")
    return EXIT_OK


# ── parser ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill-lab", description="Phong thi nghiem cho Agent Skill.")
    parser.add_argument("--workspace", default="", help="goc workspace (mac dinh: tu tim len tren)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="chay mot case hoac mot dataset")
    run.add_argument("case", nargs="?", default="", help="id cua case")
    run.add_argument("--dataset", default="", help="thu muc, tag hoac ten skill")
    run.add_argument("--model", default="", help="de ghi de model cua actor")
    run.add_argument(
        "--effort",
        default="",
        help="muc effort cua phien actor; cung model o hai muc effort la hai cau hinh khac nhau",
    )
    run.add_argument("--label", default="", help="ten phien ban cho lan chay nay, vi du 1.8.3-candidate")
    run.add_argument("--dry", action="store_true", help="phat lai trace dong hop; khong goi model")
    run.add_argument("--keep", action="store_true", help="giu fixture lai trong thu muc lan chay")
    run.add_argument("--step", action="store_true", help="in tung dong trace ngay khi no roi xuong")
    run.add_argument("--judge", action="store_true", help="hoi them cac cau judge; day la mot lan goi model that")
    run.set_defaults(func=cmd_run)

    debug = sub.add_parser("debug", help="buoc sai dau tien, phan loai, bang chung")
    debug.add_argument("run_id")
    debug.add_argument("--limit", type=int, default=0, help="cat trajectory sau N buoc")
    debug.add_argument("--output", action="store_true", help="in ca dau ra cuoi cung cua actor")
    debug.set_defaults(func=cmd_debug)

    replay = sub.add_parser("replay", help="chay lai mot case, hoac cham lai trajectory da luu")
    replay.add_argument("run_id")
    replay.add_argument("--rescore", action="store_true", help="cham lai, khong goi model, mien phi")
    replay.add_argument("--model", default="")
    replay.add_argument("--effort", default="")
    replay.add_argument("--label", default="")
    replay.add_argument("--keep", action="store_true")
    replay.add_argument("--step", action="store_true")
    replay.add_argument("--judge", action="store_true")
    replay.set_defaults(func=cmd_replay, dry=False)

    cmp_ = sub.add_parser("compare", help="baseline vs candidate, kem cac cua regression")
    cmp_.add_argument("baseline", help="skill_version hoac --label cua ben nen")
    cmp_.add_argument("candidate")
    cmp_.add_argument("--dataset", default="", help="gioi han o mot tap case")
    cmp_.add_argument("--cost-tolerance", type=float, default=compare_mod.DEFAULT_COST_TOLERANCE)
    cmp_.add_argument("--latency-tolerance", type=float, default=compare_mod.DEFAULT_LATENCY_TOLERANCE)
    cmp_.add_argument("--support", type=int, default=2, help="so lan chay toi thieu de mot cum duoc bao cao")
    cmp_.add_argument(
        "--min-runs",
        type=int,
        default=compare_mod.DEFAULT_MIN_RUNS,
        help="so lan chay toi thieu moi ben truoc khi mot hieu duoc doc nhu tin hieu",
    )
    cmp_.set_defaults(func=cmd_compare)

    listing = sub.add_parser("list", help="cac lan chay da luu")
    listing.add_argument("--case", default="")
    listing.add_argument("--skill", default="")
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=cmd_list)

    cases = sub.add_parser("cases", help="cac case co trong workspace")
    cases.set_defaults(func=cmd_cases)

    skills = sub.add_parser("skills", help="cac skill co trong workspace, kem hash phien ban")
    skills.set_defaults(func=cmd_skills)

    matrix = sub.add_parser("matrix", help="cung dataset, nhieu model/effort, mot bang")
    matrix.add_argument("--dataset", default="")
    matrix.add_argument("--skill", default="")
    matrix.add_argument("--min-runs", type=int, default=compare_mod.DEFAULT_MIN_RUNS)
    matrix.add_argument(
        "--include-dry",
        action="store_true",
        help="tinh ca lan chay `--dry`; mac dinh loai vi chung khong goi model nao",
    )
    matrix.set_defaults(func=cmd_matrix)

    exp = sub.add_parser("experiment", help="chay mot thi nghiem da khai bao trong YAML")
    exp.add_argument("file")
    exp.add_argument("--reuse", action="store_true", help="dung lan chay da co thay vi chay moi")
    exp.add_argument("--dry", action="store_true")
    exp.add_argument("--min-runs", type=int, default=compare_mod.DEFAULT_MIN_RUNS)
    exp.set_defaults(func=cmd_experiment)

    doctor_p = sub.add_parser("doctor", help="kiem moi tien de mot lan chay can; khong sua gi")
    doctor_p.set_defaults(func=cmd_doctor)

    ev = sub.add_parser(
        "evaluate",
        help="skill -> case -> lan chay -> bao cao, trong mot lenh",
    )
    ev.add_argument("skill", help="ten skill (thu muc duoi `workspace.skills`)")
    ev.add_argument(
        "--task",
        default="",
        help="viec can lam, viet nhu nguoi dung se go. Bat buoc khi chua co case nao cho skill nay "
        "-- bo do khong doan task tu mo ta skill",
    )
    ev.add_argument(
        "--from-git",
        default="",
        help="URL git cua workspace can do; shallow-clone roi do trong ban clone do",
    )
    ev.add_argument(
        "--new-case",
        action="store_true",
        help="sinh lai case smoke va ghi de, thay vi dung case da co",
    )
    ev.add_argument("--model", default="", help="de ghi de model cua actor")
    ev.add_argument("--dry", action="store_true", help="phat lai trace dong hop; khong goi model")
    ev.set_defaults(func=cmd_evaluate)

    init = sub.add_parser("init", help="tao skill-lab.yaml cho workspace nay")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return args.func(args)
    except (
        config_mod.ConfigError,
        case_mod.CaseError,
        store.StoreError,
        runner.RunnerError,
        experiment_mod.ExperimentError,
        # Cung nhom voi cac loi tren: mot ten skill go sai hay mot URL git hong la loi dau vao,
        # khong phai mot su co. Thieu dong nay thi `evaluate <ten-sai>` in ra traceback va thoat
        # voi ma 1 -- dung ma nghia la "skill do", tuc bao cao mot that bai cua skill cho mot
        # loi danh may.
        evaluate.EvaluateError,
    ) as exc:
        print(f"loi: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
