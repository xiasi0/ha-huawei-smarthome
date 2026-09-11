"""Shared helpers for generic HA entities backed by product adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.helpers.entity import DeviceInfo

from .device_adapters.api import EntitySpec
from .device_adapters.context import DeviceContext
from .device_registry import device_identifier, profile_configuration_url


def iter_specs(client: Any, platform: str) -> Iterable[tuple[DeviceContext, EntitySpec]]:
    for context in client.protocol_devices.values():
        for spec in context.entity_specs:
            if spec.platform == platform:
                yield context, spec


def device_info(context: DeviceContext) -> DeviceInfo:
    descriptor = context.descriptor
    profile = context.profile or {}
    manufacturer = descriptor.manufacturer or profile.get("manufacturerName")
    model = descriptor.model or profile.get("deviceModel") or descriptor.prod_id
    return DeviceInfo(
        identifiers={device_identifier(descriptor)},
        name=descriptor.name,
        manufacturer=manufacturer,
        model=model,
        sw_version=descriptor.firmware_version,
        configuration_url=profile_configuration_url(descriptor.prod_id),
    )


class AdapterEntityMixin:
    """Common lifecycle and state helpers for every generic HA platform."""

    def _init_adapter_entity(self, context: DeviceContext, spec: EntitySpec) -> None:
        self._device_context = context
        self._spec = spec
        self._attr_unique_id = f"{context.home_id}_{context.dev_id}_{spec.key}"
        self._attr_name = spec.name or spec.key
        self._attr_has_entity_name = True
        self._attr_should_poll = False

    @property
    def device_info(self):
        return device_info(self._device_context)

    @property
    def available(self) -> bool:
        return self._device_context.available

    def _state_value(self, key: str, default: Any = None) -> Any:
        return self._spec.state(self._device_context).get(key, default)

    async def async_added_to_hass(self) -> None:
        self._device_context.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device_context.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()

    async def _run_action(self, name: str, data: Mapping[str, Any]) -> None:
        action = self._spec.actions.get(name)
        if action is None:
            raise ValueError(f"adapter action is unavailable: {name}")
        await action(self._device_context, data)
