"""Shared stock cache."""

CACHE: dict[str, int] = {}


def warm(sku: str, quantity: int) -> None:
    CACHE[sku] = quantity
