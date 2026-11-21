import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from DBDofusUnity.consts import PROTOS_ROOT
from DBDofusUnity.proto_mapper_assembly.controllers import game_mappings
from DBDofusUnity.proto_mapper_assembly.interfaces.dump_cs_message import DumpCSMessage
from DBDofusUnity.proto_mapper_assembly.parsers.protobuf_dump_cs import build_dump_cs_messages_from_pb2
from DBDofusUnity.proto_mapper_assembly.runtime import runtime_store
from DBDofusUnity.proto_mapper_assembly.runtime.runtime_store import RuntimeDataStore
from scripts.mapping import export_signature_overrides
from src.protocol import protocol_game
from utils.singleton import Singleton


@pytest.fixture
def dump_cs(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    tmp_dir = tmp_path_factory.mktemp("parse_types")
    tmp_file = tmp_dir / f"{uuid.uuid4()}.cs"

    def _dump_cs(code: str) -> Path:
        tmp_file.write_text(code, encoding="utf-8")
        return tmp_file

    return _dump_cs


@pytest.fixture
def runtime_data_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RuntimeDataStore:
    monkeypatch.setattr(runtime_store, "RUNTIME_DATA_FILE", tmp_path / "instancied_msg_infos.json")
    monkeypatch.setattr(runtime_store, "ENABLE_MSG_CAPTURE", True)
    monkeypatch.setattr(Singleton, "_instances", {})
    monkeypatch.setattr(protocol_game, "_on_exit", lambda: None)
    return RuntimeDataStore()


@pytest.fixture(scope="session")
def generated_non_obf_messages() -> dict[str, DumpCSMessage]:
    return build_dump_cs_messages_from_pb2(PROTOS_ROOT / "non_obf")


@pytest.fixture
def reuse_generated_non_obf_messages(
    monkeypatch: pytest.MonkeyPatch,
    generated_non_obf_messages: dict[str, DumpCSMessage],
) -> None:
    def load_messages(protos_dir: Path) -> dict[str, DumpCSMessage]:
        assert protos_dir == PROTOS_ROOT / "non_obf"
        return generated_non_obf_messages

    monkeypatch.setattr(game_mappings, "build_dump_cs_messages_from_pb2", load_messages)
    monkeypatch.setattr(export_signature_overrides, "build_dump_cs_messages_from_pb2", load_messages)
