"""V0DE 华为 Vision 智慧屏 3 (QINL-370A), observed cloud states only.

Profile: device/guide/V0DE/V0DE.json on smarthome-drcn.dbankcdn.com.
No controls are inferred from another model's LAN or generalcommand protocol.
"""

from .api import EntitySpec
from .context import DeviceContext
from . import vision_states


class ProductV0DEAdapter:
    prod_id = "V0DE"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        return vision_states.entities(context)


ADAPTER = ProductV0DEAdapter()
