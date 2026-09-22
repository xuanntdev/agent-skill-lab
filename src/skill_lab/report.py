"""In ket qua ra terminal. Khong mau me, va khong bao gio noi hon nhung gi du lieu noi.

Mot quy tac chay xuyen file nay: **trang thai ket thuc duoc noi TRUOC bang tieu chi.** Mot lan
chay dat 4/6 khi da chay xong va mot lan chay dat 4/6 khi bi cat ngang la hai con vat khac nhau,
va bang tieu chi tu no khong phan biet duoc. Doc con so truoc khi biet dieu do la doc sai.
"""

from __future__ import annotations

from typing import Sequence

from skill_lab import diagnose as diagnose_mod
from skill_lab import model as model_mod
from skill_lab import taxonomy
from skill_lab.compare import Comparison
from skill_lab.diagnose import Cluster, Diagnosis
from skill_lab.model import CheckResult, RunRecord, Step, call_steps

#: Trang thai may -> nhan nguoi doc. Sau trang thai, sau nhan: gop `WEAK_EVIDENCE` vao `XANH` hay
#: gop `NOT_EVALUATED` vao `DO` la dung cho mot bao cao bat dau noi doi mot cach le phep.
MARKS = {
    model_mod.PASS: "XANH",
    model_mod.FAIL: "DO",
    model_mod.WEAK_EVIDENCE: "BANG CHUNG YEU",
    model_mod.NOT_APPLICABLE: "KHONG AP DUNG",
    model_mod.UNDECIDED: "CHUA CHAM",
    model_mod.NOT_EVALUATED: "KHONG DO DUOC",
}
MARK_WIDTH = max(len(v) for v in MARKS.values())

NEWLINE = chr(10)


def _mark(check: CheckResult) -> str:
    return MARKS.get(check.status, check.status)


def run_header(record: RunRecord) -> str:
    lines = [
        f"run      {record.run_id}",
        f"case     {record.case_id}",
        f"skill    {record.version_label}",
        f"model    {record.model}",
        f"fixture  {record.fixture}" + (f" @ {record.workspace_rev}" if record.workspace_rev else ""),
    ]
    return "\n".join(lines)


def run_status(record: RunRecord) -> str:
    if record.completed:
        if record.num_tool_calls == 0:
            # Dong nay phai to hon mot con so 0 trong ngoac. Truoc khi co no, mot lan chay khong
            # ghi duoc gi doc y het mot lan chay sach se, va cai dap vao mat nguoi doc la bang
            # check ben duoi -- ma bang do luc ay toan mau xanh.
            return (
                "actor: ket thuc binh thuong nhung KHONG GHI DUOC TOOL CALL NAO. "
                "Moi check doc tu trajectory deu khong cham duoc -- xem chan doan."
            )
        return f"actor: ket thuc binh thuong ({record.num_tool_calls} tool call duoc ghi)"
    return (
        f"actor: KHONG HOAN TAT -- exit {record.exit_code}, {record.num_tool_calls} tool call duoc ghi. "
        "Bang duoi cham xem no di duoc toi dau, khong phai cham mot lan chay tron ven."
    )


def metrics(record: RunRecord) -> str:
    seconds = record.duration_ms / 1000.0
    return (
        f"buoc {record.num_tool_calls}  |  turn {record.num_turns}  |  "
        f"chi phi {record.cost_usd:.4f} USD  |  thoi gian {seconds:.1f}s"
    )


def checks_table(checks: Sequence[CheckResult]) -> str:
    if not checks:
        return "  (case nay khong khai check nao)"
    width = max(len(c.id) for c in checks)
    lines = []
    for check in checks:
        tag = "" if check.deterministic else " (judge)"
        lines.append(f"  [{_mark(check):<{MARK_WIDTH}}] {check.id:<{width}}{tag}  {check.why}")
    return "\n".join(lines)


def score_line(checks: Sequence[CheckResult]) -> str:
    """Diem, cong so check KHONG vao duoc diem -- va dem chung rieng.

    Gop "chua cham duoc" vao mau sau la cach mot bang mat nghia: 8/8 tren mot case co ba check
    khong do duoc khong phai 8/8, va nguoi doc phai thay duoc dieu do o cung mot dong.
    """
    decided = [c for c in checks if not c.undecided]
    passed = sum(1 for c in decided if c.passed)
    weak = sum(1 for c in checks if c.status == model_mod.WEAK_EVIDENCE)
    unevaluated = sum(1 for c in checks if c.status == model_mod.NOT_EVALUATED)
    undecided = sum(1 for c in checks if c.status == model_mod.UNDECIDED)
    tail = ""
    for count, label in ((weak, "bang chung yeu"), (unevaluated, "khong do duoc"), (undecided, "chua cham")):
        if count:
            tail += f", {count} {label}"
    return f"diem: {passed}/{len(decided)} check tat dinh xanh{tail}"


