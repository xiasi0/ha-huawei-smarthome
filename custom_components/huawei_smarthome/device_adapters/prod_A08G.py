"""A08G 美的智能电风扇, read-only until its model-specific writes are verified.

The public Profile describes FTS30-16BR with fan.gear=1..4, while the actual
5600117P reports fan.speed=5 and no gear. Never clamp this to four speeds or
write the other model's gear field. The power schema also warns that some
models only support remote off or are read-only, so no action is exposed.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import number, sensor


class ProductA08GAdapter:
    prod_id = "A08G"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()
        entities = []
        if context.has_service("switch"):
            entities.append(sensor("power_state", "电源状态", "switch", "on", kind="bool"))
        if context.has_service("mode"):
            entities.append(sensor("mode", "风类", "mode", "mode", kind="enum"))
        if context.has_service("fan"):
            def speed(device: DeviceContext):
                attr = "speed" if device.value("fan", "speed") is not None else "gear"
                return {"native_value": number(device.value("fan", attr)),
                        "extra_state_attributes": {"source_field": f"fan.{attr}"}}

            entities.append(EntitySpec(platform="sensor", key="speed", name="风速原始值", state=speed))
            entities.append(sensor("oscillation", "摇头状态", "fan", "angle", kind="enum"))
        return tuple(entities)


ADAPTER = ProductA08GAdapter()
