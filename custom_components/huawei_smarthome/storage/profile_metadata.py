"""Read-only product metadata from the local Profile cache."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
import logging
from typing import Any, Protocol

from ..const import PROFILE_CDN_BASE_URL, PROFILE_CDN_PATH
from ..hwiotdevices.profile import ProductProfile
from .locking import storage_lock


PROFILE_STORAGE_VERSION = 1
PROFILE_STORAGE_PREFIX = "huawei_smarthome/profiles"
_LOGGER = logging.getLogger(__name__)


class ProductProfileStore(Protocol):
    """Load normalized public Profiles keyed by product ID."""

    async def async_get_profiles(
        self,
        prod_ids: Iterable[str],
    ) -> dict[str, ProductProfile]:
        """Return cached or downloaded Profiles."""

    async def async_get_cached_profiles(
        self,
        prod_ids: Iterable[str],
    ) -> dict[str, ProductProfile]:
        """Return only locally cached Profiles."""


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


class HomeAssistantProductProfileStore:
    """Persist and fetch one public Profile per product ID."""

    def __init__(
        self,
        hass: Any,
        session: Any,
        *,
        store_type: Any | None = None,
    ) -> None:
        if store_type is None:
            from homeassistant.helpers.storage import Store

            store_type = Store
        self._hass = hass
        self._session = session
        self._store_type = store_type
        self._stores: dict[str, Any] = {}

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

    async def async_get_profiles(
        self,
        prod_ids: Iterable[str],
    ) -> dict[str, ProductProfile]:
        """Load unique product Profiles with bounded concurrency."""

        unique = tuple(
            sorted(
                {
                    item.strip()
                    for item in prod_ids
                    if isinstance(item, str) and item.strip()
                }
            )
        )
        cached = await self.async_get_cached_profiles(unique)
        missing = sorted(
            set(unique) - set(cached)
        )
        semaphore = asyncio.Semaphore(8)

        async def load(prod_id: str) -> tuple[str, ProductProfile] | None:
            async with semaphore:
                profile = await self.async_get_profile(prod_id)
                return (prod_id, profile) if profile is not None else None

        results = await asyncio.gather(*(load(prod_id) for prod_id in missing))
        downloaded = {
            prod_id: profile
            for item in results
            if item is not None
            for prod_id, profile in (item,)
        }
        return {**cached, **downloaded}

    async def async_get_cached_profiles(
        self,
        prod_ids: Iterable[str],
    ) -> dict[str, ProductProfile]:
        """Read unique product Profiles without network I/O."""

        unique = sorted(
            {
                item.strip()
                for item in prod_ids
                if isinstance(item, str) and item.strip()
            }
        )
        profiles: dict[str, ProductProfile] = {}
        for prod_id in unique:
            storage_key = profile_storage_key(prod_id)
            async with storage_lock(storage_key):
                raw = await self._store_for_product(prod_id).async_load()
            profile = _profile_from_storage(raw)
            if profile is not None:
                profiles[prod_id] = profile
        return profiles

    async def async_get_profile(self, prod_id: str) -> ProductProfile | None:
        """Load a Profile from Store, fetching the public CDN on a miss."""

        storage_key = profile_storage_key(prod_id)
        async with storage_lock(storage_key):
            store = self._store_for_product(prod_id)
            cached = await store.async_load()
            profile = _profile_from_storage(cached)
            if profile is not None:
                return profile

            url = (
                f"{PROFILE_CDN_BASE_URL}"
                f"{PROFILE_CDN_PATH.format(prod_id=prod_id)}"
            )
            try:
                async with self._session.get(url, timeout=20) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
                    payload = await response.json(content_type=None)
                profile = ProductProfile.from_payload(payload)
            except Exception as error:  # noqa: BLE001 - Profile is optional
                _LOGGER.debug(
                    "Huawei SmartHome Profile unavailable: prod_id=%s error=%s",
                    prod_id,
                    type(error).__name__,
                )
                return None
            await store.async_save({"profile": payload})
            return profile


def _profile_from_storage(value: Any) -> ProductProfile | None:
    if not isinstance(value, Mapping):
        return None
    payload = value.get("profile")
    if not isinstance(payload, Mapping) or not payload.get("prodId"):
        return None
    try:
        return ProductProfile.from_payload(payload)
    except ValueError:
        return None
