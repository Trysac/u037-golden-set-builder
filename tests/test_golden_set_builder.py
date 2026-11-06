"""Behavior tests for the public API of golden_set_builder."""

from __future__ import annotations

import pytest

import golden_set_builder


def test_normalize_trims_and_lowercases() -> None:
    assert golden_set_builder.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        golden_set_builder.normalize(value)


def test_version_is_semver() -> None:
    parts = golden_set_builder.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