def diagnosis_block(diag: Diagnosis) -> str:
    if diag.verdict == "PASS":
        lines = [f"chan doan: {diag.summary} (do tin cay: {diag.confidence})"]
        if diag.weak_evidence:
            lines.append(f"  bang chung yeu      {', '.join(diag.weak_evidence)}")
        if diag.undecided:
            lines.append(f"  chua cham duoc      {', '.join(diag.undecided)}")
        return "\n".join(lines)
    if diag.verdict == diagnose_mod.NO_EVIDENCE:
        # Khong in "buoc sai dau tien": khong co buoc nao ca, va in mot dong trong o do se moi
        # nguoi doc di tim mot buoc khong ton tai.
        lines = [f"chan doan: {diag.summary}"]
        lines.append(f"  phan loai           {diag.category} -- {taxonomy.describe(diag.category)}")
        lines.append(f"  ai phai sua         {diag.owner} (do tin cay: {diag.confidence})")
        for item in diag.evidence:
            lines.append(f"    - {item}")
        if diag.hypothesis:
            lines.append(f"  gia thuyet          {diag.hypothesis}")
        if diag.suggestion:
            lines.append(f"  huong sua           {diag.suggestion}")
        if diag.undecided:
            lines.append(f"  chua cham duoc      {', '.join(diag.undecided)}")
        return "\n".join(lines)

    lines = ["chan doan:"]
    if diag.first_error_step is not None:
        lines.append(f"  buoc sai dau tien   {diag.first_error_step}  (check `{diag.first_error_check}`)")
        lines.append(f"  anh huong ve sau    {diag.downstream_steps} buoc sau do khong con dang tin")
    else:
        lines.append(f"  buoc sai dau tien   khong neo duoc vao buoc nao (check `{diag.first_error_check}`)")
    lines.append(f"  phan loai           {diag.category} -- {taxonomy.describe(diag.category)}")
    lines.append(f"  ai phai sua         {diag.owner}")
    lines.append(f"  do tin cay          {diag.confidence}")
    if diag.reattributed_from:
        lines.append(
            f"  da doi chu so huu   tu `{diag.reattributed_from}` sang `{diag.category}` vi trace noi khac"
        )
    if diag.evidence:
        lines.append("  bang chung")
        for item in diag.evidence:
            lines.append(f"    - {item}")
    if diag.summary:
        lines.append(f"  doc the nao         {diag.summary}")
    if diag.suggestion:
        lines.append(f"  huong sua           {diag.suggestion}")
    if diag.undecided:
        lines.append(f"  chua cham duoc      {', '.join(diag.undecided)}")
    return "\n".join(lines)


def trajectory_block(steps: Sequence[Step], *, mark: int | None = None, limit: int = 0) -> str:
    calls = call_steps(steps)
    if limit:
        calls = calls[:limit]
    lines = []
    for step in calls:
        pointer = ">>" if mark is not None and step.index == mark else "  "
        actor = "" if step.actor == "main" else f" [{step.actor}]"
        payload = step.command or ", ".join(step.paths)
        lines.append(f"{pointer} {step.index:>3}  {step.tool:<12}{actor} {payload[:110]}")
    return "\n".join(lines) or "  (trace rong -- actor khong goi tool nao)"


def clusters_block(clusters: Sequence[Cluster], below: Sequence[tuple[str, int]], support: int) -> str:
    lines = [f"cum that bai (nguong ho tro: {support} lan chay)"]
    if not clusters:
        lines.append("  khong cum nao dat nguong -- chua du bang chung de sua than skill")
    for cluster in clusters:
        lines.append(f"  {cluster.category}  x{cluster.count}  -> sua o: {cluster.owner}")
        for item in cluster.sample_evidence[:3]:
            lines.append(f"      {item}")
        if cluster.suggestion:
            lines.append(f"      huong sua: {cluster.suggestion}")
    if below:
        listed = ", ".join(f"{label} x{count}" for label, count in below)
        lines.append(f"  duoi nguong (chua hanh dong theo): {listed}")
    return "\n".join(lines)


