"""HDV ressources: update *existing* listings only; never touch the bank or create a sale."""
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import partial

from DBDofusUnity.datas.protos.non_obf.game.exchange_pb2 import (
    ExchangeBidHouseItemRemovedEvent,
    ExchangeBidHousePriceRequest,
    ExchangeBidPriceEvent,
    ExchangeBidSellerStartedEvent,
    ExchangeObjectModifyPricedRequest,
)
from DBDofusUnity.dofus_unity_reader.game_constants.item import CategoryItemEnum
from DBDofusUnity.dofus_unity_reader.game_constants.sale_hotel import SALE_HOTEL_LISTING_FEE
from src.controller.game_data import GameDataController
from src.core.behaviors.sale_hotel.sale_hotel_price_guard import get_verified_lot_price
from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import SaleHotelSellBehavior
from src.services.human_timings import HumanTimingsService


@dataclass
class SaleHotelUpdatePricesBehavior(SaleHotelSellBehavior):
    """Uses only the HDV opening behavior and the existing listings snapshot."""

    _pending_updates: deque[ExchangeObjectModifyPricedRequest] = field(init=False, default_factory=deque)
    _updated_count: int = field(init=False, default=0)
    MAX_UPDATES = 40

    def start_selling(self) -> None:
        # run() from the parent performs the standard safety/recovery checks.
        self._activity_performed = False
        self._updated_count = 0
        self._pending_updates.clear()
        self.categories = {CategoryItemEnum.RESOURCES}
        self.sell_next_category()

    def sell_next_category(self) -> None:
        if not self.categories:
            return self.finish()
        self._curr_category = self.categories.pop()
        self.enter_sale_hotel_sell_behavior.start(
            callback=self.on_enter_sale_hotel_sell_behavior_finished,
            parent=self,
            category=self._curr_category,
        )

    def on_enter_sale_hotel_sell_behavior_finished(
        self,
        error_code: str | None,
        items: Iterable[ExchangeBidSellerStartedEvent.ItemToSellInBid],
    ) -> None:
        if error_code is not None:
            return self.finish(error_code)
        self._items_in_sale_hotel = list(items)
        self.update_all_prices()

    def update_all_prices(self) -> None:
        if self._updated_count >= self.MAX_UPDATES:
            self.logger.warning("HDV update limit reached (%s); ending", self.MAX_UPDATES)
            return self.finish()
        if not self._items_in_sale_hotel:
            return self.finish()
        item_gid = self._items_in_sale_hotel[0].item.gid
        self.update_item_price(item_gid)

    def update_item_price(self, item_gid: int) -> None:
        self.event_manager.on(
            ExchangeBidPriceEvent,
            partial(self.on_exchange_bid_price_event, item_gid=item_gid),
            originator=self,
            timeout=25,
            on_timeout=partial(self._on_price_timeout, item_gid),
            override_on_self=True,
        )
        self.send_message_delayed(
            ExchangeBidHousePriceRequest(object_gid=item_gid),
            HumanTimingsService().get_timing_sale_hotel_review(),
        )

    def _on_price_timeout(self, item_gid: int) -> None:
        self.logger.warning("HDV price response missing for %s; skipping its listings", item_gid)
        self._items_in_sale_hotel = [x for x in self._items_in_sale_hotel if x.item.gid != item_gid]
        self.update_all_prices()

    def on_exchange_bid_price_event(self, msg: ExchangeBidPriceEvent, item_gid: int) -> None:
        if msg.object_gid != item_gid:
            self.logger.warning("Ignoring unrelated HDV price response %s (expected %s)", msg.object_gid, item_gid)
            return
        self.unregister_listener(ExchangeBidPriceEvent)
        related = [x for x in self._items_in_sale_hotel if x.item.gid == item_gid]
        self._items_in_sale_hotel = [x for x in self._items_in_sale_hotel if x.item.gid != item_gid]
        server_id = self.game_state.player.server_id
        active_uids = GameDataController().get_hdv_by_uid_by_player(server_id).get(
            self.game_state.player.character_id, {}
        )
        minimal_prices = list(msg.bid_price_for_seller.minimal_prices)
        available_kamas = self.game_state.inventory.kamas
        self._pending_updates.clear()
        for item in related:
            if item.item.uid not in active_uids:
                continue
            market = get_verified_lot_price(minimal_prices, item.item.quantity)
            # Never invent a quote and never increase an existing listing.
            if market <= 1 or item.price <= market:
                continue
            target = market - 1
            if target >= item.price:
                continue
            fee = target * SALE_HOTEL_LISTING_FEE
            if fee > available_kamas:
                self.logger.warning("Insufficient kamas for updating HDV item %s", item.item.gid)
                continue
            available_kamas -= fee
            self._pending_updates.append(
                ExchangeObjectModifyPricedRequest(
                    object_uid=item.item.uid,
                    quantity=item.item.quantity,
                    price=target,
                )
            )
        self._send_next_update()

    def _send_next_update(self) -> None:
        if not self._pending_updates:
            return self.run_timer(
                HumanTimingsService().get_timing_sale_hotel_review(),
                self.update_all_prices,
            )
        if self._updated_count >= self.MAX_UPDATES:
            return self.finish()
        req = self._pending_updates.popleft()
        self.event_manager.on(
            ExchangeBidHouseItemRemovedEvent,
            partial(self._on_update_confirmed, expected_uid=req.object_uid),
            originator=self,
            timeout=20,
            on_timeout=self._on_update_timeout,
            override_on_self=True,
        )
        self.send_message_delayed(req, HumanTimingsService().get_timing_sale_hotel_price_change())

    def _on_update_confirmed(self, msg: ExchangeBidHouseItemRemovedEvent, expected_uid: int) -> None:
        if msg.sell_id != expected_uid:
            return
        self.unregister_listener(ExchangeBidHouseItemRemovedEvent)
        self._updated_count += 1
        self._activity_performed = True
        self.run_timer(HumanTimingsService().get_timing_sale_hotel_price_change(), self._send_next_update)

    def _on_update_timeout(self) -> None:
        self.logger.warning("HDV modification unconfirmed: stopping instead of looping")
        self.finish("HDV_MODIFICATION_UNCONFIRMED")
