"""Build golden evaluation datasets from production JSONL logs."""

from __future__ import annotations

import logging

from . import core, detectors
from .core import (
    BuildResult,
    LogRecord,
    ReadResult,
    build,
    export_annotation,
    import_annotation,
    read_logs,
    sample,
    scrub,
    self_check,
    write_jsonl,
)
from .errors import GoldenSetError

__all__ = [
    "BuildResult",
    "GoldenSetError",
    "LogRecord",
    "ReadResult",
    "__version__",
    "build",
    "core",
    "detectors",
    "export_annotation",
    "import_annotation",
    "read_logs",
    "sample",
    "scrub",
    "self_check",
    "write_jsonl",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
