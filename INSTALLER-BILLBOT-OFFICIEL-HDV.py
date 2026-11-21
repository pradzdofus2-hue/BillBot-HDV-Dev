#!/usr/bin/env python3
"""BillBot officiel 6.0_3.7.13.17 : séparer HDV ressources / actualisation.

N'utilise que Python standard (compatible avec le Python qui sert à appliquer le patch).
Usage : python INSTALLER-BILLBOT-OFFICIEL-HDV.py --check|--apply
Ne s'applique qu'au commit officiel pinne et aux fichiers sources officiels non modifies.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

OFFICIAL_COMMIT = '52fa2a9d4575f5ee954e7e23c027d5175f9bf308'
OFFICIAL_VERSION = '6.0_3.7.13.17'
EXPECTED_BLOBS = {
    'src/core/behaviors/sale_hotel/sale_hotel_sell_behavior.py': 'f7d2ee5311791a1dc95dff19a2ac65753e504719',
    'src/core/bot/bot_factory.py': '2cba00658ca97e710a647cc6bad76f8f5dcdd5c1',
    'src/core/behaviors/behavior_factory.py': 'c4e5b4abc808b88b73addb3e7ef279589aba55b3',
    'src/gui/pages/farmer/farmer.py': '7868386a6d995cd3cf673e895c4fe5fed4d9aa73',
}
UPDATER_PATH = 'src/core/behaviors/sale_hotel/sale_hotel_update_prices_behavior.py'
PRICE_GUARD_PATH = 'src/core/behaviors/sale_hotel/sale_hotel_price_guard.py'


def replace_once(s: str, needle: str, replacement: str, detail: str) -> str:
    found = s.count(needle)
    if found != 1:
        raise RuntimeError(f'Fichier officiel inattendu ({detail}) : {found} occurrences au lieu de 1.')
    return s.replace(needle, replacement, 1)


def patch_seller(s: str) -> str:
    s = replace_once(s,
        'from src.core.behaviors.sale_hotel.enter_sale_hotel_sell_behavior import (\n    EnterSaleHotelSellBehavior,\n)\n',
        'from src.core.behaviors.sale_hotel.enter_sale_hotel_sell_behavior import (\n    EnterSaleHotelSellBehavior,\n)\nfrom src.core.behaviors.sale_hotel.sale_hotel_price_guard import get_verified_lot_price\n',
        'seller price guard import')
    s = replace_once(s,
        '    _activity_performed: bool = field(init=False, default=False)\n',
        '    _activity_performed: bool = field(init=False, default=False)\n'
        '    _sale_bank_visits: int = field(init=False, default=0)\n',
        'seller visits field')
    s = replace_once(s,
        '        self._activity_performed = False\n'
        '        self.categories = {CategoryItemEnum.RESOURCES, CategoryItemEnum.CONSUMABLES}\n',
        '        self._activity_performed = False\n'
        '        self._sale_bank_visits = 0\n'
        '        self.categories = {CategoryItemEnum.RESOURCES}\n',
        'seller only resources')
    s = replace_once(s,
        '    def load_items(self) -> None:\n'
        '        self.logger.info(f"Gonna load and sell : {self._load_items_infos}")\n',
        '    def load_items(self) -> None:\n'
        '        self._sale_bank_visits += 1\n'
        '        if self._sale_bank_visits > 5:\n'
        '            self.logger.warning("Five bank-load cycles without completing sale; stopping")\n'
        '            return self.finish()\n'
        '        self.logger.info(f"Gonna load and sell : {self._load_items_infos}")\n',
        'seller bank trip limit')
    s = replace_once(s,
        '                    self.logger.info("No more item to sell, lets update prices")\n'
        '                    return self.update_all_prices()\n',
        '                    self.logger.info("Resources placed for sale; no price updates in this module")\n'
        '                    return self.finish()\n',
        'seller does not reprice after selling')
    s = replace_once(s,
        '        if not msg.follow:\n'
        '            return\n'
        '        self.unregister_listener(\n'
        '            ExchangeBidHouseSearchRequest,',
        '        if not msg.follow or msg.object_gid != next_item.gid:\n'
        '            return\n'
        '        self.unregister_listener(\n'
        '            ExchangeBidHouseSearchRequest,',
        'seller only accepts requested item selection')
    s = replace_once(s,
        '        self.event_manager.on(\n'
        '            ExchangeBidPriceEvent,\n'
        '            partial(\n'
        '                self.on_exchange_bid_price_event_after_select_for_create_price,\n'
        '                item=next_item,\n'
        '            ),\n'
        '            originator=self,\n'
        '            once=True,\n'
        '        )\n',
        '        self.event_manager.on(\n'
        '            ExchangeBidPriceEvent,\n'
        '            partial(\n'
        '                self.on_exchange_bid_price_event_after_select_for_create_price,\n'
        '                item=next_item,\n'
        '            ),\n'
        '            originator=self,\n'
        '            timeout=20,\n'
        '            on_timeout=self.create_all_prices,\n'
        '        )\n',
        'seller await matching price with timeout')
    s = replace_once(s,
        '    def on_exchange_bid_price_event_after_select_for_create_price(\n'
        '        self,\n'
        '        msg: ExchangeBidPriceEvent,\n'
        '        item: ObjectItem,\n'
        '    ) -> None:\n'
        '        self.create_price(list(msg.bid_price_for_seller.minimal_prices), item)\n',
        '    def on_exchange_bid_price_event_after_select_for_create_price(\n'
        '        self,\n'
        '        msg: ExchangeBidPriceEvent,\n'
        '        item: ObjectItem,\n'
        '    ) -> None:\n'
        '        if msg.object_gid != item.gid:\n'
        '            self.logger.warning(\n'
        '                f"Ignoring unrelated HDV price: expected {item.gid}, received {msg.object_gid}"\n'
        '            )\n'
        '            return\n'
        '        self.unregister_listener(ExchangeBidPriceEvent)\n'
        '        self.create_price(list(msg.bid_price_for_seller.minimal_prices), item)\n',
        'seller price must match gid')
    s = replace_once(s,
        '        market_price = get_price_for_sale_hotel(list(minimal_prices), quantity_to_sell)\n',
        '        # Never extrapolate a price using other lot sizes (1/10/100/1000).\n'
        '        market_price = get_verified_lot_price(minimal_prices, int(quantity_to_sell))\n',
        'seller real price for exact lot')
    s = replace_once(s,
        '            self.logger.info("Sale hotel is full of object, let\'s update prices")\n'
        '            return self.update_all_prices()\n',
        '            self.logger.info("HDV full: ending sell-only session without repricing")\n'
        '            return self.finish()\n',
        'seller full does not update')
    s = replace_once(s,
        '        self._activity_performed = True\n'
        '        if self.game_state.sale_hotel.is_full_object_in_sale_hotel:\n'
        '            return self.update_all_prices()\n',
        '        self._activity_performed = True\n'
        '        if self.game_state.sale_hotel.is_full_object_in_sale_hotel:\n'
        '            return self.finish()\n',
        'seller event full does not update')
    return s


def patch_factory(s: str) -> str:
    s = replace_once(s,
        'from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import (\n    SaleHotelSellBehavior,\n)\n',
        'from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import (\n    SaleHotelSellBehavior,\n)\n'
        'from src.core.behaviors.sale_hotel.sale_hotel_update_prices_behavior import SaleHotelUpdatePricesBehavior\n',
        'factory updater import')
    s = replace_once(s,
        '        sale_hotel_prices_behavior = SaleHotelSellBehavior(\n',
        '        sale_hotel_sell_behavior = SaleHotelSellBehavior(\n',
        'factory separate seller variable')
    s = replace_once(s,
        '            load_from_guild_chest_behavior=load_from_guild_chest_behavior,\n'
        '        )\n\n'
        '        weighted_path = WeightedPath()\n',
        '            load_from_guild_chest_behavior=load_from_guild_chest_behavior,\n'
        '        )\n'
        '        sale_hotel_prices_behavior = SaleHotelUpdatePricesBehavior(\n'
        '            recovery=blocking_state_recovery,\n'
        '            event_manager=event_manager,\n'
        '            game_state=game_state,\n'
        '            _logger=logger,\n'
        '            load_from_bank_behavior=load_from_bank_behavior,\n'
        '            enter_sale_hotel_sell_behavior=enter_sale_hotel_sell_behavior,\n'
        '            load_from_guild_chest_behavior=load_from_guild_chest_behavior,\n'
        '        )\n\n'
        '        weighted_path = WeightedPath()\n',
        'factory create updater')
    s = replace_once(s,
        '            sale_hotel_sell_behavior=sale_hotel_prices_behavior,\n',
        '            sale_hotel_sell_behavior=sale_hotel_sell_behavior,\n',
        'auto bot must sell, never reprice')
    s = replace_once(s,
        '                dungeon_behavior,\n'
        '                sale_hotel_prices_behavior,\n',
        '                dungeon_behavior,\n'
        '                sale_hotel_sell_behavior,\n'
        '                sale_hotel_prices_behavior,\n',
        'factory both usable behaviors')
    return s


def patch_behavior_factory(s: str) -> str:
    s = replace_once(s,
        'from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import (\n    SaleHotelSellBehavior,\n)\n',
        'from src.core.behaviors.sale_hotel.sale_hotel_sell_behavior import (\n    SaleHotelSellBehavior,\n)\n'
        'from src.core.behaviors.sale_hotel.sale_hotel_update_prices_behavior import SaleHotelUpdatePricesBehavior\n',
        'behavior dropdown import')
    s = replace_once(s,
        '    DungeonBehavior,\n    SaleHotelSellBehavior,\n',
        '    DungeonBehavior,\n    SaleHotelSellBehavior,\n    SaleHotelUpdatePricesBehavior,\n',
        'behavior dropdown two modules')
    return s


def patch_farmer(s: str) -> str:
    s = replace_once(s,
        'from src.gui.pages.farmer.world_tab import WorldTab\n\n\nclass FarmActionEnum',
        'from src.gui.pages.farmer.world_tab import WorldTab\n\n\n'
        'HDV_BEHAVIOR_LABELS = {\n'
        '    "SaleHotelSellBehavior": "HDV - Vendre ressources",\n'
        '    "SaleHotelUpdatePricesBehavior": "HDV - Actualiser prix",\n'
        '}\n\n\nclass FarmActionEnum',
        'farmer HDV menu labels')
    s = replace_once(s,
        '        for usable_behavior in USABLE_BEHAVIORS:\n'
        '            self.type_action_combo.addItem(usable_behavior.__name__)\n',
        '        for usable_behavior in USABLE_BEHAVIORS:\n'
        '            behavior_name = usable_behavior.__name__\n'
        '            self.type_action_combo.addItem(\n'
        '                HDV_BEHAVIOR_LABELS.get(behavior_name, behavior_name),\n'
        '                userData=behavior_name,\n'
        '            )\n',
        'farmer display labels + stable identity')
    s = replace_once(s,
        '        elif self.type_action_combo.currentText() not in FarmActionEnum:\n'
        '            self.bot.bot_signals.play_usable_behavior.emit(self.type_action_combo.currentText())\n',
        '        elif self.type_action_combo.currentText() not in FarmActionEnum:\n'
        '            behavior_name = self.type_action_combo.currentData() or self.type_action_combo.currentText()\n'
        '            self.bot.bot_signals.play_usable_behavior.emit(behavior_name)\n',
        'farmer dispatch by class name')
    return s


PRICE_GUARD_CODE = '''"""A real market quote for the precise lot is required for every HDV action."""
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
'''

UPDATER_CODE = '''"""HDV ressources: update *existing* listings only; never touch the bank or create a sale."""
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
'''


def blob_sha(content: bytes) -> str:
    # Git checks out text with CRLF on some Windows installations; normalize first.
    normalized = content.replace(b'\r\n', b'\n')
    header = f'blob {len(normalized)}\0'.encode('ascii')
    return hashlib.sha1(header + normalized).hexdigest()


def run_git(root: Path, *args: str) -> str:
    p = subprocess.run(['git', *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError(f'git {" ".join(args)} : {p.stderr.strip()}')
    return p.stdout.strip()


def check_and_prepare(root: Path) -> dict[Path, bytes]:
    if not (root / '.git').exists():
        raise RuntimeError('Lance le script dans le dossier du nouveau clone officiel Git.')
    head = run_git(root, 'rev-parse', 'HEAD')
    if head != OFFICIAL_COMMIT:
        raise RuntimeError(
            'Le clone n\'est pas sur la version officielle prevue. Executer : '
            f'git switch -c hdv-officiel {OFFICIAL_COMMIT}'
        )
    if (root / 'VERSION').read_text(encoding='utf-8').strip() != OFFICIAL_VERSION:
        raise RuntimeError('Fichier VERSION inattendu : patch prevu pour la 6.0_3.7.13.17.')
    if run_git(root, 'status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Le clone officiel contient deja des fichiers suivis modifies. Ne rien ecraser.')
    for path in (UPDATER_PATH, PRICE_GUARD_PATH):
        if (root / path).exists():
            raise RuntimeError(f'{path} existe deja : patch non reapplicable.')
    patches = {
        'src/core/behaviors/sale_hotel/sale_hotel_sell_behavior.py': patch_seller,
        'src/core/bot/bot_factory.py': patch_factory,
        'src/core/behaviors/behavior_factory.py': patch_behavior_factory,
        'src/gui/pages/farmer/farmer.py': patch_farmer,
    }
    new_files = {}
    for rel, transform in patches.items():
        p = root / rel
        before = p.read_bytes()
        current_sha = blob_sha(before)
        if current_sha != EXPECTED_BLOBS[rel]:
            raise RuntimeError(f'Fichier officiel inattendu : {rel} (Git {current_sha}).')
        result = transform(before.decode('utf-8-sig').replace('\r\n', '\n'))
        # BillBot uses Python 3.15 lazy imports; when this installer itself is
        # run with an older Python, strip the keyword ONLY in the test copy.
        syntax_only = result.replace('lazy from ', 'from ').replace('lazy import ', 'import ')
        compile(syntax_only, rel, 'exec')
        new_files[p] = result.encode('utf-8')
    for rel, payload in ((UPDATER_PATH, UPDATER_CODE), (PRICE_GUARD_PATH, PRICE_GUARD_CODE)):
        compile(payload, rel, 'exec')
        new_files[root / rel] = payload.encode('utf-8')
    return new_files


def main() -> int:
    parser = argparse.ArgumentParser(description='Patch HDV strictement sur le depot OFFICIEL BillBot')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Verifier sans modifier')
    mode.add_argument('--apply', action='store_true', help='Appliquer les 6 fichiers HDV uniquement')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        new_contents = check_and_prepare(root)
        print(f'[OK] Git officiel {OFFICIAL_COMMIT[:10]}, version {OFFICIAL_VERSION}')
        print('[OK] Diff cible : 4 fichiers modifies, 2 fichiers HDV crees.')
        for p in new_contents:
            print(' - ' + str(p.relative_to(root)).replace('\\', '/'))
        if args.check:
            print('[OK] Controle termine. Aucun fichier modifie.')
            return 0
        # Backup is stored outside the repository, so only HDV code appears in git status.
        backup = Path(tempfile.gettempdir()) / f'BillBot-HDV-Officiel-{uuid.uuid4().hex[:12]}.zip'
        with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in new_contents:
                if p.exists():
                    z.write(p, p.relative_to(root).as_posix())
        originals = {p: p.read_bytes() if p.exists() else None for p in new_contents}
        try:
            for p, body in new_contents.items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(body)
        except Exception:
            for p, original in originals.items():
                if original is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(original)
            raise
        print(f'[OK] Patch HDV applique. Sauvegarde hors du depot : {backup}')
        print('[OK] 2 modules dans le menu : HDV - Vendre ressources / HDV - Actualiser prix')
        print('[OK] Aucune fonctionnalite Songe/Socket provenant de l\'ancien dossier.')
        return 0
    except (OSError, RuntimeError, UnicodeError, SyntaxError) as e:
        print('[ERREUR] ' + str(e))
        print('[SECURITE] Aucune modification partielle volontaire.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
