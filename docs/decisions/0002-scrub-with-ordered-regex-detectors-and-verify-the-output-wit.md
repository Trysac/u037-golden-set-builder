# Scrub with ordered regex detectors and verify the output with the same detectors

Status: accepted (generated, pending human review)

## Context

Golden evaluation sets built from production logs must not leak personal data, must not contain near-duplicates and must be reproducible. The tool has no network access and must stay dependency free, so detection has to be rule based and its limits must be explicit.

## Decision

Use a fixed pipeline of standard-library regex detectors (EMAIL, IBAN with mod-97, CARD with Luhn, IPV4, PHONE, then validated user patterns) that replace matches with per-record numbered typed placeholders and never re-scrub placeholders. Validators that reject a greedy match retry shorter prefixes at separator boundaries. Records are deduplicated on the NFKC, casefolded, whitespace-collapsed scrubbed input and get ids derived from the scrubbed input, so no raw value is ever hashed. Sampling uses sorted ids, largest-remainder quotas and random.Random(seed) per stratum. Before writing, the same detectors run over the output fields, and any match aborts with pii_remaining without creating a file. Files are written through a temporary file and os.replace.

## Consequences

Output is deterministic and auditable, and the tool refuses to publish text its own detectors still flag. Detection stays best effort: names, addresses and unusual formats are missed, which docs/SECURITY.md states. Default hash ids are not self-checked because digit runs inside hashes can look like phone numbers. User regexes cannot be timed out. The build output carries only id, input, output, expected and label, so the stratum is not preserved in the file.
