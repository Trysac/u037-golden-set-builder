# Security

`golden-set-builder` turns production logs into a golden evaluation set. It reduces the personal data that ends up in that set; it does not eliminate it.

## Threat model

- Asset: personal data contained in production logs.
- Adversary: anyone who can read the golden set, which is usually committed to a repository or handed to annotators.
- Goal of the tool: no identifier recognised by its detectors is written to the output file.

### Defended

- Detected identifiers are replaced by placeholders before sampling and writing. Detectors: `EMAIL` (whole address, Unicode local parts included), `IBAN` (ISO 13616 mod-97 check, length 15-34), `CARD` (13-19 digits, Luhn check), `IPV4` (octets 0-255), `PHONE` (7-15 digits, thousands shapes and dates excluded), and custom `--pattern NAME=REGEX` run last.
- Self-check before writing: every built-in and custom detector runs over the written fields (input, output and, with `--id-key`, the id). Any match raises `pii_remaining`, the CLI exits with code 1, and no output file is created.
- Only `id`, `input`, `output`, `expected` and `label` are written. Other log fields and the placeholder mapping are never written.
- Default ids are the first 12 hex characters of the sha256 of the scrubbed input, so ids do not contain the raw input.
- Size limits: lines over `max_line_bytes` (1 MiB) are skipped without being buffered; text fields are truncated to 20,000 characters before matching; custom regexes are at most 200 characters with names matching `[A-Z][A-Z0-9_]{0,19}`; at most `max_records` (1,000,000) records are accepted.
- Output is written to a temporary file and moved with `os.replace`.
- Error messages never quote log records and are at most 200 characters long. Logging never logs record contents.

### Not defended

- Names, postal addresses, IPv6 addresses, free-text identifiers and anything that matches no detector are not found. Detection is best effort.
- Custom regexes are user supplied and cannot be timed out. Do not run untrusted patterns.
- Values in fields other than input, output and (with `--id-key`) the id are not scanned; they are not written either.
- The tool does not verify who can read the output file; file permissions are the caller's responsibility.

**Review the golden set before publishing it.**
