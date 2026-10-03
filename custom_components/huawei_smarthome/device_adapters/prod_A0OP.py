"""A0OP 酷宅科技智能墙壁开关, single channel.

The product's own Profile declares switch.on (0 off / 1 on, GPR).
Only this relay is exposed; no OTA or inferred multi-channel commands.
State checked against a real device's cloud shadow; writes await online testing.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import field, switch


class ProductA0OPAdapter:
    prod_id = "A0OP"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if not field(context, "switch", "on"):
            return ()
        return (switch(context, "power", "开关", "switch"),)


ADAPTER = ProductA0OPAdapter()
