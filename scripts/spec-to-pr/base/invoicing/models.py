from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List

from .money import to_money


@dataclass(frozen=True)
class LineItem:
    sku: str
    description: str
    qty: int
    unit_price: Decimal
    tax_rate: Decimal = Decimal("0")

    def net(self) -> Decimal:
        return to_money(self.unit_price * self.qty)

    def tax(self) -> Decimal:
        return to_money(self.net() * self.tax_rate)


@dataclass
class Invoice:
    id: str
    customer: str
    issued: date
    lines: List[LineItem] = field(default_factory=list)

    def subtotal(self) -> Decimal:
        return to_money(sum((l.net() for l in self.lines), Decimal("0")))

    def tax(self) -> Decimal:
        return to_money(sum((l.tax() for l in self.lines), Decimal("0")))

    def total(self) -> Decimal:
        return to_money(self.subtotal() + self.tax())
