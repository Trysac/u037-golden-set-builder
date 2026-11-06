"""Regex PII detectors and typed-placeholder scrubbing.

Detectors run in a fixed order on text that already holds the earlier placeholders: EMAIL, IBAN,
CARD, IPV4, PHONE and then user-supplied patterns. Detection is best effort: names and postal
addresses are not detected. User regular expressions cannot be timed out.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .errors import GoldenSetError

MAX_TEXT_CHARS = 20_000
MAX_PATTERN_CHARS = 200

Span = tuple[int, int]
Finder = Callable[[str], list[Span]]

_PLACEHOLDER = re.compile(r"<[A-Z0-9_]+_\d+>")
_PLACEHOLDER_PARTS = re.compile(r"<([A-Z0-9_]+)_(\d{1,9})>")
_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,19}")
_EMAIL = re.compile(r"(?<![\w.%+-])[\w.%+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}(?![\w-])")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}[0-9]{2}(?: ?[A-Za-z0-9]){11,30}(?![A-Za-z0-9])")
_CARD = re.compile(r"(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?!\w)")
_IPV4 = re.compile(r"(?<![0-9.])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9.])")
_PHONE = re.compile(r"(?<![0-9+])(?<![0-9][ .-])\+?[0-9](?:[ .-]?[0-9]){6,14}(?![ .-]?[0-9])")
_DATE = re.compile(r"[0-9]{4}[ .-][0-9]{2}[ .-][0-9]{2}|[0-9]{2}[ .-][0-9]{2}[ .-][0-9]{4}")
_SEPARATOR = re.compile(r"[ .-]")


@dataclass(frozen=True)
class CustomPattern:
    """A validated user pattern: a placeholder name and its compiled regular expression."""

    name: str
    regex: re.Pattern[str]


def compile_patterns(extra: Mapping[str, str] | None) -> tuple[CustomPattern, ...]:
    """Validate and compile ``NAME -> REGEX`` custom patterns.

    Names must match ``[A-Z][A-Z0-9_]{0,19}`` and regexes are limited to 200 characters.

    Raises:
        GoldenSetError: with code ``invalid_pattern`` for any invalid name or regex.
    """
    if not extra:
        return ()
    compiled: list[CustomPattern] = []
    for name, source in extra.items():
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise GoldenSetError("invalid_pattern", "pattern name is invalid")
        if not isinstance(source, str) or not source or len(source) > MAX_PATTERN_CHARS:
            raise GoldenSetError("invalid_pattern", "pattern regex is empty or too long")
        try:
            regex = re.compile(source)
        except (re.error, OverflowError, RecursionError):
            raise GoldenSetError("invalid_pattern", f"pattern {name} is invalid") from None
        compiled.append(CustomPattern(name, regex))
    return tuple(compiled)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = (compact[4:] + compact[:4]).upper()
    number = "".join(str(int(char, 36)) for char in rearranged)
    return int(number) % 97 == 1


def _card_valid(candidate: str) -> bool:
    digits = "".join(char for char in candidate if char.isdigit())
    return 13 <= len(digits) <= 19 and _luhn_valid(digits)


def _phone_valid(candidate: str) -> bool:
    if _DATE.fullmatch(candidate):
        return False
    if not candidate.startswith("+"):
        groups = _SEPARATOR.split(candidate)
        if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
            return False
    return True


def _longest_valid_end(
    text: str,
    start: int,
    end: int,
    valid: Callable[[str], bool],
    separators: str,
) -> int | None:
    """Return the end of the longest valid span, retrying prefixes at separator boundaries."""
    if valid(text[start:end]):
        return end
    for index in range(end - 1, start, -1):
        if text[index] in separators and valid(text[start:index]):
            return index
    return None


def _scan(
    text: str,
    candidate: re.Pattern[str],
    valid: Callable[[str], bool],
    separators: str,
) -> list[Span]:
    spans: list[Span] = []
    position = 0
    while True:
        match = candidate.search(text, position)
        if match is None:
            return spans
        start, end = match.span()
        stop = _longest_valid_end(text, start, end, valid, separators)
        if stop is None:
            position = start + 1
        else:
            spans.append((start, stop))
            position = stop


def _find_email(text: str) -> list[Span]:
    return [match.span() for match in _EMAIL.finditer(text)]


def _find_iban(text: str) -> list[Span]:
    return _scan(text, _IBAN, _iban_valid, " ")


def _find_card(text: str) -> list[Span]:
    return _scan(text, _CARD, _card_valid, " -")


def _find_ipv4(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in _IPV4.finditer(text):
        if all(int(part) <= 255 for part in match.group().split(".")):
            spans.append(match.span())
    return spans


def _find_phone(text: str) -> list[Span]:
    return [match.span() for match in _PHONE.finditer(text) if _phone_valid(match.group())]


def _custom_finder(regex: re.Pattern[str]) -> Finder:
    def find(text: str) -> list[Span]:
        return [match.span() for match in regex.finditer(text) if match.end() > match.start()]

    return find


_BUILTIN: tuple[tuple[str, Finder], ...] = (
    ("EMAIL", _find_email),
    ("IBAN", _find_iban),
    ("CARD", _find_card),
    ("IPV4", _find_ipv4),
    ("PHONE", _find_phone),
)


def _finders(patterns: Sequence[CustomPattern]) -> list[tuple[str, Finder]]:
    return [*_BUILTIN, *((pattern.name, _custom_finder(pattern.regex)) for pattern in patterns)]


def _protected_mask(text: str) -> bytearray:
    """Mark every character that belongs to an existing placeholder."""
    mask = bytearray(len(text))
    for match in _PLACEHOLDER.finditer(text):
        start, end = match.span()
        mask[start:end] = bytes([1]) * (end - start)
    return mask


def _free(spans: list[Span], mask: bytearray) -> list[Span]:
    return [span for span in spans if mask.find(1, span[0], span[1]) == -1]


class _Numbering:
    """Per-record placeholder numbering that skips numbers already present in the text."""

    def __init__(self) -> None:
        self._used: dict[str, set[int]] = {}
        self._assigned: dict[tuple[str, str], int] = {}

    def reserve(self, text: str) -> None:
        for match in _PLACEHOLDER_PARTS.finditer(text):
            self._used.setdefault(match.group(1), set()).add(int(match.group(2)))

    def placeholder(self, name: str, value: str) -> str:
        key = (name, value)
        number = self._assigned.get(key)
        if number is None:
            used = self._used.setdefault(name, set())
            number = 1
            while number in used:
                number += 1
            used.add(number)
            self._assigned[key] = number
        return f"<{name}_{number}>"


def _replace(text: str, spans: list[Span], name: str, numbering: _Numbering) -> str:
    if not spans:
        return text
    parts: list[str] = []
    last = 0
    for start, end in spans:
        parts.append(text[last:start])
        parts.append(numbering.placeholder(name, text[start:end]))
        last = end
    parts.append(text[last:])
    return "".join(parts)


def scrub_texts(
    texts: Sequence[str | None],
    patterns: Sequence[CustomPattern] = (),
) -> list[str | None]:
    """Scrub several texts of one record with shared placeholder numbering.

    Each text is truncated to 20_000 characters first. Existing placeholders are never
    re-scrubbed and new numbers skip the ones already present in any of the texts.
    """
    clipped = [None if text is None else text[:MAX_TEXT_CHARS] for text in texts]
    numbering = _Numbering()
    for text in clipped:
        if text is not None:
            numbering.reserve(text)
    finders = _finders(patterns)
    scrubbed: list[str | None] = []
    for text in clipped:
        if text is None:
            scrubbed.append(None)
            continue
        for name, finder in finders:
            spans = _free(finder(text), _protected_mask(text))
            text = _replace(text, spans, name, numbering)
        scrubbed.append(text)
    return scrubbed


def find_pii(text: str, patterns: Sequence[CustomPattern] = ()) -> str | None:
    """Return the name of the first detector that still matches ``text``, or ``None``."""
    mask = _protected_mask(text)
    for name, finder in _finders(patterns):
        if _free(finder(text), mask):
            return name
    return None
