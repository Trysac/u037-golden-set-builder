# golden-set-builder

[![PyPI version](https://img.shields.io/pypi/v/trysac-golden-set-builder)](https://pypi.org/project/trysac-golden-set-builder/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-golden-set-builder)](LICENSE)
[![CI](https://github.com/Trysac/u037-golden-set-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u037-golden-set-builder/actions/workflows/ci.yml)

Build golden evaluation datasets from production JSONL logs: dedup, regex PII scrubbing with typed placeholders, seeded stratified sampling, annotation files

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-golden-set-builder
# or
uv add trysac-golden-set-builder
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import golden_set_builder

# normalize() trims surrounding whitespace and lower-cases the text.
print(golden_set_builder.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    golden_set_builder.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
