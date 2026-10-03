"""Offline regression tests using minimal synthetic Profile/state fragments.

Run: python -m unittest discover -s tests -p test_household_adapters.py
No account, device identifiers, complete Profiles or network calls are used.
"""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "vendor" if (ROOT / "app" / "vendor").exists() else ROOT))
from custom_components.huawei_smarthome.device_adapters.context import DeviceContext
from custom_components.huawei_smarthome.domain.models import RemoteDeviceDescriptor, RemoteServiceState


def definition(name, **kwargs):
    return {"characteristicName": name, **kwargs}


def enums(*labels):
    return [{"enumVal": str(value), "descCh": label} for value, label in labels]


def context(pid, definitions, states=None):
    adapter = importlib.import_module(
        f"custom_components.huawei_smarthome.device_adapters.prod_{pid}").ADAPTER
    profile = {"prodId": pid, "services": [
        {"serviceId": sid, "characteristics": attrs} for sid, attrs in definitions.items()
    ]}
    descriptor = RemoteDeviceDescriptor(home_id="test", dev_id="test", name="test",
                                        prod_id=pid, service_states={
        sid: RemoteServiceState(sid=sid, data=data) for sid, data in (states or {}).items()
    })
    result = DeviceContext(descriptor, profile, Mock(), adapter)
    result.async_send_service = AsyncMock()
    return result


def specs(device):
    return {spec.key: spec for spec in device.entity_specs}


