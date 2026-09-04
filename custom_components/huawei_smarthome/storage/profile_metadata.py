"""Read-only product metadata from the local Profile cache."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .locking import storage_lock


PROFILE_STORAGE_VERSION = 1
PROFILE_STORAGE_PREFIX = "huawei_smarthome/profiles"


class ProductMetadataStore(Protocol):
    """Read product metadata without requesting or modeling a Profile."""

    async def async_get_manufacturer_names(
        self,
        prod_ids: Iterable[str],
    ) -> dict[str, str]:
        """Return cached manufacturer names keyed by product ID."""


def profile_storage_key(prod_id: str) -> str:
    """Return the product-id-named Profile Store key."""

    prod_id = prod_id.strip()
    if not prod_id:
        raise ValueError("product id is required")
    if prod_id in {".", ".."} or any(
        char in '<>:"/\\|?*' or ord(char) < 32
        for char in prod_id
    ):
        raise ValueError("product id cannot be used as a storage filename")
    return f"{PROFILE_STORAGE_PREFIX}/{prod_id}.json"


class HomeAssistantProductMetadataStore:
    """Read manufacturer metadata from one local Store per prodId."""

    def __init__(self, hass: Any) -> None:
        from homeassistant.helpers.storage import Store

        self._hass = hass
        self._stores: dict[str, Any] = {}
        self._store_type = Store

    def _store_for_product(self, prod_id: str) -> Any:
        key = profile_storage_key(prod_id)
        store = self._stores.get(key)
        if store is None:
            store = self._store_type(
                self._hass,
                PROFILE_STORAGE_VERSION,
                key,
            )
            self._stores[key] = store
        return store

    async def async_get_manufacturer_names(
        self,
        prod_ids: Iterable[str],
    ) -> dict[str, str]:
        """Read each unique product cache once."""

        names: dict[str, str] = {}
        for prod_id in sorted(
            {
                item.strip()
                for item in prod_ids
                if isinstance(item, str) and item.strip()
            }
        ):
            storage_key = profile_storage_key(prod_id)
            async with storage_lock(storage_key):
                raw = await self._store_for_product(prod_id).async_load()
            manufacturer_name = manufacturer_name_from_storage(raw)
            if manufacturer_name is not None:
                names[prod_id] = manufacturer_name
        return names


def manufacturer_name_from_storage(value: Any) -> str | None:
    """Extract manufacturer_name from supported local Profile cache shapes."""

    candidates: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        candidates.append(value)
        for key in ("profile", "raw_payload", "json"):
            child = value.get(key)
            if isinstance(child, Mapping):
                candidates.append(child)
    for candidate in candidates:
        for key in ("manufacturer_name", "manufacturerName"):
            name = candidate.get(key)
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None
