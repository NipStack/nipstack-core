"""Strict capture validation and explicitly bounded, fixed transformation pipelines."""

import json
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface, IPv6Address, IPv6Interface

from nipstack_core.contracts.json_data import JSONValue

from .model import Capture, NativeError, NativeLimits, Validator

_MAX_INTEGER_DIGITS = 640


def _decimal(value: str, *, unsigned: bool = False) -> bool:
    digits = value[1:] if not unsigned and value[:1] in ("+", "-") else value
    return bool(digits) and digits.isascii() and digits.isdecimal()


def validates(validator: Validator, value: str) -> bool:
    if validator == "INT":
        return _decimal(value)
    if any(character in value for character in "%[]"):
        return False
    if validator in ("PREFIXV4", "PREFIXV6"):
        parts = value.split("/")
        if (
            len(parts) != 2
            or not _decimal(parts[1], unsigned=True)
            or len(parts[1]) > 3
            or (len(parts[1]) > 1 and parts[1].startswith("0"))
        ):
            return False
    try:
        if validator == "IPV4":
            IPv4Address(value)
        elif validator == "IPV6":
            IPv6Address(value)
        elif validator == "PREFIXV4":
            IPv4Interface(value)
        else:
            IPv6Interface(value)
    except ValueError:
        return False
    return True


def _integer(value: str, *, unsigned: bool = False) -> int:
    if not _decimal(value, unsigned=unsigned):
        raise NativeError("MALFORMED_LINE")
    if len(value.lstrip("+-")) > _MAX_INTEGER_DIGITS:
        raise NativeError("RESOURCE_LIMIT")
    return int(value, 10)


def json_bytes(value: JSONValue) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@dataclass(slots=True)
class ValueBudget:
    """Cumulative intermediate array elements; state belongs to one parse call."""

    limits: NativeLimits
    items: int = 0

    def check_items(self, count: int) -> None:
        if count > self.limits.max_transformed_items - self.items:
            raise NativeError("RESOURCE_LIMIT")

    def claim(self, count: int) -> None:
        self.check_items(count)
        self.items += count

    def check_bytes(self, size: int) -> None:
        if size > self.limits.max_output_bytes:
            raise NativeError("RESOURCE_LIMIT")


def _expand(items: tuple[str, ...], delimiter: str, budget: ValueBudget) -> tuple[str, ...]:
    pieces: list[str | tuple[int, int]] = []
    count = 0
    for item in items:
        if delimiter not in item:
            pieces.append(item)
            count += 1
        else:
            endpoints = item.split(delimiter)
            if len(endpoints) != 2:
                raise NativeError("MALFORMED_LINE")
            start, end = (_integer(endpoint, unsigned=True) for endpoint in endpoints)
            if start > end:
                raise NativeError("MALFORMED_LINE")
            count += end - start + 1
            pieces.append((start, end))
        budget.check_items(count)
    size = 2 + max(0, count - 1)
    for piece in pieces:
        if isinstance(piece, str):
            size += json_bytes(piece)
        else:
            size += sum(len(str(number)) + 2 for number in range(piece[0], piece[1] + 1))
        budget.check_bytes(size)
    budget.claim(count)
    expanded: list[str] = []
    for piece in pieces:
        if isinstance(piece, str):
            expanded.append(piece)
        else:
            expanded.extend(str(number) for number in range(piece[0], piece[1] + 1))
    return tuple(expanded)


def transform_value(capture: Capture, value: str, budget: ValueBudget) -> JSONValue:
    steps = capture.transformations
    if not steps:
        return value
    if steps[0].kind == "to_int":
        return _integer(value)
    first = steps[0]
    assert first.kind == "split" and first.delimiter is not None
    budget.claim(value.count(first.delimiter) + 1)
    items = tuple(value.split(first.delimiter))
    budget.check_bytes(json_bytes(items))
    for step in steps[1:]:
        if step.kind == "expand_ranges":
            assert step.delimiter is not None
            items = _expand(items, step.delimiter, budget)
        else:
            assert step.kind == "map_int"
            budget.claim(len(items))
            integers = tuple(_integer(item) for item in items)
            budget.check_bytes(json_bytes(integers))
            return integers
    return items