class HouseholdAdaptersTest(unittest.IsolatedAsyncioTestCase):
    async def test_opple_native_brightness_and_limits(self):
        device = context("20I0", {
            "switch": [definition("on", method="RW")],
            "brightness": [definition("brightness", method="RW", min=3, max=255)],
            "cct": [definition("colorTemperature", method="RW", min=3000, max=5000)],
            "lightMode": [definition("mode", method="RW", enumList=enums((1, "阅读"), (2, "书写")))],
        }, {"brightness": {"brightness": 128}, "switch": {"on": 0}})
        items = specs(device)
        self.assertEqual(items["brightness"].state(device)["native_value"], 128)
        self.assertNotIn("unit", items["brightness"].metadata)
        self.assertEqual(items["color_temp"].metadata, {"unit": "K", "min": 3000, "max": 5000, "step": 1})
        await items["brightness"].actions["set_value"](device, {"value": 255})
        device.async_send_service.assert_awaited_with("brightness", {"brightness": 255})
        for value in [2, 256, 3.5, float("nan"), float("inf"), True, None, "bad"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                await items["brightness"].actions["set_value"](device, {"value": value})
        self.assertEqual(device.async_send_service.await_count, 1)
        await items["light_mode"].actions["select_option"](device, {"option": "书写"})
        device.async_send_service.assert_awaited_with("lightMode", {"mode": 2})
        self.assertIsNone(items["light_mode"].state(device)["current_option"])
        with self.assertRaises(ValueError):
            await items["light_mode"].actions["select_option"](device, {"option": "not-a-mode"})

    async def test_dalen_backlight_preserves_sibling(self):
        definitions = {"backlight": [
            definition("on", permission="GPR"),
            definition("brightness", permission="GPR", enumList=enums((0, "low"), (1, "middle"), (2, "high"))),
        ]}
        device = context("2J6Y", definitions, {"backlight": {"on": 0, "brightness": 2}})
        items = specs(device)
        await items["night_light"].actions["turn_on"](device, {})
        device.async_send_service.assert_awaited_with("backlight", {"on": 1, "brightness": 2})
        await items["night_brightness"].actions["select_option"](device, {"option": "middle"})
        device.async_send_service.assert_awaited_with("backlight", {"brightness": 1, "on": 0})
        missing = context("2J6Y", definitions)
        for key, action, data in [("night_light", "turn_on", {}),
                                  ("night_brightness", "select_option", {"option": "low"})]:
            with self.assertRaises(ValueError):
                await specs(missing)[key].actions[action](missing, data)
        missing.async_send_service.assert_not_awaited()

    async def test_dalen_limits_and_absent_cct(self):
        device = context("2J6Y", {"brightness": [definition("brightness", permission="GPR", min=0, max=100, step=1)]})
        item = specs(device)["brightness"]
        self.assertEqual(item.metadata, {"unit": "%", "min": 0, "max": 100, "step": 1})
        self.assertNotIn("color_temp", specs(device))
        await item.actions["set_value"](device, {"value": 0})
        device.async_send_service.assert_awaited_with("brightness", {"brightness": 0})

    async def test_switch_strict_unknown_and_commands(self):
        device = context("A0OP", {"switch": [definition("on", permission="GPR")]})
        item = specs(device)["power"]
        self.assertIsNone(item.state(device)["is_on"])
        for raw, expected in [("0", False), (1, True), (2, None), ("garbage", None)]:
            device._state["switch"] = {"on": raw}
            self.assertIs(item.state(device)["is_on"], expected)
        await item.actions["turn_on"](device, {})
        device.async_send_service.assert_awaited_with("switch", {"on": 1})
        await item.actions["turn_off"](device, {})
        device.async_send_service.assert_awaited_with("switch", {"on": 0})

    def test_readonly_permission_overrides_legacy_write(self):
        device = context("A0OP", {"switch": [definition("on", permission="GR", method="RW")]})
        self.assertEqual(specs(device)["power"].platform, "binary_sensor")
        self.assertFalse(specs(device)["power"].actions)

    def test_thermometer_has_no_inferred_divisor(self):
        device = context("A2LW", {sid: [definition("current", permission="GR")]
                                  for sid in ["temperature", "humidity"]},
                         {"temperature": {"current": 28}, "humidity": {"current": 43}})
        items = specs(device)
        self.assertEqual(items["temperature"].state(device)["native_value"], 28)
        self.assertEqual(items["humidity"].state(device)["native_value"], 43)
        self.assertTrue(all(not spec.actions for spec in items.values()))

    async def test_fridge_targets_and_modes_are_not_power(self):
        device = context("A3G6", {
            "freezerFloat": [definition("target", permission="GPR", min="-24.0", max="-16.0", step=1.0)],
            "refrigeratorFloat": [definition("target", permission="GPR", min="2.0", max="8.0", step=1.0)],
            "freezeSwitch": [definition("on", permission="GPR")],
            "refrigerateSwitch": [definition("on", permission="GPR")],
            "commonFaultDetection": [definition("status", permission="GR"),
                definition("code", permission="GR", enumList=enums((0, "正常"), (1, "冷藏室长时间未关门")))],
        }, {"freezerFloat": {"target": -22}, "commonFaultDetection": {"code": 1, "status": 1}})
        items = specs(device)
        self.assertFalse({"power", "switch", "on_off"} & items.keys())
        self.assertTrue(items["problem"].state(device)["is_on"])
        self.assertEqual(items["fault_code"].state(device)["native_value"], "冷藏室长时间未关门")
        await items["freezer_target"].actions["set_value"](device, {"value": -24})
        device.async_send_service.assert_awaited_with("freezerFloat", {"target": -24})
        for value in [-25, -15, -22.5]:
            with self.assertRaises(ValueError):
                await items["freezer_target"].actions["set_value"](device, {"value": value})

    def test_fan_speed_is_not_clamped_to_profile_gear(self):
        device = context("A08G", {"fan": [definition("gear", min=1, max=4)]},
                         {"fan": {"speed": 5, "angle": 0}, "switch": {"on": 1}})
        items = specs(device)
        self.assertEqual(items["speed"].state(device)["native_value"], 5)
        self.assertEqual(items["speed"].state(device)["extra_state_attributes"]["source_field"], "fan.speed")
        self.assertTrue(all(not spec.actions for spec in items.values()))
        device._state["fan"] = {"gear": 2}
        self.assertEqual(items["speed"].state(device)["native_value"], 2)

    def test_televisions_use_own_labels_and_no_secrets(self):
        for pid in ["V0D5", "V0DE"]:
            device = context(pid, {"devicestate": [definition("screenState", enumList=enums((0, "熄屏"), (1, "在线"), (2, "离线")))]},
                             {"devicestate": {"screenState": 2}, "pictureMode": {"mode": 9},
                              "remotecontrol": {"access_token": "SYNTHETIC_SECRET"},
                              "speaker": {"volume": 31, "mute": False}})
            items = specs(device)
            self.assertEqual(items["screen_state"].state(device)["native_value"], "离线")
            self.assertEqual(items["picture_mode"].state(device)["native_value"], 9)
            self.assertFalse({"power", "switch", "on_off"} & items.keys())
            self.assertTrue(all(not spec.actions for spec in items.values()))
            self.assertNotIn("SYNTHETIC_SECRET", repr([spec.state(device) for spec in items.values()]))

    def test_no_missing_fields_and_no_fake_zero(self):
        for pid in ["20I0", "2J6Y", "A0OP", "A2LW", "A3G6", "V0D5", "V0DE"]:
            self.assertEqual(context(pid, {}).entity_specs, ())
        device = context("A2LW", {"temperature": [definition("current")]})
        for value in [None, "", "invalid", float("nan"), float("inf"), True]:
            device._state["temperature"] = {"current": value}
            self.assertIsNone(specs(device)["temperature"].state(device)["native_value"])

    def test_ambiguous_enum_has_no_controls(self):
        device = context("20I0", {"lightMode": [definition("mode", method="RW",
                         enumList=enums((1, "one"), (1, "another")))]})
        self.assertEqual(specs(device)["light_mode"].platform, "sensor")
        self.assertFalse(specs(device)["light_mode"].actions)


if __name__ == "__main__":
    unittest.main()
