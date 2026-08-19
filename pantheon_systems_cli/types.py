# It uses TypeAlias explicitly because it is recursive.
from typing import TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
