"""Lan chay ben vung: no nam o dau, trong no co gi, va doc lai the nao.

**Mot thu muc mot lan chay, va trace tho duoc giu canh trace da doc.** `trace.jsonl` la dau ra cua
hook, tung byte; `trajectory.jsonl` la cach package nay doc no. Giu ca hai ton vai kilobyte va mua
duoc tinh chat duy nhat lam cho mot chan doan co the tranh luan duoc: moi cau `debug` in ra deu
lan nguoc ve duoc mot dong ma mot hook nao do da ghi truoc khi bat ky ai co y kien ve no. Mot kho
chi giu phan da doc thi dang de nghi duoc tin.

**Lan chay khong vao git.** Chung la hien vat sinh ra tu mot lenh, va chung nang. Case thi nguoc
lai -- case la thu duoc version-control, va no song o `cases/`. `case.yaml` duoc chep vao trong
lan chay de mot ban ghi con doc duoc sau khi case cua no da bi sua; thieu buoc do, mot lan chay
sau sau tuan se bi doc theo mot rubric ma no chua bao gio thay.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from skill_lab import trace as trace_mod
from skill_lab.model import CheckResult, RunRecord, Step, build_trajectory

RUN_JSON = "run.json"
TRACE_JSONL = "trace.jsonl"
TRAJECTORY_JSONL = "trajectory.jsonl"
EVALUATION_JSON = "evaluation.json"
DIAGNOSIS_JSON = "diagnosis.json"
CASE_SNAPSHOT = "case.yaml"
GATES_JSON = "gates.json"
FIXTURE_DIR = "fixture"


class StoreError(Exception):
    """Thu muc lan chay khong co, khong ro, hoac khong dung hinh dang module nay ghi."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-").lower() or "run"


