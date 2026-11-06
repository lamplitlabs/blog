from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def to_money(value) -> Decimal:
    """Convert to Decimal rounded half-up to cents."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal) -> str:
    """Plain two-decimal string, e.g. 1234.50."""
    return str(to_money(value))
