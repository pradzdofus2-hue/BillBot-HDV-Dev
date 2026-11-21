from dataclasses import dataclass
from math import ceil, floor

from DBDofusUnity.dofus_unity_reader.models.datas.map_positions_root import MapInformationRootItem
from PyQt6.QtCore import QRectF, Qt, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.core.signals.world_signals import WorldSignals
from src.gui.services.worldmap_tiles import TILE_SIZE, worldmap_tile_cache
from src.gui.utils.profiling import profiled_slot

type Coord = tuple[int, int]
type RGBColor = tuple[int, int, int]

CELL_SIZE: int = 50
LIMIT_GRID = 8
MAX_PATH_EDGES = 500

WIDTH_AROUND_CURRENT_MAP = CELL_SIZE * LIMIT_GRID * 2
HEIGHT_AROUND_CURRENT_MAP = CELL_SIZE * LIMIT_GRID * 2


class SquareMap(QGraphicsRectItem):
    DEFAULT = Qt.GlobalColor.transparent

    def __init__(self):
        self.colors_by_map_id: dict[int, RGBColor] = {}
        rect = QRectF(0, 0, CELL_SIZE, CELL_SIZE)
        super().__init__(rect)
        self.setBrush(self.DEFAULT)
        self.setPen(QPen(Qt.PenStyle.NoPen))

    def add_color(self, map_id: int, color: RGBColor):
        self.colors_by_map_id[map_id] = color
        self.update()

    def reset_color(self):
        self.colors_by_map_id.clear()
        self.setBrush(SquareMap.DEFAULT)
        self.update()

    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionGraphicsItem | None,
        widget: QWidget | None = None,
    ) -> None:
        if painter is None or option is None:
            return
        if len(self.colors_by_map_id) == 0:
            return super().paint(painter, option, widget)

        all_colors = set(self.colors_by_map_id.values())
        divided_height = floor(self.boundingRect().height() / len(all_colors))
        for index, color in enumerate(all_colors):
            rect = QRectF(
                self.boundingRect().x(),
                self.boundingRect().y() + divided_height * index,
                self.boundingRect().width(),
                divided_height,
            )
            painter.fillRect(rect, QColor(*color, 89))


class MapCircle(QGraphicsEllipseItem):
    def __init__(self) -> None:
        super().__init__(
            CELL_SIZE // 4,
            CELL_SIZE // 4,
            CELL_SIZE // 2,
            CELL_SIZE // 2,
        )
        self.setZValue(1)
        self.setBrush(Qt.GlobalColor.red)


@dataclass
class CurrMapInfo:
    state: MapCircle
    map_pos: MapInformationRootItem


