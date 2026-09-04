"""Home Assistant integration entry point for Huawei SmartHome."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import CONF_ACCOUNT, CONF_SELECTED_HOME_IDS, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Huawei SmartHome integration domain."""

    del hass, config
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up one Huawei SmartHome account."""

    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api.client import SmartHomeDiscoveryApi
    from .api.transport import AiohttpHttpTransport
    from .client import HuaweiSmartHomeClient
    from .device_registry import register_devices
    from .errors import ReauthenticationRequired
    from .storage.credentials import HomeAssistantCredentialStore
    from .storage.profile_metadata import HomeAssistantProductMetadataStore
    from .storage.state import HomeAssistantAccountStateStore

    session = async_get_clientsession(hass)
    selected_home_ids = entry.options.get(
        CONF_SELECTED_HOME_IDS,
        entry.data.get(CONF_SELECTED_HOME_IDS, []),
    )
    if not isinstance(selected_home_ids, list):
        selected_home_ids = []
    smart_home_api = SmartHomeDiscoveryApi(
        transport=AiohttpHttpTransport(session)
    )
    client = HuaweiSmartHomeClient(
        account=str(entry.data.get(CONF_ACCOUNT, "")),
        identity_fingerprint=str(entry.data.get("identity_fingerprint", "")),
        selected_home_ids=frozenset(
            value
            for value in selected_home_ids
            if isinstance(value, str) and value
        ),
        credential_store=HomeAssistantCredentialStore(hass),
        state_store=HomeAssistantAccountStateStore(hass, entry.entry_id),
        api=smart_home_api,
        metadata_store=HomeAssistantProductMetadataStore(hass),
    )
    account = entry.data.get(CONF_ACCOUNT)
    if isinstance(account, str) and account.strip() and entry.title != account.strip():
        hass.config_entries.async_update_entry(
            entry,
            title=account.strip(),
        )
    entry.runtime_data = client
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    try:
        await client.async_start()
    except ReauthenticationRequired as error:
        await client.async_stop()
        raise ConfigEntryAuthFailed(
            "Huawei SmartHome authentication required"
        ) from error
    except Exception as error:
        await client.async_stop()
        raise ConfigEntryNotReady(
            "Huawei SmartHome could not be initialized"
        ) from error
    register_devices(
        hass,
        entry.entry_id,
        client.devices.values(),
        excluded_device_ids=client.excluded_device_ids,
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload one Huawei SmartHome account."""

    del hass
    await entry.runtime_data.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove credentials and state while retaining client identity."""

    from .storage.credentials import HomeAssistantCredentialStore
    from .storage.state import HomeAssistantAccountStateStore

    account = entry.data.get("account")
    if isinstance(account, str) and account:
        await HomeAssistantCredentialStore(hass).async_remove(account)
    await HomeAssistantAccountStateStore(hass, entry.entry_id).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Remove one device from the local HA projection for this account."""

    account = config_entry.data.get(CONF_ACCOUNT)
    if not isinstance(account, str) or not account.strip():
        return False
    identifiers = tuple(
        value
        for domain, value in device_entry.identifiers
        if domain == DOMAIN
    )
    if len(identifiers) != 1:
        return False
    config_entries = getattr(device_entry, "config_entries", ())
    if config_entries and config_entry.entry_id not in config_entries:
        return False
    if len(config_entries) > 1:
        return False

    from .storage.credentials import HomeAssistantCredentialStore
    from homeassistant.helpers import device_registry

    await HomeAssistantCredentialStore(hass).async_add_device_exclusion(
        account,
        identifiers[0],
    )
    device_registry.async_get(hass).async_remove_device(device_entry.id)
    return True


__all__ = ["DOMAIN"]


async def _async_options_updated(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Reload discovery when the selected remote homes change."""

    await hass.config_entries.async_reload(entry.entry_id)
