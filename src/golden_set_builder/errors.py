"""Typed errors raised by golden_set_builder."""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal[
    "invalid_pattern",
    "unknown_case_id",
    "sample_size",
    "input_invalid",
    "pii_remaining",
    "merge_conflict",
]

_MAX_MESSAGE_CHARS = 200


class GoldenSetError(Exception):
    """Base error of the library.

    Attributes:
        code: Stable machine-readable error code. Messages never quote log records and are
            truncated to 200 characters.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message[:_MAX_MESSAGE_CHARS])
        self.code: ErrorCode = code
