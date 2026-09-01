"""Parses uploaded dataset files (JSONL or CSV) into dataset records.

Kept separate from the router so the parsing logic — the part with actual
edge cases (malformed lines, missing columns, encoding) — is unit-testable
without spinning up the ASGI app.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    question: str
    context: str = ""
    expected_answer: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class DatasetImportError(ValueError):
    """Raised for a malformed upload — the router translates this to 400."""


_KNOWN_FIELDS = {"question", "context", "expected_answer"}


def parse_jsonl(content: str) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetImportError(f"line {line_number}: invalid JSON ({exc.msg})") from exc
        if not isinstance(data, dict) or "question" not in data:
            raise DatasetImportError(f"line {line_number}: missing required 'question' field")
        records.append(
            ParsedRecord(
                question=str(data["question"]),
                context=str(data.get("context", "")),
                expected_answer=str(data.get("expected_answer", "")),
                metadata=data.get("metadata")
                or {k: v for k, v in data.items() if k not in _KNOWN_FIELDS},
            )
        )
    return records


def parse_csv(content: str) -> list[ParsedRecord]:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None or "question" not in reader.fieldnames:
        raise DatasetImportError("CSV must have a 'question' column")

    records: list[ParsedRecord] = []
    for row_number, row in enumerate(reader, start=2):  # header is row 1
        question = (row.get("question") or "").strip()
        if not question:
            raise DatasetImportError(f"row {row_number}: 'question' is required")
        extra = {k: v for k, v in row.items() if k not in _KNOWN_FIELDS and v}
        records.append(
            ParsedRecord(
                question=question,
                context=(row.get("context") or "").strip(),
                expected_answer=(row.get("expected_answer") or "").strip(),
                metadata=extra,
            )
        )
    return records


def parse_dataset_file(filename: str, content: str) -> list[ParsedRecord]:
    lowered = filename.lower()
    if lowered.endswith(".jsonl") or lowered.endswith(".ndjson"):
        records = parse_jsonl(content)
    elif lowered.endswith(".csv"):
        records = parse_csv(content)
    else:
        raise DatasetImportError(f"unsupported file type '{filename}' — expected .jsonl or .csv")

    if not records:
        raise DatasetImportError("no records found in uploaded file")
    return records
