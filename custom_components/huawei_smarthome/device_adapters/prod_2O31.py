"""WSERD24-DA-1.5/35 roller blind: open/close/stop and position.

Firmware 1.4.6 reports current as closure percentage: 100=closed, 0=open.
Inverse current mapping verified on one device at full open and 25% open;
initial fully closed state also confirmed. No optimistic state updates.
Target uses opening percentage per Profile (100=open, 0=closed).
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, TYPE_CHECKING
from .api import EntitySpec
if TYPE_CHECKING:
    from .context import DeviceContext


def _field(context: DeviceContext, sid: str, key: str) -> Mapping[str, Any]:
    for service in (context.profile or {}).get('services', ()):
        if isinstance(service, Mapping) and service.get('serviceId') == sid:
            for field in service.get('characteristics', ()):
                if isinstance(field, Mapping) and field.get('characteristicName') == key:
                    return field
    return {}


def _integer(raw: Any) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _state(context: DeviceContext) -> Mapping[str, Any]:
    current = _integer(context.value('opener', 'current'))
    position = 100 - current if current is not None and 0 <= current <= 100 else None
    return {'current_position': position, 'is_closed': None if position is None else position == 0}


async def _send(context: DeviceContext, sid: str, key: str, value: int) -> None:
    field = _field(context, sid, key)
    if not context.available or 'W' not in str(field.get('method', '')):
        raise ValueError('Device offline or field not writable')
    enums = field.get('enumList')
    if enums and str(value) not in {str(item.get('enumVal')) for item in enums if isinstance(item, Mapping)}:
        raise ValueError('Value not allowed by Profile enum')
    if field.get('characteristicType') == 'int':
        low = float(field.get('min', 0)); high = float(field.get('max', 100))
        step = float(field.get('step', 1))
        if not low <= value <= high or step <= 0 or abs((value-low)/step - round((value-low)/step)) > 1e-8:
            raise ValueError('Value outside Profile range or step')
    await context.async_send_service(sid, {key: value})


async def _open(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await _send(context, 'action', 'action', 1)


async def _close(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await _send(context, 'action', 'action', 0)


async def _stop(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await _send(context, 'action', 'action', 2)


async def _position(context: DeviceContext, data: Mapping[str, Any]) -> None:
    position = _integer(data.get('position'))
    if position is None or not 0 <= position <= 100:
        raise ValueError('Position must be an integer from 0 to 100')
    await _send(context, 'opener', 'target', position)


class Product2O31Adapter:
    prod_id = '2O31'

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.prod_id != self.prod_id or not context.profile:
            return ()
        actions = {}
        if 'W' in str(_field(context, 'action', 'action').get('method', '')):
            actions.update(open=_open, close=_close, stop=_stop)
        if 'W' in str(_field(context, 'opener', 'target').get('method', '')):
            actions['set_position'] = _position
        if not actions:
            return ()
        return (EntitySpec(platform='cover', key='blind', name='卷帘', state=_state,
                           metadata={'device_class': 'shade'}, actions=actions),)


ADAPTER = Product2O31Adapter()
