"""Log reading, scrubbing pipeline, sampling and annotation files."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import random
import tempfile
import unicodedata
import warnings
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any

from .detectors import compile_patterns, find_pii, scrub_texts
from .errors import GoldenSetError

logger = logging.getLogger(__name__)

DEFAULT_MAX_LINE_BYTES = 1_048_576
DEFAULT_MAX_RECORDS = 1_000_000

_ID_LENGTH = 12
_UNKNOWN_STRATUM = "unknown"
_DRAIN_CHUNK = 65_536
_ANNOTATION_KEYS = ("expected", "label")
# Seeded, reproducible sampling; this is not a security-sensitive use of randomness.
_RNG_FACTORY = random.Random


@dataclass(frozen=True)
class LogRecord:
    """One log entry.

    Attributes:
        id: Stable identifier of the case.
        input: The (scrubbed) input text.
        output: The (scrubbed) output text, if any.
        stratum: Value of the stratification field, if any.
    """

    id: str
    input: str
    output: str | None = None
    stratum: str | None = None


@dataclass(frozen=True)
class ReadResult:
    """Records kept by :func:`read_logs` plus the counts of everything skipped."""

    records: tuple[LogRecord, ...]
    skipped_invalid: int
    skipped_oversize: int
    duplicates: int


@dataclass(frozen=True)
class BuildResult:
    """Summary of a :func:`build` run."""

    written: int
    skipped_invalid: int
    skipped_oversize: int
    duplicates: int


def scrub(record: LogRecord, extra_patterns: Mapping[str, str] | None = None) -> LogRecord:
    """Replace personal data in a record by typed placeholders such as ``<EMAIL_1>``.

    Input, output and stratum share one numbering, so equal values get equal placeholders.
    Fields are truncated to 20_000 characters before matching.

    Raises:
        GoldenSetError: with code ``invalid_pattern`` if a custom pattern is invalid.
    """
    patterns = compile_patterns(extra_patterns)
    text, output, stratum = scrub_texts([record.input, record.output, record.stratum], patterns)
    return replace(record, input=text or "", output=output, stratum=stratum)


def _require_positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GoldenSetError("input_invalid", f"{name} must be a positive integer")


def _drain(handle: IO[bytes]) -> None:
    """Discard the rest of the current line without buffering it."""
    while True:
        rest = handle.readline(_DRAIN_CHUNK)
        if not rest or rest.endswith(b"\n"):
            return


def _iter_lines(path: Path, max_line_bytes: int) -> Iterator[bytes | None]:
    """Yield line bodies, or ``None`` for lines longer than ``max_line_bytes``."""
    limit = max_line_bytes + 2
    with path.open("rb") as handle:
        while True:
            chunk = handle.readline(limit)
            if not chunk:
                return
            if len(chunk) >= limit and not chunk.endswith(b"\n"):
                _drain(handle)
                yield None
                continue
            body = chunk[:-1] if chunk.endswith(b"\n") else chunk
            if body.endswith(b"\r"):
                body = body[:-1]
            yield None if len(body) > max_line_bytes else body


def _load_object(line: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _stratum_of(obj: dict[str, Any], key: str | None) -> str | None:
    if key is None:
        return None
    value = obj.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    return _UNKNOWN_STRATUM


def _parse_line(
    line: bytes,
    input_key: str,
    output_key: str,
    id_key: str | None,
    stratify_by: str | None,
) -> tuple[str, str, str | None, str | None] | None:
    obj = _load_object(line)
    if obj is None:
        return None
    text = obj.get(input_key)
    if not isinstance(text, str) or not text.strip():
        return None
    raw_id = ""
    if id_key is not None:
        value = obj.get(id_key)
        if isinstance(value, bool) or not isinstance(value, str | int):
            return None
        raw_id = str(value)
        if not raw_id:
            return None
    output = obj.get(output_key)
    if output is not None and not isinstance(output, str):
        output = json.dumps(output, ensure_ascii=False, sort_keys=True)
    return raw_id, text, output, _stratum_of(obj, stratify_by)


def _dedupe_digest(text: str) -> bytes:
    folded = unicodedata.normalize("NFKC", text).casefold()
    normalized = " ".join(folded.split())
    return hashlib.sha256(normalized.encode("utf-8", "surrogatepass")).digest()


def read_logs(
    path: Path,
    input_key: str = "input",
    output_key: str = "output",
    id_key: str | None = None,
    stratify_by: str | None = None,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
    extra_patterns: Mapping[str, str] | None = None,
) -> ReadResult:
    """Read a JSONL log file, scrub every record and drop duplicates.

    Lines that are not JSON objects, lack a usable ``input_key`` or exceed ``max_line_bytes``
    are skipped and counted. Records whose scrubbed input is equal after NFKC, casefold and
    whitespace collapse are duplicates (the first one is kept). The id is the first 12 hex
    characters of the sha256 of the scrubbed input unless ``id_key`` names a log field.

    Raises:
        GoldenSetError: ``input_invalid`` for an unreadable file, bad limits, more than
            ``max_records`` records or duplicate ids; ``invalid_pattern`` for a bad pattern.
    """
    _require_positive(max_line_bytes, "max_line_bytes")
    _require_positive(max_records, "max_records")
    if not input_key or not output_key:
        raise GoldenSetError("input_invalid", "input_key and output_key must not be empty")
    compile_patterns(extra_patterns)
    records: list[LogRecord] = []
    seen: set[bytes] = set()
    ids: set[str] = set()
    invalid = oversize = duplicates = valid = 0
    try:
        for line in _iter_lines(Path(path), max_line_bytes):
            if line is None:
                oversize += 1
                continue
            parsed = _parse_line(line, input_key, output_key, id_key, stratify_by)
            if parsed is None:
                invalid += 1
                continue
            valid += 1
            if valid > max_records:
                raise GoldenSetError("input_invalid", "too many records in the log file")
            raw_id, text, output, stratum = parsed
            raw = LogRecord(raw_id, text, output, stratum)
            cleaned = scrub(raw) if extra_patterns is None else scrub(raw, extra_patterns)
            digest = _dedupe_digest(cleaned.input)
            if digest in seen:
                duplicates += 1
                continue
            seen.add(digest)
            if id_key is None:
                encoded = cleaned.input.encode("utf-8", "surrogatepass")
                record_id = hashlib.sha256(encoded).hexdigest()[:_ID_LENGTH]
            else:
                record_id = raw_id
            if record_id in ids:
                raise GoldenSetError("input_invalid", "duplicate record id")
            ids.add(record_id)
            records.append(replace(cleaned, id=record_id))
    except OSError:
        raise GoldenSetError("input_invalid", "cannot read the log file") from None
    logger.info(
        "read %d records (%d invalid, %d oversize, %d duplicate)",
        len(records),
        invalid,
        oversize,
        duplicates,
    )
    return ReadResult(tuple(records), invalid, oversize, duplicates)


def _check_sample_size(n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise GoldenSetError("sample_size", "n must be a positive integer")


def _record_id(record: LogRecord) -> str:
    return record.id


def _quotas(sizes: dict[str, int], n: int, total: int) -> dict[str, int]:
    """Largest-remainder allocation of ``n`` over strata; ties are broken by stratum name."""
    quotas = {name: n * size // total for name, size in sizes.items()}
    extra = n - sum(quotas.values())
    order = sorted(sizes, key=lambda name: (-(n * sizes[name] % total), name))
    for name in order[:extra]:
        quotas[name] += 1
    return quotas


def sample(records: Iterable[LogRecord], n: int, seed: int = 0) -> list[LogRecord]:
    """Draw a reproducible stratified sample of ``n`` records, ordered by id.

    Records are sorted by id, quotas follow the largest-remainder method and each stratum is
    sampled with ``random.Random(seed)`` in stratum-name order. If ``n`` exceeds the number of
    records, all records are returned and a warning is emitted.

    Raises:
        GoldenSetError: ``sample_size`` if ``n`` is not a positive integer.
    """
    _check_sample_size(n)
    ordered = sorted(records, key=_record_id)
    total = len(ordered)
    if n >= total:
        if n > total:
            message = f"requested {n} cases but only {total} are available; returning all"
            logger.warning(message)
            warnings.warn(message, UserWarning, stacklevel=2)
        return ordered
    groups: dict[str, list[LogRecord]] = {}
    for record in ordered:
        groups.setdefault(record.stratum or "", []).append(record)
    quotas = _quotas({name: len(items) for name, items in groups.items()}, n, total)
    rng = _RNG_FACTORY(seed)
    picked: list[LogRecord] = []
    for name in sorted(groups):
        if quotas[name]:
            picked.extend(rng.sample(groups[name], quotas[name]))
    return sorted(picked, key=_record_id)


def self_check(
    records: Iterable[LogRecord],
    extra_patterns: Mapping[str, str] | None = None,
    check_ids: bool = False,
) -> None:
    """Run every built-in and custom detector over the output fields of ``records``.

    Raises:
        GoldenSetError: ``pii_remaining`` if any detector still matches. The message names the
            detector and never quotes the record.
    """
    patterns = compile_patterns(extra_patterns)
    for record in records:
        fields = [record.input]
        if record.output is not None:
            fields.append(record.output)
        if check_ids:
            fields.append(record.id)
        for text in fields:
            name = find_pii(text, patterns)
            if name is not None:
                message = f"detector {name} still matches an output field; nothing was written"
                raise GoldenSetError("pii_remaining", message)


def write_jsonl(rows: Iterable[Mapping[str, Any]], path: Path) -> None:
    """Write ``rows`` as JSONL through a temporary file and ``os.replace``.

    Raises:
        GoldenSetError: ``input_invalid`` if the file cannot be written.
    """
    target = Path(path)
    tmp_name: str | None = None
    try:
        descriptor, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".golden-", suffix=".tmp")
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        tmp_name = None
    except OSError:
        raise GoldenSetError("input_invalid", "cannot write the output file") from None
    finally:
        if tmp_name is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)


def _annotation_row(record: LogRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "input": record.input,
        "output": record.output,
        "expected": None,
        "label": None,
    }


def export_annotation(records: Iterable[LogRecord], path: Path) -> None:
    """Write an annotation file with keys id, input, output, expected and label.

    ``expected`` and ``label`` are ``null`` for the annotators to fill in. Nothing else from the
    log record is written.
    """
    write_jsonl([_annotation_row(record) for record in records], path)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in _iter_lines(path, DEFAULT_MAX_LINE_BYTES):
            if line is None:
                raise GoldenSetError("input_invalid", "annotation line exceeds the size limit")
            if not line.strip():
                continue
            if len(rows) >= DEFAULT_MAX_RECORDS:
                raise GoldenSetError("input_invalid", "too many annotation records")
            row = _load_object(line)
            if row is None:
                raise GoldenSetError("input_invalid", "annotation line is not a JSON object")
            rows.append(row)
    except OSError:
        raise GoldenSetError("input_invalid", "cannot read the annotation file") from None
    return rows


def import_annotation(golden: Path, labelled: Path) -> list[dict[str, Any]]:
    """Merge annotator labels from ``labelled`` into the cases of ``golden``.

    Returns one dict per golden case, in golden order, with the keys id, input, output, expected
    and label.

    Raises:
        GoldenSetError: ``unknown_case_id`` for an id that is not in the golden file;
            ``input_invalid`` for unreadable files; ``merge_conflict`` for
            conflicting rows for one id.
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in _read_rows(Path(golden)):
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in merged:
            raise GoldenSetError("input_invalid", "golden file has a missing or duplicate id")
        merged[case_id] = {
            "id": case_id,
            "input": row.get("input"),
            "output": row.get("output"),
            "expected": row.get("expected"),
            "label": row.get("label"),
        }
    updates: dict[str, dict[str, Any]] = {}
    for row in _read_rows(Path(labelled)):
        case_id = row.get("id")
        if not isinstance(case_id, str) or case_id not in merged:
            raise GoldenSetError("unknown_case_id", "labelled id is not in the golden file")
        values = {key: row[key] for key in _ANNOTATION_KEYS if key in row}
        if updates.get(case_id, values) != values:
            raise GoldenSetError("merge_conflict", "conflicting labelled rows for one id")
        updates[case_id] = values
        merged[case_id].update(values)
    return list(merged.values())


def build(
    logs: Path,
    output: Path,
    n: int,
    seed: int = 0,
    stratify_by: str | None = None,
    input_key: str = "input",
    output_key: str = "output",
    id_key: str | None = None,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
    extra_patterns: Mapping[str, str] | None = None,
) -> BuildResult:
    """Read, scrub, dedupe, sample, self-check and write an annotation-ready golden set.

    Nothing is written when the self-check finds personal data.

    Raises:
        GoldenSetError: ``sample_size``, ``invalid_pattern``, ``input_invalid`` or
            ``pii_remaining``.
    """
    _check_sample_size(n)
    compile_patterns(extra_patterns)
    result = read_logs(
        logs,
        input_key,
        output_key,
        id_key,
        stratify_by,
        max_line_bytes,
        max_records,
        extra_patterns,
    )
    chosen = sample(result.records, n, seed)
    self_check(chosen, extra_patterns, check_ids=id_key is not None)
    export_annotation(chosen, output)
    return BuildResult(
        len(chosen),
        result.skipped_invalid,
        result.skipped_oversize,
        result.duplicates,
    )
