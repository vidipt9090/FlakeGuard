"""Reports built from the shared stock cache."""

from inventory.cache import CACHE


class Report:
    def title(self) -> str:
        return "Report"

    def total(self, sku: str) -> int:
        return CACHE.get(sku, 0)
