from src.core.behaviors.behavior import Behavior
from src.core.behaviors.items.auto_equipment_behavior import AutoEquipmentBehavior
from src.core.behaviors.quests.dungeon_behavior import DungeonBehavior
from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import (
    SaleHotelSellBehavior,
)
from src.core.behaviors.sale_hotel.sale_hotel_update_prices_behavior import SaleHotelUpdatePricesBehavior
from src.core.behaviors.storage.mule.mule_accept_behavior import MuleAcceptBehavior
from src.utils.project_paths import IS_PACKAGED

USABLE_BEHAVIORS: list[type[Behavior]] = [
    MuleAcceptBehavior,
    DungeonBehavior,
    SaleHotelSellBehavior,
    SaleHotelUpdatePricesBehavior,
    AutoEquipmentBehavior,
]

if not IS_PACKAGED:
    from src.core.behaviors.interactives.fake_bad_interactive_behavior import FakeBadInteractiveBehavior
    from src.core.behaviors.movements.fake_bad_movement_behavior import FakeBadMovementBehavior

    USABLE_BEHAVIORS.extend([FakeBadMovementBehavior, FakeBadInteractiveBehavior])
