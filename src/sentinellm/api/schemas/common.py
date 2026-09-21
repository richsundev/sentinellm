from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

T = TypeVar("T")


def strip_nul(value: Any) -> Any:
    """Removes NUL characters from every string in a JSON-like structure.

    Postgres cannot store U+0000 in a text column; SQLite (the test database)
    can, so a request carrying one only ever failed in production, as a 500.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    return value


class NulStrippingModel(BaseModel):
    """Base for request bodies: every string arrives without NUL characters, and
    no number is NaN or infinite (Python's JSON parser accepts both literals; a
    stored infinity poisons every aggregate and can't be serialised back)."""

    model_config = ConfigDict(allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _strip_nul_characters(cls, data: Any) -> Any:
        return strip_nul(data)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
