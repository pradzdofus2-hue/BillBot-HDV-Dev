from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N


def get_item_display(item_id: int) -> tuple[str, int | None]:
    item = DataReader().item_by_id.get(item_id)
    fallback = f"Item {item_id}"
    if item is None:
        return fallback, None
    name = I18N().name_by_id.get(item.nameId, fallback) if item.nameId else fallback
    return name, item.iconId
