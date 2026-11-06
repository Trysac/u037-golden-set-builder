# Testing

## Running

```sh
uv run pytest --cov=golden_set_builder   # tests with coverage report
uv run python scripts/check.py           # every gate, as CI and the factory run it
```

## Policy

- Branch coverage of `src/golden_set_builder` must stay at or above 80 %; the gate fails below it.
- Tests exercise the public API (`import golden_set_builder`) and assert observable effects: return values, raised exceptions and their codes and messages.
- Each bug fix starts with a failing test that reproduces it.
- Tests are deterministic: no network, no wall clock, no dependence on test order.

## Layout

`tests/test_<module>.py` mirrors each public module. Shared fixtures go in `tests/conftest.py`.

Acceptance cases from the specification to cover: placeholder replacement and numbering, whole-address e-mail replacement, Luhn and mod-97 checks, shorter-span fallback, deduplication and hashed ids, seeded stratified quotas, annotation keys, skipped-line accounting, custom pattern validation, and the `pii_remaining` abort.