def comparison_block(comparison: Comparison) -> str:
    base, cand = comparison.baseline, comparison.candidate
    lines = [
        f"phep so nay do: {comparison.subject}",
    ]
    if comparison.changed:
        lines.append("bien da doi:")
        for name, (left, right) in comparison.changed.items():
            lines.append(f"  {name:<20}{left or '-'}  ->  {right or '-'}")
    fixed = [f for f in comparison.baseline.identity if f not in comparison.changed]
    if fixed:
        lines.append(f"bien giu nguyen: {', '.join(fixed)}")
    lines += [
        "",
        f"{'':<22}{base.label:>18}{cand.label:>18}",
        f"{'ty le xanh':<22}{base.rate:>17.1%}{cand.rate:>18.1%}",
        f"{'so lan chay':<22}{base.runs:>18}{cand.runs:>18}",
        f"{'chi phi tb (USD)':<22}{base.mean('cost_usd'):>18.4f}{cand.mean('cost_usd'):>18.4f}",
        f"{'thoi gian tb (s)':<22}{base.mean('duration_ms') / 1000:>18.1f}{cand.mean('duration_ms') / 1000:>18.1f}",
        f"{'tool call tb':<22}{base.mean('tool_calls'):>18.1f}{cand.mean('tool_calls'):>18.1f}",
        "",
        f"case chung: {comparison.shared_cases}  |  nguong nhieu: ±{comparison.noise_threshold:.1%}",
    ]
    regressions = [d for d in comparison.deltas if d.regressed]
    improvements = [d for d in comparison.deltas if d.delta > 0]
    if improvements:
        lines.append("tot len:")
        for d in improvements:
            lines.append(f"  + {d.case_id:<32}{d.baseline_rate:.0%} -> {d.candidate_rate:.0%}")
    if regressions:
        lines.append("di lui:")
        for d in regressions:
            tag = "  [NANG]" if d.critical else ("  [BIEN]" if d.boundary else "")
            lines.append(f"  - {d.case_id:<32}{d.baseline_rate:.0%} -> {d.candidate_rate:.0%}{tag}")
    if not improvements and not regressions:
        lines.append("khong case nao doi ket qua")
    lines.append("")
    lines.append(f"ket luan: {comparison.verdict}")
    for reason in comparison.reasons:
        lines.append(f"  - {reason}")
    lines.append("")
    lines.append(
        "Khong ket luan nao o day la mot quyet dinh promote. `IMPROVED` noi rang do do da tang va "
        "khong co gi di lui; no khong noi rang nen trien khai."
    )
    return "\n".join(lines)


def runs_table(records: Sequence[RunRecord], verdicts: dict[str, str]) -> str:
    if not records:
        return "chua co lan chay nao"
    lines = [f"{'run':<36}{'case':<26}{'skill':<28}{'ket qua':<10}{'USD':>8}"]
    for record in records:
        verdict = verdicts.get(record.run_id, "?")
        lines.append(
            f"{record.run_id:<36}{record.case_id:<26}{record.version_label:<28}{verdict:<10}{record.cost_usd:>8.4f}"
        )
    return "\n".join(lines)


def matrix_block(cells: dict, order: list) -> str:
    """Bang model matrix: mot dong moi `model/effort`, tren cung mot dataset.

    Cot `ket qua` la ty le xanh, va no cot y dung canh chi phi va thoi gian chu khong dung mot
    minh: cau hoi that su khi chon cau hinh khong phai "cau hinh nao dat diem cao nhat" ma la
    "cau hinh nao dat du diem voi cai gia chap nhan duoc".
    """
    if not cells:
        return "chua co lan chay nao de dung bang"
    width = max(len(k) for k in order)
    lines = [
        f"{'cau hinh':<{width}}{'lan chay':>10}{'ty le xanh':>12}{'buoc tb':>10}"
        f"{'tool call':>11}{'USD tb':>10}{'giay tb':>10}"
    ]
    for key in order:
        c = cells[key]
        lines.append(
            f"{key:<{width}}{c['runs']:>10}{c['rate']:>11.1%}{c['steps']:>10.1f}"
            f"{c['tool_calls']:>11.1f}{c['cost']:>10.4f}{c['duration']:>10.1f}"
        )
    return NEWLINE.join(lines)


def experiment_block(exp, problems: list) -> str:
    lines = [
        f"thi nghiem   {exp.id}",
        f"gia thuyet   {exp.hypothesis.strip()}",
        f"dataset      {exp.dataset}",
        f"baseline     {exp.baseline.label}" + (f" ({exp.baseline.model or '-'}/{exp.baseline.effort or '-'})" if exp.baseline.model or exp.baseline.effort else ""),
        f"candidate    {exp.candidate.label}" + (f" ({exp.candidate.model or '-'}/{exp.candidate.effort or '-'})" if exp.candidate.model or exp.candidate.effort else ""),
        f"khai la doi  {', '.join(exp.changed) or '-'}",
        f"khai la giu  {', '.join(exp.fixed) or '-'}",
    ]
    if problems:
        lines.append("")
        lines.append("thiet ke khong khop voi thuc te:")
        for item in problems:
            lines.append(f"  - {item}")
        lines.append(
            "  Mot thi nghiem chay khac voi thiet ke cua no van cho ra so, va nhung so do tra loi "
            "mot cau hoi khac voi cau da dat."
        )
    return NEWLINE.join(lines)


def gates_block(results, mutated=()) -> str:
    """Bang gate preservation. In ca gate DAT, khong chi gate hong.

    Mot bao cao chi liet ke cai hong khong noi duoc pham vi da kiem, va "hai gate dat, mot hong"
    la mot tinh huong khac han "mot gate hong, khong kiem gi them".
    """
    lines = ["Gate preservation"]
    for r in results:
        mark = "OK  " if r.ok else "HONG"
        lines.append(f"  [{mark}] {r.spec.label}")
        lines.append(f"         mong doi exit: {r.spec.expected_exit}")
        lines.append(f"         thuc te exit:  {r.actual_exit}")
        if r.summary:
            lines.append(f"         ket qua:       {r.summary}")
    if mutated:
        lines.append("")
        lines.append("  Gate assertion da SUA fixture -- assertion chi duoc phep quan sat:")
        for item in mutated:
            lines.append(f"    - {item}")
    return NEWLINE.join(lines)
