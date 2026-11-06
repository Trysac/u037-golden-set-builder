"""Command line interface: ``python -m golden_set_builder``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .core import build, import_annotation, write_jsonl
from .errors import GoldenSetError

_CONFLICT_CODES = frozenset({"pii_remaining", "unknown_case_id", "merge_conflict"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="golden-set",
        description="Build golden evaluation datasets from JSONL logs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="scrub, sample and export a golden set")
    build_cmd.add_argument("logs", type=Path, help="input JSONL log file")
    build_cmd.add_argument("-n", "--count", type=int, required=True, help="cases to sample")
    build_cmd.add_argument("-o", "--output", type=Path, required=True, help="output JSONL")
    build_cmd.add_argument("--seed", type=int, default=0, help="sampling seed")
    build_cmd.add_argument("--stratify", default=None, metavar="FIELD", help="stratify field")
    build_cmd.add_argument("--pattern", action="append", default=[], metavar="NAME=REGEX")
    build_cmd.add_argument("--input-key", default="input")
    build_cmd.add_argument("--output-key", default="output")
    build_cmd.add_argument("--id-key", default=None)
    merge_cmd = commands.add_parser("merge", help="merge annotator labels into a golden file")
    merge_cmd.add_argument("golden", type=Path)
    merge_cmd.add_argument("labelled", type=Path)
    merge_cmd.add_argument("-o", "--output", type=Path, required=True)
    return parser


def _parse_patterns(items: Sequence[str]) -> dict[str, str]:
    patterns: dict[str, str] = {}
    for item in items:
        name, separator, regex = item.partition("=")
        if not separator or name in patterns:
            raise GoldenSetError("invalid_pattern", "use --pattern NAME=REGEX once per name")
        patterns[name] = regex
    return patterns


def _run_build(args: argparse.Namespace) -> int:
    result = build(
        args.logs,
        args.output,
        args.count,
        seed=args.seed,
        stratify_by=args.stratify,
        input_key=args.input_key,
        output_key=args.output_key,
        id_key=args.id_key,
        extra_patterns=_parse_patterns(args.pattern) or None,
    )
    summary = (
        f"skipped: {result.skipped_invalid} invalid, "
        f"{result.skipped_oversize} oversize, {result.duplicates} duplicate"
    )
    print(summary, file=sys.stderr)
    print(f"wrote {result.written} cases to {args.output}")
    return 0


def _run_merge(args: argparse.Namespace) -> int:
    rows = import_annotation(args.golden, args.labelled)
    write_jsonl(rows, args.output)
    print(f"merged {len(rows)} cases into {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code.

    Exit codes: 0 success, 1 self-check failure or merge conflict, 2 usage or input error.
    """
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_request:
        code = exit_request.code
        return code if isinstance(code, int) else 2
    try:
        if args.command == "build":
            return _run_build(args)
        return _run_merge(args)
    except GoldenSetError as error:
        print(f"error: {error.code}: {error}", file=sys.stderr)
        return 1 if error.code in _CONFLICT_CODES else 2


if __name__ == "__main__":
    raise SystemExit(main())
