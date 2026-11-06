# Architecture

## Purpose

`trysac-golden-set-builder` is a small, dependency-free Python library and CLI that builds golden evaluation datasets from production JSONL logs: it reads and deduplicates records, scrubs personal data with typed placeholders, draws a seeded stratified sample, and writes annotation files.

## Shape

```text
caller code / CLI (__main__.py) --> golden_set_builder (public API in __init__.py)
                                        |
                                        +-- core.py       reading, scrubbing pipeline, sampling, annotation files
                                        +-- detectors.py  regex PII detectors, custom patterns, placeholder numbering
                                        +-- errors.py     GoldenSetError with a Literal code
```

- **Public API**: the names listed in `__all__` of `src/golden_set_builder/__init__.py`.
- **Pipeline** (`build`): read, scrub, deduplicate, sample, self-check, write. Nothing is written when the self-check finds personal data.
- **Errors**: library functions raise `GoldenSetError` with a stable `code`; the CLI maps codes to exit codes.
- **Side effects**: file reading and writing happen in `core.py`. Writes go through a temporary file and `os.replace`.
- **Logging**: `logging.getLogger(__name__)` with a `NullHandler`; record contents are never logged.

## Quality contract

The gates are defined by `scripts/check.py`. See [TESTING.md](TESTING.md).

## Decisions

The package does not register a console script; the CLI runs as `python -m golden_set_builder`. The build output is the annotation file, whose keys are fixed to id, input, output, expected and label, so the stratum is used for sampling only and is not written.
