import logging
from collections import OrderedDict
from functools import cache
from pathlib import Path
from typing import Literal

from ankama_launcher_emulator.utils.environment import resolve_dofus_path
from PyQt6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from src.gui.services.decoded_images import decoded_image
from src.services.icon_process import icon_process
from src.services.icon_worker import IconRequest

logger = logging.getLogger()
ICON_SIZE = 64


class IconLoader:
    def __init__(self, *, kind: Literal["item", "class"] = "item", size: int = ICON_SIZE) -> None:
        self._kind = kind
        self._size = size
        self._game_dir: str | None = None
        self._unavailable = False

    def load(self, icon_id: int) -> QImage:
        if self._unavailable:
            return QImage()
        try:
            if self._game_dir is None:
                self._game_dir = str(Path(resolve_dofus_path()).parent)
            response = icon_process.load(IconRequest(self._game_dir, self._kind, icon_id, self._size))
            if response.error:
                logger.warning("Cannot decode %s icon %s: %s", self._kind, icon_id, response.error)
                return QImage()
            if not response.pixels:
                return QImage()
            return decoded_image(response)
        except Exception:
            self._unavailable = True
            logger.warning("Icon decoding process is unavailable", exc_info=True)
            return QImage()


class _IconSignals(QObject):
    loaded = pyqtSignal(int, QImage)


class _LoadIcon(QRunnable):
    def __init__(self, loader: IconLoader, signals: _IconSignals, icon_id: int) -> None:
        super().__init__()
        self.loader = loader
        self.signals = signals
        self.icon_id = icon_id

    def run(self) -> None:
        self.signals.loaded.emit(self.icon_id, self.loader.load(self.icon_id))


class ItemIconCache(QObject):
    ready = pyqtSignal(int, QImage)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        max_bytes: int = 16 * 1024 * 1024,
        loader: IconLoader | None = None,
    ) -> None:
        super().__init__(parent)
        self._max_bytes = max_bytes
        self._bytes = 0
        self._images: OrderedDict[int, QImage] = OrderedDict()
        self._pending: set[int] = set()
        self._request_priority = 0
        self._missing: set[int] = set()
        self._loader = loader or IconLoader()
        self._signals = _IconSignals(self)
        self._signals.loaded.connect(self._loaded)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    @pyqtSlot()
    def shutdown(self) -> None:
        self._pool.clear()
        icon_process.close()
        self._pool.waitForDone()

    def cached(self, icon_id: int) -> QImage | None:
        image = self._images.get(icon_id)
        if image is not None:
            self._images.move_to_end(icon_id)
        return image

    def request(self, icon_id: int) -> QImage | None:
        image = self.cached(icon_id)
        if image is not None:
            return image
        if icon_id not in self._pending and icon_id not in self._missing:
            self._pending.add(icon_id)
            self._request_priority += 1
            self._pool.start(_LoadIcon(self._loader, self._signals, icon_id), self._request_priority)
        return None

    @pyqtSlot(int, QImage)
    def _loaded(self, icon_id: int, image: QImage) -> None:
        self._pending.discard(icon_id)
        if image.isNull():
            self._missing.add(icon_id)
            return
        self._images[icon_id] = image
        self._bytes += image.sizeInBytes()
        while self._bytes > self._max_bytes and self._images:
            _, evicted = self._images.popitem(last=False)
            self._bytes -= evicted.sizeInBytes()
        self.ready.emit(icon_id, image)


@cache
def item_icon_cache() -> ItemIconCache:
    return _create_cache()


@cache
def class_icon_cache() -> ItemIconCache:
    return _create_cache(IconLoader(kind="class", size=160))


def _create_cache(loader: IconLoader | None = None) -> ItemIconCache:
    app = QCoreApplication.instance()
    icons = ItemIconCache(app, loader=loader)
    if app is not None:
        app.aboutToQuit.connect(icons.shutdown)
    return icons
