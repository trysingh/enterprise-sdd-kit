"""Open-questions register: list, CSV export for stakeholders, CSV import of answers."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .project import EkitError, dump_yaml, load_yaml

COLUMNS = ["id", "blocking", "status", "owner", "affects", "question", "context", "options",
           "answer", "answered_by", "answered_on"]
EDITABLE = {"answer", "answered_by", "answered_on", "status"}


def _file(prd_dir: Path) -> Path:
    f = prd_dir / "open-questions.yaml"
    if not f.is_file():
        raise EkitError(f"No open-questions.yaml in {prd_dir}")
    return f


def list_questions(prd_dir: Path, status: str | None = None) -> list[dict]:
    data = load_yaml(_file(prd_dir)) or {}
    qs = data.get("questions") or []
    if status:
        qs = [q for q in qs if q.get("status") == status]
    return sorted(qs, key=lambda q: (not q.get("blocking"), str(q.get("id"))))


def export_csv(prd_dir: Path, out: Path, only_open: bool = True) -> int:
    qs = list_questions(prd_dir)
    if only_open:
        qs = [q for q in qs if q.get("status") in ("open", "deferred")]
    out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows opens it with the right encoding
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for q in qs:
            row = {c: q.get(c) for c in COLUMNS}
            row["affects"] = ", ".join(q.get("affects") or [])
            row["options"] = " | ".join(q.get("options") or [])
            row["blocking"] = "yes" if q.get("blocking") else "no"
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return len(qs)


def import_csv(prd_dir: Path, src: Path) -> list[str]:
    f = _file(prd_dir)
    data = load_yaml(f) or {}
    by_id = {q.get("id"): q for q in data.get("questions") or []}
    changed = []
    with src.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            qid = (row.get("id") or "").strip()
            if qid not in by_id:
                raise EkitError(f"CSV row with unknown question id '{qid}' — refusing partial import.")
            answer = (row.get("answer") or "").strip()
            if not answer:
                continue
            q = by_id[qid]
            q["answer"] = answer
            q["answered_by"] = (row.get("answered_by") or "").strip() or q.get("answered_by")
            q["answered_on"] = (row.get("answered_on") or "").strip() or dt.date.today().isoformat()
            status = (row.get("status") or "").strip().lower()
            q["status"] = status if status in ("answered", "deferred", "withdrawn") else "answered"
            changed.append(qid)
    if changed:
        dump_yaml(data, f)
    return changed
