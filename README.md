# golden-set-builder

[![PyPI version](https://img.shields.io/pypi/v/trysac-golden-set-builder)](https://pypi.org/project/trysac-golden-set-builder/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-golden-set-builder)](LICENSE)
[![CI](https://github.com/Trysac/u037-golden-set-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u037-golden-set-builder/actions/workflows/ci.yml)

Build golden evaluation datasets from production JSONL logs: dedup, regex PII scrubbing with typed placeholders, seeded stratified sampling, annotation files.

## Problem

The best evaluation cases come from real traffic, but production logs contain personal data, near-duplicates and a skewed distribution. Teams copy a few examples by hand and the golden set never grows. This library and CLI turn JSONL logs into a reproducible, scrubbed, deduplicated, stratified sample ready for human annotation, and refuse to finish if their own detectors still find personal data.

## Install

```sh
pip install trysac-golden-set-builder
# or
uv add trysac-golden-set-builder
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from golden_set_builder import LogRecord, scrub

record = LogRecord("1", "mail a@b.co or a@b.co, call +1 415 555 0100, host 10.0.0.1", None, None)
print(scrub(record).input)
# mail <EMAIL_1> or <EMAIL_1>, call <PHONE_1>, host <IPV4_1>
```

Public API: `read_logs`, `scrub`, `sample`, `export_annotation`, `import_annotation`, `LogRecord`, `ReadResult`, `GoldenSetError`.

Command line (`python -m golden_set_builder`):

```sh
python -m golden_set_builder build logs.jsonl -n 100 -o golden.jsonl --stratify lang
python -m golden_set_builder merge golden.jsonl labelled.jsonl -o out.jsonl
```

Exit codes: 0 ok, 1 self-check failure or merge conflict, 2 usage or input error.

## Public API

- `LogRecord(id, input, output=None, stratum=None)`: frozen dataclass.
- `read_logs(path, input_key="input", output_key="output", id_key=None, stratify_by=None, max_line_bytes=1_048_576, max_records=1_000_000, extra_patterns=None) -> ReadResult`: reads, scrubs and deduplicates; `ReadResult` holds `records`, `skipped_invalid`, `skipped_oversize`, `duplicates`.
- `scrub(record, extra_patterns=None) -> LogRecord`: replaces detected personal data by placeholders such as `<EMAIL_1>`.
- `sample(records, n, seed=0) -> list[LogRecord]`: seeded, largest-remainder stratified sample ordered by id.
- `export_annotation(records, path)`: writes keys `id`, `input`, `output`, `expected`, `label`.
- `import_annotation(golden, labelled) -> list[dict]`: merges labels into the golden file.

Errors: `GoldenSetError` with `code` one of `invalid_pattern`, `unknown_case_id`, `sample_size`, `input_invalid`, `pii_remaining`. Messages never quote records.

Limits: lines over `max_line_bytes` are skipped; text fields are truncated to 20,000 characters before matching; custom regexes are at most 200 characters; user regexes cannot be timed out; names and postal addresses are not detected.

## Why not Presidio?

Microsoft Presidio is a general-purpose PII analysis framework. This library instead uses a small set of fixed regex detectors with no runtime dependencies, and it is scoped to producing evaluation datasets rather than arbitrary PII analysis.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model and the detection limits. Review the golden set before publishing it.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