class MapWorldView(QGraphicsView):
    def __init__(self, world_signals: WorldSignals | None = None, debug: bool = False) -> None:
        super().__init__()
        self.debug = debug
        self.world_signals = world_signals
        self.curr_map_info: CurrMapInfo | None = None
        self.line_items: list[QGraphicsLineItem] = []
        self._scene: QGraphicsScene = QGraphicsScene()
        self.square_by_coord: dict[Coord, SquareMap] = {}
        self._colors_by_map_id: dict[int, tuple[MapInformationRootItem, RGBColor]] = {}
        self._path: list[tuple[MapInformationRootItem, MapInformationRootItem]] = []
        self._current_map: MapInformationRootItem | None = None
        self._render_dirty = False
        self._tiles = worldmap_tile_cache()
        viewport = self.viewport()
        if viewport is not None:
            self._tiles.changed.connect(viewport.update)
        self._scene.setSceneRect(
            -WIDTH_AROUND_CURRENT_MAP / 2,
            -HEIGHT_AROUND_CURRENT_MAP / 2,
            WIDTH_AROUND_CURRENT_MAP,
            HEIGHT_AROUND_CURRENT_MAP,
        )

        self.setStyleSheet("border: 0px")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setScene(self._scene)
        self._fit_window()

        if self.world_signals:
            self.world_signals.color_pos.connect(profiled_slot(self.on_color_pos))
            self.world_signals.color_pos_batch.connect(profiled_slot(self.on_color_pos_batch))
            self.world_signals.arrow_pos.connect(profiled_slot(self.on_arrow_pos))
            self.world_signals.arrow_pos_batch.connect(profiled_slot(self.on_arrow_pos_batch))
            self.world_signals.reset_weight.connect(profiled_slot(self.on_reset_weight))
            self.world_signals.reset_path.connect(profiled_slot(self.on_reset_path))
            self.world_signals.curr_map_pos.connect(profiled_slot(self.on_curr_map))

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._fit_window()

    def _fit_window(self) -> None:
        self.fitInView(self._scene.sceneRect(), mode=Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(self._scene.sceneRect().center())

    def drawBackground(self, painter: QPainter | None, rect: QRectF) -> None:
        if painter is None:
            return
        painter.fillRect(rect, self.palette().base())
        self._draw_worldmap(painter, rect)

    def _draw_worldmap(self, painter: QPainter, window: QRectF) -> None:
        if self._current_map is None or self._current_map.worldMap < 0:
            return
        world_id = self._current_map.worldMap
        world = self._tiles.geometry(world_id)
        if world is None:
            return
        scale_x, scale_y = CELL_SIZE / world.mapWidth, CELL_SIZE / world.mapHeight
        columns = ceil(world.totalWidth / TILE_SIZE)
        rows = ceil(world.totalHeight / TILE_SIZE)
        first_col = max(0, floor((window.left() / scale_x + world.origineX) / TILE_SIZE))
        last_col = min(columns - 1, floor((window.right() / scale_x + world.origineX) / TILE_SIZE))
        first_row = max(0, floor((window.top() / scale_y + world.origineY) / TILE_SIZE))
        last_row = min(rows - 1, floor((window.bottom() / scale_y + world.origineY) / TILE_SIZE))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for row in range(first_row, last_row + 1):
            for column in range(first_col, last_col + 1):
                number = row * columns + column + 1
                image = self._tiles.request(world_id, number)
                if image is None:
                    continue
                width = min(image.width(), world.totalWidth - column * TILE_SIZE)
                height = min(image.height(), world.totalHeight - row * TILE_SIZE)
                target = QRectF(
                    (column * TILE_SIZE - world.origineX) * scale_x,
                    (row * TILE_SIZE - world.origineY) * scale_y,
                    width * scale_x,
                    height * scale_y,
                )
                painter.drawImage(target, image, QRectF(0, 0, width, height))
        painter.restore()

    def _same_world(self, map_pos: MapInformationRootItem) -> bool:
        return self._current_map is None or map_pos.worldMap == self._current_map.worldMap

    def showEvent(self, event: QShowEvent | None) -> None:
        if self._render_dirty:
            self._rebuild_scene()
        super().showEvent(event)

    @pyqtSlot(MapInformationRootItem)
    def on_curr_map(self, map_pos: MapInformationRootItem):
        changed_world = self._current_map is None or self._current_map.worldMap != map_pos.worldMap
        self._current_map = map_pos
        if changed_world:
            self._colors_by_map_id = {
                key: value for key, value in self._colors_by_map_id.items() if self._same_world(value[0])
            }
            self._path = [(start, end) for start, end in self._path if self._same_world(start) and self._same_world(end)]
        if not self.isVisible():
            self._render_dirty = True
            return
        if changed_world:
            self._rebuild_scene()
            return
        self._render_current_map(map_pos)

    def _render_current_map(self, map_pos: MapInformationRootItem) -> None:
        coord = map_pos.posX, map_pos.posY
        if self.curr_map_info is None:
            state = MapCircle()
            self._scene.addItem(state)
            self.curr_map_info = CurrMapInfo(state=state, map_pos=map_pos)
        else:
            self.curr_map_info.map_pos = map_pos

        x, y = self.get_pos_by_coord(coord)
        self.curr_map_info.state.setPos(x, y)
        center = self.curr_map_info.state.sceneBoundingRect().center()
        left = center.x() - WIDTH_AROUND_CURRENT_MAP / 2
        top = center.y() - HEIGHT_AROUND_CURRENT_MAP / 2
        self._scene.setSceneRect(QRectF(left, top, WIDTH_AROUND_CURRENT_MAP, HEIGHT_AROUND_CURRENT_MAP))
        self._fit_window()
        self._prune_outside_current_window()

    def get_or_create_map(self, map_pos: MapInformationRootItem) -> SquareMap:
        coord = map_pos.posX, map_pos.posY
        if coord not in self.square_by_coord:
            square = SquareMap()
            x, y = self.get_pos_by_coord(coord)
            square.setPos(x, y)
            self.square_by_coord[coord] = square
            self._scene.addItem(square)

            if self.debug:
                text = QGraphicsTextItem(f"{coord[0]},{coord[1]}")
                text.setPos(x, y)
                text.setZValue(2)
                self._scene.addItem(text)

        return self.square_by_coord[coord]

    def get_pos_by_coord(self, coord: Coord) -> tuple[int, int]:
        return coord[0] * CELL_SIZE, coord[1] * CELL_SIZE

    @pyqtSlot(MapInformationRootItem, tuple)
    def on_color_pos(self, map_pos: MapInformationRootItem, color: RGBColor):
        if not self._same_world(map_pos):
            return
        self._colors_by_map_id[map_pos.id] = (map_pos, color)
        if not self.isVisible():
            self._render_dirty = True
            return
        square_cell = self.get_or_create_map(map_pos)
        square_cell.add_color(map_pos.id, color)

    @pyqtSlot(list)
    def on_color_pos_batch(self, items: list[tuple[MapInformationRootItem, RGBColor]]):
        items = [(map_pos, color) for map_pos, color in items if self._same_world(map_pos)]
        for map_pos, color in items:
            self._colors_by_map_id[map_pos.id] = (map_pos, color)
        if not self.isVisible():
            self._render_dirty = True
            return
        self.setUpdatesEnabled(False)
        for map_pos, color in items:
            square_cell = self.get_or_create_map(map_pos)
            square_cell.add_color(map_pos.id, color)
        self.setUpdatesEnabled(True)

    @pyqtSlot(MapInformationRootItem, MapInformationRootItem)
    def on_arrow_pos(self, map_pos_start: MapInformationRootItem, map_pos_end: MapInformationRootItem):
        if not self._same_world(map_pos_start) or not self._same_world(map_pos_end):
            return
        self._path.append((map_pos_start, map_pos_end))
        self._trim_path()
        if not self.isVisible():
            self._render_dirty = True
            return
        self._render_arrow(map_pos_start, map_pos_end)

    def _render_arrow(
        self, map_pos_start: MapInformationRootItem, map_pos_end: MapInformationRootItem
    ) -> None:
        start_square = self.get_or_create_map(map_pos_start)
        end_square = self.get_or_create_map(map_pos_end)
        line_item = QGraphicsLineItem(
            start_square.x() + CELL_SIZE / 2,
            start_square.y() + CELL_SIZE / 2,
            end_square.x() + CELL_SIZE / 2,
            end_square.y() + CELL_SIZE / 2,
        )
        pen = QPen(Qt.GlobalColor.green)
        pen.setWidth(2)
        line_item.setPen(pen)
        self.line_items.append(line_item)
        self._scene.addItem(line_item)

    @pyqtSlot(list)
    def on_arrow_pos_batch(self, items: list[tuple[MapInformationRootItem, MapInformationRootItem]]):
        items = [(start, end) for start, end in items if self._same_world(start) and self._same_world(end)]
        self._path.extend(items)
        self._trim_path()
        if not self.isVisible():
            self._render_dirty = True
            return
        self.setUpdatesEnabled(False)
        for map_pos_start, map_pos_end in items:
            self._render_arrow(map_pos_start, map_pos_end)
        self.setUpdatesEnabled(True)

    @pyqtSlot()
    def on_reset_path(self):
        self._path.clear()
        if not self.isVisible():
            self._render_dirty = True
            return
        self.setUpdatesEnabled(False)
        while self.line_items:
            line_item = self.line_items.pop()
            self._scene.removeItem(line_item)
        self.setUpdatesEnabled(True)

    @pyqtSlot()
    def on_reset_weight(self):
        self._colors_by_map_id.clear()
        if not self.isVisible():
            self._render_dirty = True
            return
        self.setUpdatesEnabled(False)
        for square in self.square_by_coord.values():
            square.reset_color()
        self.setUpdatesEnabled(True)

    def _rebuild_scene(self) -> None:
        self._scene.clear()
        self.curr_map_info = None
        self.line_items.clear()
        self.square_by_coord.clear()
        for map_pos, color in self._colors_by_map_id.values():
            self.get_or_create_map(map_pos).add_color(map_pos.id, color)
        for map_pos_start, map_pos_end in self._path:
            self._render_arrow(map_pos_start, map_pos_end)
        if self._current_map is not None:
            self._render_current_map(self._current_map)
        self._render_dirty = False

    def _trim_path(self) -> None:
        overflow = len(self._path) - MAX_PATH_EDGES
        if overflow <= 0:
            return
        del self._path[:overflow]
        while len(self.line_items) > MAX_PATH_EDGES:
            self._scene.removeItem(self.line_items.pop(0))

    def _prune_outside_current_window(self) -> None:
        if self._current_map is None:
            return
        current_x, current_y = self._current_map.posX, self._current_map.posY
        kept_coords = {
            coord
            for coord in self.square_by_coord
            if -LIMIT_GRID <= coord[0] - current_x < LIMIT_GRID
            and -LIMIT_GRID <= coord[1] - current_y < LIMIT_GRID
        }
        for coord in set(self.square_by_coord) - kept_coords:
            self._scene.removeItem(self.square_by_coord.pop(coord))
        self._colors_by_map_id = {
            map_id: value
            for map_id, value in self._colors_by_map_id.items()
            if (value[0].posX, value[0].posY) in kept_coords
        }
