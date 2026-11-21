"""A real market quote for the precise lot is required for every HDV action."""
from collections.abc import Sequence

from DBDofusUnity.dofus_unity_reader.game_constants.sale_hotel import (
    QUANTITY_INDEX_BY_QUANTITY,
    QuantityEnum,
)


def get_verified_lot_price(minimal_prices: Sequence[int], quantity: int) -> int:
    """No inferred price when the market has no price for this lot (1, 10, 100, 1000)."""
    try:
        lot = QuantityEnum(quantity)
    except (ValueError, TypeError):
        return 0
    index = QUANTITY_INDEX_BY_QUANTITY[lot]
    if index >= len(minimal_prices):
        return 0
    price = int(minimal_prices[index])
    return price if price > 0 else 0
