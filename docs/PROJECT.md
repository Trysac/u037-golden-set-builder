# Project record

## Objective

Build golden evaluation datasets from production JSONL logs, so that teams can build a reproducible, scrubbed, deduplicated, stratified sample ready for human annotation, without copying examples by hand.

## Scope

- In scope: the public API documented in [README.md](../README.md): reading and deduplicating JSONL logs, regex PII scrubbing with typed placeholders, seeded stratified sampling, annotation export and merge, and the `python -m golden_set_builder` CLI.
- Out of scope: name and postal address detection, runtime dependencies, and any I/O beyond the log, annotation and output files.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 825776 / 142529 |
| Hours (human) | pending measurement |
| Cost (USD) | 1.2260 |

## Factory run u037 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2953 | 120473 | 0 | 4246 | 0.6057 |
| fix-1 | claude-sonnet-5-5 | no | 8 | 1283 | 19463 | 68133 | 0.0683 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 1050 | 7709 | 57009 | 0.0355 |
| fix-3 | claude-sonnet-5-5 | no | 8 | 839 | 4868 | 60107 | 0.0266 |
| audit | claude-sonnet-5-5 | no | 16 | 6397 | 39931 | 232566 | 0.1871 |
| fix-4 | claude-sonnet-5-5 | no | 10 | 4844 | 19078 | 92658 | 0.1054 |
| fix-1 | claude-sonnet-5-5 | no | 10 | 1166 | 8716 | 77688 | 0.0412 |
| fix-2 | claude-sonnet-5-5 | no | 10 | 1610 | 20890 | 98926 | 0.0782 |
| docs | claude-haiku-5-5 | no | 131420 | 4867 | 0 | 0 | 0.0779 |

Total: $1.2260. Prices: Anthropic list prices.