def new_run_id(case_id: str, *, now: datetime | None = None) -> str:
    """`20260921T101500Z-<case>-<8 ky tu>`: sap xep theo chu cai ra dung thu tu thoi gian.

    Tam ky tu cuoi khong phai trang tri, va con so 8 la ket qua cua hai lan do.

    Lan mot: khong co hau to nao ca. Mot lan chay `--dry` mat chua toi mot giay, nen chay cung mot
    case hai lan lien tiep -- dung thu ma mot bo so sanh doi hoi -- cho ra hai id trung nhau. Phat
    hien bang cach tao 10 lan chay roi dem duoc 7.

    Lan hai: bon ky tu. Khong gian 65 536 nghe nhu du, nhung cau hoi dung khong phai "hai id co
    trung khong" ma la nghich ly ngay sinh -- voi 50 lan rut, xac suat co mot cap trung la gan 2%,
    va mot bo so sanh chay hang tram lan se gap no. Tam ky tu dua con so do xuong khong dang ke.
    `create` van tu choi ghi de, vi "khong dang ke" khong phai "khong the".
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_slug(case_id)}-{uuid4().hex[:8]}"


def run_dir(root: Path, run_id: str) -> Path:
    return root / run_id


def resolve(root: Path, run_id: str) -> Path:
    """Mot run id day du, hoac bat ky doan nao cua no ma khong nhap nhang.

    Go 32 ky tu de xem lai lan chay vua tao chin muoi giay truoc la loai ma sat lam nguoi ta thoi
    dung cong cu. Mot doan nhap nhang thi bao loi chu khong lay cai moi nhat: doan xem nguoi kia
    y ai la cach mot so sanh trich dan nham lan chay.
    """
    exact = root / run_id
    if exact.is_dir():
        return exact
    if not root.is_dir():
        raise StoreError(f"chua co lan chay nao duoi {root}")
    matches = sorted(p for p in root.iterdir() if p.is_dir() and run_id in p.name)
    if not matches:
        raise StoreError(f"khong co lan chay nao khop '{run_id}' trong {root}")
    if len(matches) > 1:
        raise StoreError(f"'{run_id}' khop nhieu lan chay: {', '.join(p.name for p in matches)}")
    return matches[0]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create(root: Path, record: RunRecord) -> Path:
    """Tao thu muc cho mot lan chay moi, va **tu choi de len mot lan chay da co**.

    Mot id trung nhau la chuyen hiem; ghi de trong im lang khi no xay ra thi khong. Hau qua khong
    phai mat mot ban ghi, ma la mot bo so sanh doc it lan chay hon so lan da chay va khong co gi
    trong bao cao noi rang no dang thieu.
    """
    directory = run_dir(root, record.run_id)
    if (directory / RUN_JSON).is_file():
        raise StoreError(f"lan chay {record.run_id} da ton tai -- tu choi ghi de")
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / RUN_JSON, record.to_dict())
    return directory


def save_record(directory: Path, record: RunRecord) -> None:
    _write_json(directory / RUN_JSON, record.to_dict())


def load_record(directory: Path) -> RunRecord:
    path = directory / RUN_JSON
    if not path.is_file():
        raise StoreError(f"{directory.name} khong co {RUN_JSON} -- khong phai mot lan chay hop le")
    return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def capture_trace(directory: Path, trace_path: Path) -> list[Step]:
    """Chep file cua hook vao nguyen van, roi ghi canh no cach package nay doc no.

    Chep ca khi trace rong. Mot `trace.jsonl` rong tu no la mot phat hien -- actor chua tung goi
    mot tool nao, hoac `SKILL_LAB_TRACE` khong toi duoc no -- va mot file vang mat thi khong phan
    biet duoc voi mot lan chay chua he duoc trace.
    """
    directory.mkdir(parents=True, exist_ok=True)
    raw = trace_path.read_text(encoding="utf-8") if trace_path.is_file() else ""
    (directory / TRACE_JSONL).write_text(raw, encoding="utf-8")
    steps = build_trajectory(trace_mod.parse(raw.splitlines()))
    with (directory / TRAJECTORY_JSONL).open("w", encoding="utf-8") as fh:
        for step in steps:
            fh.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")
    return steps


def load_trajectory(directory: Path) -> list[Step]:
    path = directory / TRAJECTORY_JSONL
    if not path.is_file():
        return []
    return [
        Step.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def save_evaluation(
    directory: Path, results: Iterable[CheckResult], *, judge: dict | None = None
) -> None:
    payload: dict[str, Any] = {"checks": [r.to_dict() for r in results]}
    if judge:
        payload["judge"] = judge
    _write_json(directory / EVALUATION_JSON, payload)


def load_evaluation(directory: Path) -> dict[str, Any]:
    path = directory / EVALUATION_JSON
    if not path.is_file():
        return {"checks": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_checks(directory: Path) -> list[CheckResult]:
    return [CheckResult(**c) for c in load_evaluation(directory).get("checks", [])]


def save_diagnosis(directory: Path, diagnosis: Any) -> None:
    _write_json(directory / DIAGNOSIS_JSON, asdict(diagnosis) if is_dataclass(diagnosis) else diagnosis)


def load_diagnosis(directory: Path) -> dict[str, Any]:
    path = directory / DIAGNOSIS_JSON
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_gates(directory: Path, results: Iterable[Any], *, mutated: Iterable[str] = ()) -> None:
    """Ket qua gate duoc luu ngay ca (va nhat la) khi fixture bi tu choi.

    Mot lan chay bi chan truoc khi actor khoi dong van la mot lan chay da hoc duoc dieu gi do -- no
    hoc rang moi truong khong con dung. Vut ket qua do di la bat nguoi dung chay lai chi de doc lai
    cung mot thong bao.
    """
    payload = {
        "gates": [
            {
                "name": r.spec.label,
                "command": list(r.spec.command),
                "expected_exit": r.spec.expected_exit,
                "actual_exit": r.actual_exit,
                "ok": r.ok,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "error": r.error,
            }
            for r in results
        ],
        "mutated": list(mutated),
    }
    _write_json(directory / GATES_JSON, payload)


def load_gates(directory: Path) -> dict[str, Any]:
    path = directory / GATES_JSON
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_case(directory: Path, case_path: Path | None) -> None:
    if case_path and case_path.is_file():
        shutil.copy2(case_path, directory / CASE_SNAPSHOT)


def keep_fixture(directory: Path, fixture_root: Path) -> Path:
    """Chuyen fixture vao trong lan chay, de `--keep` de lai mot thu de xem chu khong phai hai.

    Chuyen chu khong chep: `finally` cua runner xoa bat cu thu gi con o duong tam, va voi mot ban
    chep thi dung nhung byte ma lan chay that su da ghi lai la thu bi xoa.
    """
    dest = directory / FIXTURE_DIR
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(fixture_root), str(dest))
    return dest


def list_runs(
    root: Path,
    *,
    case_id: str = "",
    skill: str = "",
    version: str = "",
    limit: int = 0,
    only_complete: bool = False,
) -> list[RunRecord]:
    """Moi nhat o cuoi, vi terminal cuon xuong va lan chay nguoi ta muon xem gan nhu luon la lan
    gan day nhat."""
    if not root.is_dir():
        return []
    records = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        try:
            record = load_record(directory)
        except (StoreError, json.JSONDecodeError):
            continue
        if case_id and record.case_id != case_id:
            continue
        if skill and record.skill != skill:
            continue
        if version and version not in (record.skill_version, record.label, record.version_label):
            continue
        if only_complete and record.status != "complete":
            continue
        records.append(record)
    return records[-limit:] if limit else records
