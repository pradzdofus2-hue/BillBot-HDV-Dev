import sys
from pathlib import Path
from typing import Literal

import msgspec

from DBDofusUnity.dofus_unity_reader.models.datas.worldmapsroot import Worldmapsroot


class IconRequest(msgspec.Struct):
    game_dir: str
    kind: Literal["item", "class", "worldmap"]
    icon_id: int
    size: int
    world_id: int = 0


class IconResponse(msgspec.Struct):
    width: int = 0
    height: int = 0
    pixels: bytes = b""
    error: str | None = None
    worldmaps: Worldmapsroot | None = None


def main() -> None:
    from DBDofusUnity.dofus_unity_reader.data_center.item_icon_reader import IconBundleReader
    from DBDofusUnity.dofus_unity_reader.data_center.worldmap_reader import WorldMapBundleReader

    readers: dict[tuple[str, str], IconBundleReader | WorldMapBundleReader | IconResponse] = {}
    for line in sys.stdin.buffer:
        try:
            request = msgspec.json.decode(line, type=IconRequest)
            key = (request.game_dir, request.kind)
            reader = readers.get(key)
            if reader is None:
                try:
                    reader = (
                        WorldMapBundleReader(Path(request.game_dir)) if request.kind == "worldmap"
                        else IconBundleReader(Path(request.game_dir), request.kind)
                    )
                except Exception as error:
                    reader = IconResponse(error=f"{type(error).__name__}: {error}")
                readers[key] = reader
            if isinstance(reader, IconResponse):
                response = reader
            elif isinstance(reader, WorldMapBundleReader) and request.icon_id == 0:
                response = IconResponse(worldmaps=reader.worlds)
            else:
                image = (
                    reader.read(request.world_id, request.icon_id) if isinstance(reader, WorldMapBundleReader)
                    else reader.read(request.icon_id)
                )
                response = IconResponse()
                if image is not None:
                    image.thumbnail((request.size, request.size))
                    response = IconResponse(image.width, image.height, image.tobytes())
        except Exception as error:
            response = IconResponse(error=f"{type(error).__name__}: {error}")
        sys.stdout.buffer.write(msgspec.json.encode(response) + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
