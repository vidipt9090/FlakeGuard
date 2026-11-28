"""Stock reservation."""


class StockService:
    def __init__(self) -> None:
        self.available = {"sku-1": 40}

    def reserve(self, sku: str, quantity: int) -> int:
        # Seeded bug: a negative quantity is accepted and increases stock.
        self.available[sku] -= quantity
        return self.available[sku]
