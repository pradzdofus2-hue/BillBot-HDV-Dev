import re
from math import ceil, isfinite
from pathlib import Path
from struct import unpack_from
from typing import Any

import msgspec
from PIL.Image import Image
lazy from UnityPy.files.ObjectReader import ObjectReader

from DBDofusUnity.dofus_unity_reader.bundle_export import iter_bundle_data, load_bundle
from DBDofusUnity.dofus_unity_reader.models.datas.worldmapsroot import Worldmapsroot

TILE_SIZE = 1024


class ContainerPointer(msgspec.Struct):
    m_FileID: int
    m_PathID: int


class ContainerEntry(msgspec.Struct):
    asset: ContainerPointer


class BundlePaths(msgspec.Struct):
    m_Container: list[tuple[str, ContainerEntry]]


def catalog_address(catalog: bytes, guid: str) -> tuple[int, float, int]:
    if re.fullmatch(r"[0-9a-f]{32}", guid) is None:
        raise ValueError(f"Invalid worldmap asset GUID: {guid}")
    needle = b"\x20\x00\x00\x00" + guid.encode("ascii")
    position = catalog.find(needle)
    if position < 8 or catalog.find(needle, position + 1) != -1:
        raise ValueError(f"Worldmap GUID must occur exactly once in the catalog: {guid}")

    def uint(offset: int) -> int:
        if offset < 0 or offset + 4 > len(catalog):
            raise ValueError(f"Invalid catalog reference for {guid}")
        return unpack_from("<I", catalog, offset)[0]

    def string(offset: int) -> str:
        length = uint(offset - 4)
        if offset + length > len(catalog):
            raise ValueError(f"Truncated catalog string for {guid}")
        return catalog[offset : offset + length].decode("utf-8")

    suffix = string(uint(position - 8))
    prefix = uint(position - 4)
    if uint(prefix + 4) != 0xFFFFFFFF:
        raise ValueError(f"Unsupported worldmap catalog prefix for {guid}")
    address = f"{string(uint(prefix))}/{suffix}"
    match = re.fullmatch(r"worldmaps/([1-9]\d*)/(\d+(?:\.\d+)?)/([1-9]\d*)\.jpg", address)
    if match is None:
        raise ValueError(f"Invalid worldmap address: {address}")
    return int(match[1]), float(match[2]), int(match[3])


class WorldMapBundleReader:
    def __init__(self, game_dir: Path) -> None:
        self._game_dir = game_dir
        self._content = game_dir / "Dofus_Data/StreamingAssets/Content"
        metadata = list(
            iter_bundle_data(
                self._content / "Data/data_assets_worldmapsdataroot.asset.bundle",
                names={"WorldMapsDataRoot"},
                game_dir=game_dir,
            )
        )
        if len(metadata) != 1:
            raise ValueError("Expected exactly one WorldMapsDataRoot")
        self.worlds = msgspec.convert(metadata[0][1], type=Worldmapsroot)
        self._world_by_id = {world.id: world for world in self.worlds}
        if len(self._world_by_id) != len(self.worlds):
            raise ValueError("Duplicate worldmap geometry")
        for world in self.worlds:
            if (
                world.id <= 0
                or world.totalWidth <= 0
                or world.totalHeight <= 0
                or not isfinite(world.mapWidth)
                or not isfinite(world.mapHeight)
                or world.mapWidth <= 0
                or world.mapHeight <= 0
            ):
                raise ValueError(f"Invalid worldmap geometry: {world.id}")
        self._sprites: dict[tuple[int, int], ObjectReader[Any]] | None = None

    def _load_sprites(self) -> dict[tuple[int, int], ObjectReader[Any]]:
        source = self._content / "Picto/Worldmaps"
        catalog = (source / "catalog_1.0.bin").read_bytes()
        environment = load_bundle(source / "worldmap_assets_.bundle", game_dir=self._game_dir)
        paths: dict[tuple[int, int], str] = {}
        for obj in environment.objects:
            if obj.type.name != "AssetBundle":
                continue
            bundle = msgspec.convert(obj.parse_as_dict(), type=BundlePaths)
            for guid, entry in bundle.m_Container:
                if entry.asset.m_FileID == 0:
                    paths[id(obj.assets_file), entry.asset.m_PathID] = guid
        sprites: dict[tuple[int, int], ObjectReader[Any]] = {}
        for obj in environment.objects:
            if obj.type.name != "Sprite":
                continue
            world_id, zoom, number = catalog_address(catalog, paths[id(obj.assets_file), obj.path_id])
            if zoom != 1:
                continue
            world = self._world_by_id[world_id]
            count = ceil(world.totalWidth / TILE_SIZE) * ceil(world.totalHeight / TILE_SIZE)
            if (world_id, number) in sprites or number > count:
                raise ValueError(f"Invalid worldmap tile: {world_id}/{number}")
            sprites[world_id, number] = obj
        if not sprites:
            raise ValueError("No worldmap sprites found")
        return sprites

    def read(self, world_id: int, number: int) -> Image | None:
        if self._sprites is None:
            self._sprites = self._load_sprites()
        sprite = self._sprites.get((world_id, number))
        if sprite is None:
            return None
        try:
            image = sprite.parse_as_object().image.convert("RGBA")
            if not (0 < image.width <= TILE_SIZE and 0 < image.height <= TILE_SIZE):
                raise ValueError(f"Invalid tile dimensions: {world_id}/{number}")
            return image
        finally:
            sprite.assets_file._cache.clear()
