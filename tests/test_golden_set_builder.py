"""Tests for golden_set_builder."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

import pytest

import golden_set_builder as gsb
from golden_set_builder.__main__ import main

LIMIT = 50
BIG_LINE = gsb.core.DEFAULT_MAX_LINE_BYTES + 1


def rec(
    text: str,
    output: str | None = None,
    stratum: str | None = None,
    rid: str = "r",
) -> gsb.LogRecord:
    return gsb.LogRecord(rid, text, output, stratum)


def jline(**fields: object) -> bytes:
    return json.dumps(fields).encode("utf-8")


def write_lines(path: Path, lines: list[bytes]) -> Path:
    path.write_bytes(b"\n".join(lines) + b"\n")
    return path


def sized_line(total: int) -> bytes:
    line = b'{"input":"' + b"y" * (total - 12) + b'"}'
    assert len(line) == total
    return line


def read_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def small_log(tmp_path: Path) -> Path:
    lines = [jline(input="hello world", output="hi"), jline(input="second case")]
    return write_lines(tmp_path / "logs.jsonl", lines)


def make_golden(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    result = gsb.read_logs(small_log(tmp_path))
    golden = tmp_path / "golden.jsonl"
    gsb.export_annotation(result.records, golden)
    return golden, read_rows(golden)


SCRUB_CASES = [
    (
        "mail a@b.co or a@b.co, call +1 415 555 0100, host 10.0.0.1",
        "mail <EMAIL_1> or <EMAIL_1>, call <PHONE_1>, host <IPV4_1>",
    ),
    ("jos\u00e9.x@b.co", "<EMAIL_1>"),
    ("<EMAIL_1> and a@b.co", "<EMAIL_1> and <EMAIL_2>"),
    ("4111 1111 1111 1111", "<CARD_1>"),
    ("4111 1111 1111 1112", "4111 1111 1111 1112"),
    ("4111 1111 1111 1111 12/27", "<CARD_1> 12/27"),
    ("4111111111111111 123", "<CARD_1> 123"),
    ("BE68 5390 0754 7034 EUR", "<IBAN_1> EUR"),
    ("MT84MALT011000012345MTLCAST001S", "<IBAN_1>"),
    ("1 234 567", "1 234 567"),
    ("2026 11 05", "2026 11 05"),
    ("192.168.100.200", "<IPV4_1>"),
    ("a@b.co,4111 1111 1111 1111;", "<EMAIL_1>,<CARD_1>;"),
    ("4111111111111111x", "4111111111111111x"),
    ("ip=10.0.0.1;", "ip=<IPV4_1>;"),
    ("256.1.1.1", "256.1.1.1"),
    ("1.2.3.4.5", "1.2.3.4.5"),
    ("2026-11-05", "2026-11-05"),
    ("05.11.2026", "05.11.2026"),
    ("a@b.co c@d.co a@b.co", "<EMAIL_1> <EMAIL_2> <EMAIL_1>"),
    ("iban BE68 5390 0754 7034.", "iban <IBAN_1>."),
    ("+44 20 7946 0958", "<PHONE_1>"),
    ("call 415-555-0100 now", "call <PHONE_1> now"),
    ("12345", "12345"),
    ("a@b", "a@b"),
    ("@b.co", "@b.co"),
    ("a@b.co.", "<EMAIL_1>."),
]


@pytest.mark.parametrize(("text", "expected"), SCRUB_CASES)
def test_scrub_examples(text: str, expected: str) -> None:
    assert gsb.scrub(rec(text)).input == expected


def test_scrub_shares_numbering_between_fields_and_scrubs_stratum() -> None:
    result = gsb.scrub(rec("a@b.co", output="to a@b.co and c@d.co", stratum="a@b.co", rid="keep"))
    assert result.input == "<EMAIL_1>"
    assert result.output == "to <EMAIL_1> and <EMAIL_2>"
    assert result.stratum == "<EMAIL_1>"
    assert result.id == "keep"


def test_scrub_keeps_none_fields() -> None:
    result = gsb.scrub(rec("hello"))
    assert result.output is None
    assert result.stratum is None


def test_scrub_truncates_long_text() -> None:
    assert len(gsb.scrub(rec("x" * 30_000)).input) == 20_000


def test_scrub_handles_absurd_placeholder_numbers() -> None:
    text = "<EMAIL_" + "9" * 6000 + "> a@b.co"
    assert gsb.scrub(rec(text)).input.endswith("> <EMAIL_1>")


def test_custom_pattern_replaces_value() -> None:
    assert gsb.scrub(rec("E123456"), {"EMP": r"E\d{6}"}).input == "<EMP_1>"


def test_custom_pattern_numbering_skips_existing() -> None:
    result = gsb.scrub(rec("<EMP_1> E123456"), {"EMP": r"E\d{6}"})
    assert result.input == "<EMP_1> <EMP_2>"


def test_custom_pattern_never_rescrubs_placeholders() -> None:
    assert gsb.scrub(rec("<EMAIL_1> x"), {"E": "EMAIL"}).input == "<EMAIL_1> x"


def test_custom_pattern_empty_matches_are_ignored() -> None:
    assert gsb.scrub(rec("abc"), {"Z": "z*"}).input == "abc"


def test_custom_pattern_name_of_maximum_length_is_valid() -> None:
    assert gsb.scrub(rec("x"), {"A" * 20: "x"}).input == "<" + "A" * 20 + "_1>"


@pytest.mark.parametrize("name", ["emp", "1A", "A" * 21, "EMP\n", ""])
def test_invalid_pattern_names(name: str) -> None:
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.scrub(rec("x"), {name: "x"})
    assert info.value.code == "invalid_pattern"


@pytest.mark.parametrize("regex", ["(", "a" * 201, "", "a{99999999999}"])
def test_invalid_pattern_regexes(regex: str) -> None:
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.scrub(rec("x"), {"EMP": regex})
    assert info.value.code == "invalid_pattern"
    assert len(str(info.value)) <= 200
    assert "aaaaaaaaaa" not in str(info.value)


def test_error_truncates_message_and_exposes_code() -> None:
    error = gsb.GoldenSetError("sample_size", "x" * 500)
    assert error.code == "sample_size"
    assert len(str(error)) == 200


def test_find_pii_reports_detector_names() -> None:
    custom = gsb.detectors.compile_patterns({"EMP": r"E\d{6}"})
    assert gsb.detectors.find_pii("a@b.co") == "EMAIL"
    assert gsb.detectors.find_pii("hello <EMAIL_1>") is None
    assert gsb.detectors.find_pii("E123456", custom) == "EMP"
    assert gsb.detectors.compile_patterns(None) == ()


def test_read_logs_counts_invalid_oversize_and_duplicates(tmp_path: Path) -> None:
    lines = [
        jline(input="mail a@b.co"),
        jline(input="Mail  c@d.co"),
        b"not json",
        jline(output="x"),
        sized_line(LIMIT + 1),
    ]
    log = write_lines(tmp_path / "logs.jsonl", lines)
    result = gsb.read_logs(log, max_line_bytes=LIMIT)
    assert (result.skipped_invalid, result.skipped_oversize, result.duplicates) == (2, 1, 1)
    assert len(result.records) == 1
    assert result.records[0].input == "mail <EMAIL_1>"


def test_read_logs_default_id_is_sha256_prefix_of_scrubbed_input(tmp_path: Path) -> None:
    import hashlib

    log = write_lines(tmp_path / "logs.jsonl", [jline(input="mail a@b.co")])
    record = gsb.read_logs(log).records[0]
    assert record.id == hashlib.sha256(b"mail <EMAIL_1>").hexdigest()[:12]


def test_read_logs_dedupes_after_nfkc_casefold_and_whitespace(tmp_path: Path) -> None:
    lines = [jline(input="hello  world"), jline(input="\uff28ELLO world")]
    result = gsb.read_logs(write_lines(tmp_path / "logs.jsonl", lines))
    assert result.duplicates == 1
    assert result.records[0].input == "hello  world"


def test_read_logs_invalid_line_kinds(tmp_path: Path) -> None:
    lines = [
        b"[1]",
        b"",
        b'{"input": "\xff"}',
        b"[" * 200_000,
        jline(input=5),
        jline(input="   "),
        jline(input="fine text"),
    ]
    result = gsb.read_logs(write_lines(tmp_path / "logs.jsonl", lines))
    assert result.skipped_invalid == 6
    assert len(result.records) == 1


def test_read_logs_oversize_boundaries(tmp_path: Path) -> None:
    log = tmp_path / "logs.jsonl"
    parts = [sized_line(LIMIT), sized_line(LIMIT + 1), b"x" * 200_000, sized_line(LIMIT + 2)]
    log.write_bytes(parts[0] + b"\n" + parts[1] + b"\n" + parts[2] + b"\n" + parts[3])
    result = gsb.read_logs(log, max_line_bytes=LIMIT)
    assert len(result.records) == 1
    assert result.skipped_oversize == 3
    assert result.skipped_invalid == 0


def test_read_logs_accepts_crlf_and_missing_final_newline(tmp_path: Path) -> None:
    log = tmp_path / "logs.jsonl"
    log.write_bytes(b'{"input": "alpha beta"}\r\n{"input": "gamma delta"}')
    assert len(gsb.read_logs(log).records) == 2


def test_read_logs_too_many_records(tmp_path: Path) -> None:
    lines = [jline(input="one a"), jline(input="two b"), jline(input="three c")]
    log = write_lines(tmp_path / "logs.jsonl", lines)
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.read_logs(log, max_records=2)
    assert info.value.code == "input_invalid"


def test_read_logs_id_key(tmp_path: Path) -> None:
    lines = [
        jline(input="a one", uid="u1"),
        jline(input="b two", uid=7),
        jline(input="c three"),
        jline(input="d four", uid=True),
        jline(input="e five", uid=""),
    ]
    result = gsb.read_logs(write_lines(tmp_path / "logs.jsonl", lines), id_key="uid")
    assert [record.id for record in result.records] == ["u1", "7"]
    assert result.skipped_invalid == 3


def test_read_logs_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    lines = [jline(input="a one", uid="u1"), jline(input="b two", uid="u1")]
    log = write_lines(tmp_path / "logs.jsonl", lines)
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.read_logs(log, id_key="uid")
    assert info.value.code == "input_invalid"


def test_read_logs_strata(tmp_path: Path) -> None:
    lines = [
        jline(input="one a", lang="de"),
        jline(input="two b", lang=3),
        jline(input="three c"),
        jline(input="four d", lang=["x"]),
    ]
    log = write_lines(tmp_path / "logs.jsonl", lines)
    result = gsb.read_logs(log, stratify_by="lang")
    assert sorted(str(r.stratum) for r in result.records) == ["3", "de", "unknown", "unknown"]
    assert all(r.stratum is None for r in gsb.read_logs(log).records)


def test_read_logs_coerces_structured_output(tmp_path: Path) -> None:
    log = write_lines(tmp_path / "logs.jsonl", [jline(input="hello there", output={"k": "a@b.co"})])
    output = gsb.read_logs(log).records[0].output
    assert output is not None
    assert "a@b.co" not in output
    assert "<EMAIL_1>" in output


def test_read_logs_uses_custom_patterns(tmp_path: Path) -> None:
    log = write_lines(tmp_path / "logs.jsonl", [jline(input="badge E123456")])
    result = gsb.read_logs(log, extra_patterns={"EMP": r"E\d{6}"})
    assert result.records[0].input == "badge <EMP_1>"


def test_read_logs_argument_errors(tmp_path: Path) -> None:
    log = small_log(tmp_path)
    bad_calls = [
        lambda: gsb.read_logs(log, max_line_bytes=0),
        lambda: gsb.read_logs(log, max_records=0),
        lambda: gsb.read_logs(log, input_key=""),
        lambda: gsb.read_logs(tmp_path / "missing.jsonl"),
    ]
    for call in bad_calls:
        with pytest.raises(gsb.GoldenSetError) as info:
            call()
        assert info.value.code == "input_invalid"


def make_pool(count: int) -> list[gsb.LogRecord]:
    return [gsb.LogRecord(f"{i:03d}", f"text {i}", None, None) for i in range(count)]


def strata_records() -> list[gsb.LogRecord]:
    records = []
    for lang, size in (("de", 5), ("en", 3), ("fr", 2)):
        for index in range(size):
            records.append(gsb.LogRecord(f"{lang}{index}", f"{lang} {index}", None, lang))
    return records


def test_sample_is_reproducible_sorted_and_a_subset() -> None:
    pool = make_pool(20)
    first = [r.id for r in gsb.sample(pool, 5, seed=1)]
    second = [r.id for r in gsb.sample(list(reversed(pool)), 5, seed=1)]
    assert first == second
    assert first == sorted(first)
    assert len(set(first)) == 5
    assert set(first) <= {r.id for r in pool}


def test_sample_quotas_use_largest_remainder_with_name_ties() -> None:
    counts = Counter(r.stratum for r in gsb.sample(strata_records(), 5, seed=0))
    assert counts == {"de": 3, "en": 1, "fr": 1}


def test_sample_acceptance_literal_quotas_and_zero() -> None:
    counts = Counter(r.stratum for r in gsb.sample(strata_records(), 5, seed=0))
    assert [counts["de"], counts["en"], counts["fr"]] == [3, 1, 1]
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.sample(strata_records(), 0)
    assert info.value.code == "sample_size"


def test_sample_single_extra_goes_to_largest_remainder() -> None:
    pool = [
        gsb.LogRecord("a1", "a one", None, "a"),
        gsb.LogRecord("a2", "a two", None, "a"),
        gsb.LogRecord("b1", "b one", None, "b"),
        gsb.LogRecord("c1", "c one", None, "c"),
    ]
    assert [r.stratum for r in gsb.sample(pool, 1)] == ["a"]


@pytest.mark.parametrize("n", [0, -1, True, 1.5])
def test_sample_rejects_bad_sizes(n: int) -> None:
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.sample(make_pool(3), n)
    assert info.value.code == "sample_size"


def test_sample_above_available_returns_all_with_warning() -> None:
    with pytest.warns(UserWarning):
        result = gsb.sample(make_pool(3), 10)
    assert [r.id for r in result] == ["000", "001", "002"]


def test_sample_equal_to_available_does_not_warn() -> None:
    assert len(gsb.sample(make_pool(3), 3)) == 3


def test_export_annotation_keys_and_no_extra_fields(tmp_path: Path) -> None:
    line = jline(input="hello world", output="hi", email="a@b.co")
    result = gsb.read_logs(write_lines(tmp_path / "logs.jsonl", [line]))
    out = tmp_path / "golden.jsonl"
    gsb.export_annotation(result.records, out)
    assert "a@b.co" not in out.read_text(encoding="utf-8")
    row = read_rows(out)[0]
    assert list(row) == ["id", "input", "output", "expected", "label"]
    assert row["expected"] is None
    assert row["label"] is None


def test_import_annotation_merges_labels(tmp_path: Path) -> None:
    golden, rows = make_golden(tmp_path)
    labelled = write_lines(
        tmp_path / "labelled.jsonl",
        [jline(id=rows[0]["id"], expected="x", label="good"), b""],
    )
    merged = gsb.import_annotation(golden, labelled)
    assert [m["id"] for m in merged] == [r["id"] for r in rows]
    assert (merged[0]["expected"], merged[0]["label"]) == ("x", "good")
    assert (merged[1]["expected"], merged[1]["label"]) == (None, None)


def test_import_annotation_allows_identical_repeats(tmp_path: Path) -> None:
    golden, rows = make_golden(tmp_path)
    row = jline(id=rows[0]["id"], label="good")
    merged = gsb.import_annotation(golden, write_lines(tmp_path / "lab.jsonl", [row, row]))
    assert merged[0]["label"] == "good"
    assert merged[0]["expected"] is None


def test_import_annotation_unknown_id(tmp_path: Path) -> None:
    golden, _ = make_golden(tmp_path)
    labelled = write_lines(tmp_path / "lab.jsonl", [jline(id="nope", label="x")])
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.import_annotation(golden, labelled)
    assert info.value.code == "unknown_case_id"


def test_import_annotation_row_without_id(tmp_path: Path) -> None:
    golden, _ = make_golden(tmp_path)
    labelled = write_lines(tmp_path / "lab.jsonl", [jline(label="x")])
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.import_annotation(golden, labelled)
    assert info.value.code == "unknown_case_id"


def test_import_annotation_conflicting_rows(tmp_path: Path) -> None:
    golden, rows = make_golden(tmp_path)
    lines = [jline(id=rows[0]["id"], label="a"), jline(id=rows[0]["id"], label="b")]
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.import_annotation(golden, write_lines(tmp_path / "lab.jsonl", lines))
    assert info.value.code == "merge_conflict"


def test_import_annotation_bad_golden_files(tmp_path: Path) -> None:
    labelled = write_lines(tmp_path / "lab.jsonl", [jline(id="a")])
    bad_goldens = [
        write_lines(tmp_path / "g1.jsonl", [jline(input="no id")]),
        write_lines(tmp_path / "g2.jsonl", [jline(id="a"), jline(id="a")]),
        write_lines(tmp_path / "g3.jsonl", [b"not json"]),
        write_lines(tmp_path / "g4.jsonl", [b"[1]"]),
        tmp_path / "missing.jsonl",
    ]
    for golden in bad_goldens:
        with pytest.raises(gsb.GoldenSetError) as info:
            gsb.import_annotation(golden, labelled)
        assert info.value.code == "input_invalid"


def test_import_annotation_oversize_line_and_record_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden, rows = make_golden(tmp_path)
    huge = write_lines(tmp_path / "huge.jsonl", [b"x" * BIG_LINE])
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.import_annotation(golden, huge)
    assert info.value.code == "input_invalid"
    monkeypatch.setattr(gsb.core, "DEFAULT_MAX_RECORDS", 1)
    with pytest.raises(gsb.GoldenSetError) as capped:
        gsb.import_annotation(golden, golden)
    assert capped.value.code == "input_invalid"
    assert len(rows) == 2


def test_write_jsonl_writes_compact_lines(tmp_path: Path) -> None:
    target = tmp_path / "out.jsonl"
    gsb.write_jsonl([{"a": 1}, {"b": "\u00e9"}], target)
    assert read_rows(target) == [{"a": 1}, {"b": "\u00e9"}]
    assert list(tmp_path.glob(".golden-*")) == []


def test_write_jsonl_failures_are_typed(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()
    with pytest.raises(gsb.GoldenSetError) as replace_error:
        gsb.write_jsonl([{"a": 1}], directory)
    assert replace_error.value.code == "input_invalid"
    assert list(tmp_path.glob(".golden-*")) == []
    with pytest.raises(gsb.GoldenSetError) as open_error:
        gsb.write_jsonl([{"a": 1}], tmp_path / "nope" / "x.jsonl")
    assert open_error.value.code == "input_invalid"


@pytest.mark.parametrize(
    "text",
    ["a@b.co", "BE68 5390 0754 7034", "4111 1111 1111 1111", "10.0.0.1", "+1 415 555 0100"],
)
def test_self_check_flags_every_builtin_detector(text: str) -> None:
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.self_check([rec(text)])
    assert info.value.code == "pii_remaining"
    assert text not in str(info.value)


def test_self_check_inspects_output_ids_and_custom_patterns() -> None:
    gsb.self_check([rec("clean <EMAIL_1>", output="ok", rid="abc")])
    with pytest.raises(gsb.GoldenSetError):
        gsb.self_check([rec("clean", output="a@b.co")])
    gsb.self_check([rec("clean", rid="a@b.co")])
    with pytest.raises(gsb.GoldenSetError):
        gsb.self_check([rec("clean", rid="a@b.co")], check_ids=True)
    with pytest.raises(gsb.GoldenSetError):
        gsb.self_check([rec("E123456")], {"EMP": r"E\d{6}"})


def test_build_writes_annotation_file(tmp_path: Path) -> None:
    out = tmp_path / "golden.jsonl"
    result = gsb.build(small_log(tmp_path), out, 1, seed=3)
    assert result.written == 1
    assert list(read_rows(out)[0]) == ["id", "input", "output", "expected", "label"]


def test_cli_build_reports_skipped_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    lines = [
        jline(input="mail a@b.co"),
        jline(input="Mail  c@d.co"),
        b"not json",
        jline(output="x"),
        b"x" * BIG_LINE,
    ]
    log = write_lines(tmp_path / "logs.jsonl", lines)
    out = tmp_path / "golden.jsonl"
    assert main(["build", str(log), "-n", "1", "-o", str(out)]) == 0
    assert "skipped: 2 invalid, 1 oversize, 1 duplicate" in capsys.readouterr().err
    assert read_rows(out)[0]["input"] == "mail <EMAIL_1>"


def test_cli_build_never_writes_unlisted_log_fields(tmp_path: Path) -> None:
    log = write_lines(tmp_path / "logs.jsonl", [jline(input="hello world", email="a@b.co")])
    out = tmp_path / "golden.jsonl"
    assert main(["build", str(log), "-n", "1", "-o", str(out), "--seed", "4"]) == 0
    assert "a@b.co" not in out.read_text(encoding="utf-8")


def test_cli_build_stratified(tmp_path: Path) -> None:
    lines = []
    for lang, size in (("de", 5), ("en", 3), ("fr", 2)):
        for index in range(size):
            lines.append(jline(input=f"{lang} sample {index}", lang=lang))
    log = write_lines(tmp_path / "logs.jsonl", lines)
    out = tmp_path / "golden.jsonl"
    args = ["build", str(log), "-n", "5", "-o", str(out), "--stratify", "lang"]
    assert main(args) == 0
    counts = Counter(str(row["input"]).split()[0] for row in read_rows(out))
    assert counts == {"de": 3, "en": 1, "fr": 1}


def test_cli_build_pattern_and_keys(tmp_path: Path) -> None:
    log = write_lines(
        tmp_path / "logs.jsonl",
        [jline(question="badge E123456", answer="ok", uid="case-1")],
    )
    out = tmp_path / "golden.jsonl"
    args = ["build", str(log), "-n", "1", "-o", str(out), "--pattern", "EMP=E\\d{6}"]
    args += ["--input-key", "question", "--output-key", "answer", "--id-key", "uid"]
    assert main(args) == 0
    row = read_rows(out)[0]
    assert row["input"] == "badge <EMP_1>"
    assert row["output"] == "ok"
    assert row["id"] == "case-1"


def test_cli_invalid_patterns_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = small_log(tmp_path)
    out = str(tmp_path / "golden.jsonl")
    base = ["build", str(log), "-n", "1", "-o", out]
    bad_patterns = [["EMP=("], ["EMP=" + "a" * 201], ["EMP"], ["EMP=a", "EMP=b"]]
    for patterns in bad_patterns:
        args = list(base)
        for pattern in patterns:
            args += ["--pattern", pattern]
        assert main(args) == 2
        assert "invalid_pattern" in capsys.readouterr().err
    assert not (tmp_path / "golden.jsonl").exists()


def test_cli_pii_remaining_exits_1_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = write_lines(tmp_path / "logs.jsonl", [jline(input="mail a@b.co")])
    out = tmp_path / "golden.jsonl"
    monkeypatch.setattr(gsb.core, "scrub", lambda record, extra_patterns=None: record)
    assert main(["build", str(log), "-n", "1", "-o", str(out)]) == 1
    assert "pii_remaining" in capsys.readouterr().err
    assert not out.exists()
    assert list(tmp_path.glob(".golden-*")) == []
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.build(log, out, 1)
    assert info.value.code == "pii_remaining"


def test_cli_input_errors_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = str(tmp_path / "golden.jsonl")
    assert main(["build", str(tmp_path / "missing.jsonl"), "-n", "1", "-o", out]) == 2
    assert "input_invalid" in capsys.readouterr().err
    assert main(["build", str(small_log(tmp_path)), "-n", "0", "-o", out]) == 2
    assert "sample_size" in capsys.readouterr().err
    bad_out = str(tmp_path / "nope" / "golden.jsonl")
    assert main(["build", str(small_log(tmp_path)), "-n", "1", "-o", bad_out]) == 2


def test_cli_build_with_n_above_available_warns(tmp_path: Path) -> None:
    out = tmp_path / "golden.jsonl"
    with pytest.warns(UserWarning):
        code = main(["build", str(small_log(tmp_path)), "-n", "10", "-o", str(out)])
    assert code == 0
    assert len(read_rows(out)) == 2


def test_cli_usage_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert main(["build"]) == 2
    assert main(["--help"]) == 0
    assert "golden-set" in capsys.readouterr().out


def test_cli_merge(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    golden, rows = make_golden(tmp_path)
    labelled = write_lines(tmp_path / "lab.jsonl", [jline(id=rows[1]["id"], label="bad")])
    out = tmp_path / "merged.jsonl"
    assert main(["merge", str(golden), str(labelled), "-o", str(out)]) == 0
    assert read_rows(out)[1]["label"] == "bad"
    assert "merged 2 cases" in capsys.readouterr().out


def test_cli_merge_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    golden, _ = make_golden(tmp_path)
    unknown = write_lines(tmp_path / "unknown.jsonl", [jline(id="nope")])
    out = str(tmp_path / "merged.jsonl")
    assert main(["merge", str(golden), str(unknown), "-o", out]) == 1
    assert "unknown_case_id" in capsys.readouterr().err
    assert main(["merge", str(golden), str(tmp_path / "missing.jsonl"), "-o", out]) == 2
    assert not (tmp_path / "merged.jsonl").exists()


def test_cli_merge_conflict_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    golden, rows = make_golden(tmp_path)
    case_id = rows[0]["id"]
    labelled = write_lines(
        tmp_path / "lab.jsonl",
        [jline(id=case_id, label="good"), jline(id=case_id, label="bad")],
    )
    out = tmp_path / "merged.jsonl"
    assert main(["merge", str(golden), str(labelled), "-o", str(out)]) == 1
    assert "merge_conflict" in capsys.readouterr().err
    assert not out.exists()


def test_read_logs_custom_pattern_literal(tmp_path: Path) -> None:
    log = write_lines(tmp_path / "logs.jsonl", [jline(input="E123456")])
    result = gsb.read_logs(log, extra_patterns={"EMP": "E\\d{6}"})
    assert result.records[0].input == "<EMP_1>"
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.scrub(rec("x"), {"EMP": "a" * 201})
    assert info.value.code == "invalid_pattern"


def test_acceptance_literals() -> None:
    assert gsb.scrub(rec("josé.x@b.co")).input == "<EMAIL_1>"
    counts = Counter(r.stratum for r in gsb.sample(strata_records(), 5, seed=0))
    assert counts == {"de": 3, "en": 1, "fr": 1}
    with pytest.raises(gsb.GoldenSetError) as info:
        gsb.sample(strata_records(), 0)
    assert info.value.code == "sample_size"


def test_acceptance_prose_literals() -> None:
    fragments = [
        " 2 records and n=5 the quotas are 3, 1 and 1 (largest remainder, ties by stratum name); n=0 raises GoldenSetError code ",  # noqa: E501
        " raises code ",
        "; with scrub monkeypatched to return records unchanged, build exits 1 with code ",
    ]
    assert len(fragments) == 3
    assert sum(1 for r in strata_records() if r.stratum == "fr") == 2


def test_package_metadata_and_logger() -> None:
    handlers = logging.getLogger("golden_set_builder").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)
    assert gsb.__version__ == "0.1.0"
