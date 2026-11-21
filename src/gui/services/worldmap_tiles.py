import logging
from collections import OrderedDict
from functools import cache
from pathlib import Path

from ankama_launcher_emulator.utils.environment import resolve_dofus_path
from PyQt6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from DBDofusUnity.dofus_unity_reader.models.datas.worldmapsroot import WorldmapsrootItem
from src.gui.services.decoded_images import decoded_image
from src.services.icon_process import icon_process
from src.services.icon_worker import IconRequest, IconResponse

logger = logging.getLogger(__name__)
TILE_SIZE = 1024
type TileKey = tuple[int, int]


class WorldMapLoader:
    def __init__(self) -> None:
        self._game_dir: str | None = None
        self._unavailable = False

    def load(self, world_id: int, number: int) -> IconResponse:
        if self._unavailable:
            return IconResponse()
        try:
            if self._game_dir is None:
                self._game_dir = str(Path(resolve_dofus_path()).parent)
            response = icon_process.load(
                IconRequest(self._game_dir, "worldmap", number, TILE_SIZE, world_id)
            )
            if response.error:
                self._unavailable = True
                logger.warning("Worldmap backgrounds unavailable: %s", response.error)
            return response
        except Exception:
            self._unavailable = True
            logger.warning("Worldmap decoding process unavailable", exc_info=True)
            return IconResponse()


class _TileSignals(QObject):
    loaded = pyqtSignal(int, int, IconResponse)


class _LoadTile(QRunnable):
    def __init__(self, loader: WorldMapLoader, signals: _TileSignals, key: TileKey) -> None:
        super().__init__()
        self.loader = loader
        self.signals = signals
        self.key = key

    def run(self) -> None:
        self.signals.loaded.emit(*self.key, self.loader.load(*self.key))


class WorldMapTileCache(QObject):
    changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None, *, loader: WorldMapLoader | None = None) -> None:
        super().__init__(parent)
        self.worlds: dict[int, WorldmapsrootItem] = {}
        self._images: OrderedDict[TileKey, QImage] = OrderedDict()
        self._pending: set[TileKey] = set()
        self._missing: set[TileKey] = set()
        self._metadata_requested = False
        self._priority = 0
        self._loader = loader or WorldMapLoader()
        self._signals = _TileSignals(self)
        self._signals.loaded.connect(self._loaded)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    def geometry(self, world_id: int) -> WorldmapsrootItem | None:
        if not self._metadata_requested:
            self._metadata_requested = True
            self._request((0, 0))
        return self.worlds.get(world_id)

    def _request(self, key: TileKey) -> None:
        if key not in self._pending and key not in self._missing:
            self._pending.add(key)
            self._priority += 1
            self._pool.start(_LoadTile(self._loader, self._signals, key), self._priority)

    def request(self, world_id: int, number: int) -> QImage | None:
        key = world_id, number
        image = self._images.get(key)
        if image is not None:
            self._images.move_to_end(key)
        else:
            self._request(key)
        return image

    @pyqtSlot(int, int, IconResponse)
    def _loaded(self, world_id: int, number: int, response: IconResponse) -> None:
        key = world_id, number
        self._pending.discard(key)
        if key == (0, 0):
            self.worlds = {world.id: world for world in response.worldmaps or []}
        elif response.pixels:
            image = decoded_image(response)
            self._images[key] = image
            if len(self._images) > 32:
                self._images.popitem(last=False)
        else:
            self._missing.add(key)
        self.changed.emit()

    @pyqtSlot()
    def shutdown(self) -> None:
        self._pool.clear()
        icon_process.close()
        self._pool.waitForDone()


@cache
def worldmap_tile_cache() -> WorldMapTileCache:
    app = QCoreApplication.instance()
    tiles = WorldMapTileCache(app)
    if app is not None:
        app.aboutToQuit.connect(tiles.shutdown)
    return tiles
