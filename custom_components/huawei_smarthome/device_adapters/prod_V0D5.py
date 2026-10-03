"""V0D5 华为智慧屏 S86 (KEPL-280D), observed cloud states only.

Profile: device/guide/V0D5/V0D5.json on smarthome-drcn.dbankcdn.com.
No remote-control token, network identifiers, media metadata or LAN commands.
"""

from .api import EntitySpec
from .context import DeviceContext
from . import vision_states


class ProductV0D5Adapter:
    prod_id = "V0D5"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        return vision_states.entities(context)


ADAPTER = ProductV0D5Adapter()
