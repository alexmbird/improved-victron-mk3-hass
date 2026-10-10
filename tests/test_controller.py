"""Tests for the controller's Solar & Wind Priority override plumbing, with Home
Assistant and the device library replaced by stubs. Run with:

    python3 -m unittest discover -s tests
"""

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent


def _install_stubs():
    class _Error(Exception):
        pass

    stubs = {}

    def stub(name, **attrs):
        module = types.ModuleType(name)
        module.__getattr__ = lambda attr: mock.MagicMock(name=f"{name}.{attr}")
        for key, value in attrs.items():
            setattr(module, key, value)
        stubs[name] = module
        return module

    stub("homeassistant")
    stub("homeassistant.components")
    stub("homeassistant.components.device_automation")
    stub("homeassistant.components.device_automation.exceptions", DeviceNotFound=_Error)
    stub("homeassistant.config_entries")
    stub("homeassistant.const")
    stub("homeassistant.core")
    stub(
        "homeassistant.exceptions",
        HomeAssistantError=type("HomeAssistantError", (Exception,), {}),
    )
    stub("homeassistant.helpers")
    stub("homeassistant.helpers.config_validation")
    stub("homeassistant.helpers.device_registry")
    stub(
        "homeassistant.helpers.update_coordinator",
        UpdateFailed=type("UpdateFailed", (Exception,), {}),
    )
    stub("voluptuous")

    class _Response:
        def __init__(self, value):
            self.value = value

    stub(
        "victron_mk3",
        Handler=object,
        SettingResponse=_Response,
        VictronMK3=mock.MagicMock,
    )
    for name, module in stubs.items():
        sys.modules[name] = module


_install_stubs()
sys.path.insert(0, str(_ROOT))
integration = importlib.import_module("custom_components.victron_mk3")
priority = importlib.import_module(
    "custom_components.victron_mk3.prioritize_wind_and_solar"
)
SettingResponse = sys.modules["victron_mk3"].SettingResponse
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError
UpdateFailed = sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed

IDLE_STATUS = bytes.fromhex("ff00a2ff1d30008411")
ACTIVE_STATUS = bytes.fromhex("ff00a2ff1d30000410")


class FakeDriver:
    def __init__(self, replies, frame_replies=None):
        self.replies = replies
        self.frame_replies = frame_replies or {}
        self.sent = []
        # Interface frames sent, as (command, data).
        self.frames = []
        # Everything sent, in order: W payloads as bytes, frames as tuples.
        self.log = []
        self.handled = []

    def _handle_frame(self, handler, msg):
        self.handled.append(bytes(msg))

    def _send_w_request(self, msg, completion):
        self.sent.append(bytes(msg))
        self.log.append(bytes(msg))
        reply = self.replies.get(bytes(msg))
        if reply is not None:
            completion(None, reply)

    def _send_frame(self, command, data):
        frame = (command, bytes(data))
        self.frames.append(frame)
        self.log.append(frame)
        reply = self.frame_replies.get(frame)
        if reply is not None:
            self._handle_frame(None, reply)


READ_60 = b"\x31\x3c\x00"
INFO_60 = b"\x35\x3c\x00"
VERSION = b"\x05"
STATUS = b"\x44\xff"


def setting_reply(value):
    return bytes([0xFF, 0x58, 0x86, value & 0xFF, value >> 8])


# The short-frame 'S' frame, as (command, data), and its reply.
SHORT = ("S", bytes.fromhex("00000001900001"))
S_REPLY = b"\xff\x53"


def make_controller(setting_60=528, replies=None, frame_replies=None):
    controller = integration.Controller("/dev/null")
    controller._mk3 = mock.MagicMock()
    all_replies = {}
    if setting_60 is not None:
        all_replies[READ_60] = setting_reply(setting_60)
    all_replies.update(replies or {})
    controller._mk3._driver = FakeDriver(
        all_replies, {SHORT: S_REPLY} if frame_replies is None else frame_replies
    )
    return controller


class StatusDecodeTest(unittest.TestCase):
    def test_states(self):
        def reply(word, valid=0x1D, head=b"\xff\x00\xa2\xff"):
            return head + bytes([valid]) + word.to_bytes(4, "little")

        OVERRIDDEN = priority.PRIORITY_STATE_OVERRIDDEN
        ACTIVE = priority.PRIORITY_STATE_ACTIVE
        AC_OR_GENERATOR = priority.PRIORITY_STATE_AC_OR_GENERATOR
        for payload, state in (
            (IDLE_STATUS, ACTIVE),
            (ACTIVE_STATUS, OVERRIDDEN),
            (reply(0x12040030), AC_OR_GENERATOR),
            (reply(0x14040030), AC_OR_GENERATOR),
            (reply(0x16040030), AC_OR_GENERATOR),
            (reply(0x17040030), ACTIVE),
            (reply(0x10040030, valid=26), OVERRIDDEN),
            (reply(0x14040030, valid=26), AC_OR_GENERATOR),
            (reply(0x10040030, valid=25), None),
            (reply(0x10040030, valid=0), None),
            (reply(0x10040030, head=b"\xff\x00\xa2\xfe"), None),
            (reply(0x10040030, head=b"\xff\x00\xa3\xff"), None),
            (ACTIVE_STATUS[:8], None),
            (None, None),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(integration.priority_state(payload), state)


class TransportTest(unittest.TestCase):
    def test_priority_enabled(self):
        for setting_60, enabled in ((528, True), (16, False), (None, None)):
            controller = make_controller(setting_60=setting_60)
            transport = integration._DeviceTransport(controller)
            with self.subTest(setting_60=setting_60):
                self.assertEqual(asyncio.run(transport.priority_enabled()), enabled)

    def test_priority_state_reads_extended_status(self):
        controller = make_controller(replies={STATUS: ACTIVE_STATUS})
        transport = integration._DeviceTransport(controller)
        self.assertEqual(
            asyncio.run(transport.priority_state()), priority.PRIORITY_STATE_OVERRIDDEN
        )
        # No short-frame 'S' frame first unless one is pending.
        self.assertEqual(controller._mk3._driver.log, [STATUS])

    def test_read_setting_sends_three_bytes(self):
        controller = make_controller(setting_60=528)
        transport = integration._DeviceTransport(controller)
        self.assertEqual(asyncio.run(transport.read_setting(60)), 528)
        self.assertEqual(controller._mk3._driver.sent, [READ_60])

    def test_read_setting_not_supported(self):
        controller = make_controller(
            setting_60=None, replies={READ_60: b"\xff\x58\x91\x00\x00"}
        )
        transport = integration._DeviceTransport(controller)
        self.assertIsNone(asyncio.run(transport.read_setting(60)))

    def test_read_setting_maximum_long_form(self):
        reply = bytes.fromhex("ff5989" "0100" "0000" "1000" "0000" "ff03" "00")
        controller = make_controller(replies={INFO_60: reply})
        transport = integration._DeviceTransport(controller)
        self.assertEqual(asyncio.run(transport.read_setting_maximum(60)), 0x3FF)
        self.assertEqual(controller._mk3._driver.sent, [INFO_60])

    def test_read_setting_maximum_other_forms_are_none(self):
        for reply in (
            bytes.fromhex("ff5989010000"),
            bytes.fromhex("ff5986"),
            bytes.fromhex("ff598a" "0100" "0000" "1000" "0000" "ff03" "00"),
        ):
            controller = make_controller(replies={INFO_60: reply})
            transport = integration._DeviceTransport(controller)
            with self.subTest(reply=reply.hex()):
                self.assertIsNone(asyncio.run(transport.read_setting_maximum(60)))

    def test_read_software_version_long_form(self):
        reply = bytes([0xFF, 0x5A, 0x82]) + (2629506).to_bytes(4, "little")
        controller = make_controller(replies={VERSION: reply})
        transport = integration._DeviceTransport(controller)
        self.assertEqual(
            asyncio.run(transport.read_software_version()),
            priority.SoftwareVersion(2629506, long_form=True),
        )
        self.assertEqual(controller._mk3._driver.sent, [VERSION])

    def test_read_software_version_short_form(self):
        controller = make_controller(replies={VERSION: b"\xff\x5a\x82\x34\x12"})
        transport = integration._DeviceTransport(controller)
        self.assertEqual(
            asyncio.run(transport.read_software_version()),
            priority.SoftwareVersion(0x1234, long_form=False),
        )

    def test_read_software_version_wrong_reply(self):
        controller = make_controller(replies={VERSION: b"\xff\x5a\x80\x00\x00"})
        transport = integration._DeviceTransport(controller)
        self.assertIsNone(asyncio.run(transport.read_software_version()))

    def test_requests_hold_io_lock(self):
        controller = make_controller(replies={b"\x44\xff": IDLE_STATUS})
        transport = integration._DeviceTransport(controller)

        async def check():
            held = []
            original = controller._w_request_raw

            async def spy(payload):
                held.append(controller._io_lock.locked())
                return await original(payload)

            controller._w_request_raw = spy
            await transport.priority_state()
            await transport.write(b"\x44\xff")
            return held

        self.assertEqual(asyncio.run(check()), [True, True])


class ControllerTest(unittest.TestCase):
    def test_unexpected_error_becomes_clear_refusal(self):
        controller = make_controller()
        controller._w_request_raw = mock.AsyncMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(HomeAssistantError):
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        self.assertEqual(controller._mk3._driver.sent, [])

    def test_pending_short_frames_sent_before_every_request_kind(self):
        controller = make_controller(replies={STATUS: IDLE_STATUS}, frame_replies={})
        transport = integration._DeviceTransport(controller)
        controller._short_frames_pending = True
        for call in (
            transport.priority_state(),
            transport.read_setting(60),
            controller.read_device_info(),
        ):
            with self.assertRaises(UpdateFailed):
                asyncio.run(call)
        self.assertEqual(controller._mk3._driver.log, [SHORT] * 3)
        controller._mk3._driver.frame_replies[SHORT] = S_REPLY
        asyncio.run(transport.priority_state())
        self.assertEqual(controller._mk3._driver.log[-2:], [SHORT, STATUS])
        self.assertFalse(controller._short_frames_pending)

    def test_remote_panel_state_holds_io_lock(self):
        controller = make_controller()
        held = []

        async def send(*args):
            held.append(controller._io_lock.locked())

        controller._mk3.send_state_request = send
        asyncio.run(
            controller.set_remote_panel_state(integration.Mode.ON, None)
        )
        self.assertEqual(held, [True])
        self.assertEqual(controller._mk3._driver.log, [])

    def test_start_when_running_writes_nothing(self):
        controller = make_controller(replies={STATUS: ACTIVE_STATUS})
        self.assertFalse(
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        )
        self.assertEqual(controller._mk3._driver.sent, [READ_60, STATUS])

    def test_feature_disabled_writes_nothing(self):
        controller = make_controller(setting_60=16, replies={STATUS: IDLE_STATUS})
        with self.assertRaises(HomeAssistantError):
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        self.assertEqual(controller._mk3._driver.sent, [READ_60])

    def _enabled_controller(self, status, write, frame_replies=None):
        version = bytes([0xFF, 0x5A, 0x82]) + (2629506).to_bytes(4, "little")
        info = bytes.fromhex("ff5989" "0100" "0000" "1000" "0000" "ff03" "00")
        replies = {
            STATUS: list(status),
            VERSION: [version],
            INFO_60: [info],
            READ_60: [setting_reply(528)],
            write: [b"\xff\x58\x88\x00\x00"],
        }
        if frame_replies is None:
            frame_replies = {
                ("A", b"\x01\x00"): b"\xff\x41\x01\x00",
                ("D", b""): bytes.fromhex("ff44" "03" "3200" "00000000"),
                ("S", bytes.fromhex("033200" "01d03e06")): S_REPLY,
                SHORT: S_REPLY,
            }

        class Driver(FakeDriver):
            def _send_w_request(self, msg, completion):
                self.sent.append(bytes(msg))
                self.log.append(bytes(msg))
                queue = replies[bytes(msg)]
                completion(None, queue.pop(0) if len(queue) > 1 else queue[0])

        controller = make_controller(setting_60=None)
        controller._mk3._driver = Driver({}, frame_replies)
        return controller

    def test_enabled_start_sends_exact_sequence(self):
        write = bytes.fromhex("37033c1000")
        controller = self._enabled_controller([IDLE_STATUS, ACTIVE_STATUS], write)
        self.assertTrue(
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        )
        self.assertEqual(
            controller._mk3._driver.log,
            [
                READ_60,
                STATUS,
                ("A", b"\x01\x00"),
                ("D", b""),
                ("S", bytes.fromhex("033200" "01d03e06")),
                VERSION,
                INFO_60,
                READ_60,
                write,
                SHORT,
                STATUS,
            ],
        )
        self.assertFalse(controller._priority_override_transport._in_session)
        self.assertFalse(controller._io_lock.locked())
        self.assertNotIn("_handle_frame", vars(controller._mk3._driver))

    def test_enabled_stop_sends_exact_sequence(self):
        write = bytes.fromhex("37033c1002")
        controller = self._enabled_controller([ACTIVE_STATUS, IDLE_STATUS], write)
        self.assertTrue(
            asyncio.run(controller.set_prioritize_wind_and_solar_override(False))
        )
        log = controller._mk3._driver.log
        self.assertEqual(log[-3:], [write, SHORT, STATUS])

    def test_no_state_reply_restores_nothing_and_writes_nothing(self):
        write = bytes.fromhex("37033c1000")
        controller = self._enabled_controller(
            [IDLE_STATUS],
            write,
            frame_replies={
                ("A", b"\x01\x00"): b"\xff\x41\x01\x00",
                SHORT: S_REPLY,
            },
        )
        with self.assertRaises(HomeAssistantError):
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        self.assertEqual(
            controller._mk3._driver.log,
            [READ_60, STATUS, ("A", b"\x01\x00"), ("D", b"")],
        )
        self.assertFalse(controller._io_lock.locked())

    def test_short_mode_restored_when_discovery_refuses(self):
        write = bytes.fromhex("37033c1000")
        controller = self._enabled_controller([IDLE_STATUS], write)
        # Firmware 505 refuses after long-frame mode is entered.
        old = (2629505).to_bytes(4, "little")
        driver = controller._mk3._driver
        original = driver._send_w_request

        def send(msg, completion):
            if bytes(msg) == VERSION:
                driver.sent.append(bytes(msg))
                driver.log.append(bytes(msg))
                completion(None, bytes([0xFF, 0x5A, 0x82]) + old)
                return
            original(msg, completion)

        driver._send_w_request = send
        with self.assertRaises(HomeAssistantError):
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        self.assertEqual(driver.log[-2:], [VERSION, SHORT])
        self.assertNotIn(write, driver.log)

    def test_no_restore_reply_retries_then_resends_before_next_request(self):
        write = bytes.fromhex("37033c1000")
        controller = self._enabled_controller(
            [IDLE_STATUS, IDLE_STATUS, ACTIVE_STATUS], write
        )
        driver = controller._mk3._driver
        transport = controller._priority_override_transport
        asyncio.run(transport.priority_state())
        del driver.frame_replies[SHORT]
        with self.assertRaises(HomeAssistantError):
            asyncio.run(controller.set_prioritize_wind_and_solar_override(True))
        self.assertEqual(driver.log[-3:], [write, SHORT, SHORT])
        self.assertTrue(controller._short_frames_pending)
        self.assertFalse(controller._io_lock.locked())
        driver.frame_replies[SHORT] = S_REPLY
        asyncio.run(transport.priority_state())
        self.assertEqual(driver.log[-2:], [SHORT, STATUS])
        self.assertFalse(controller._short_frames_pending)

    def test_other_io_waits_for_session(self):
        write = bytes.fromhex("37033c1000")
        restore = SHORT
        controller = self._enabled_controller([IDLE_STATUS, ACTIVE_STATUS], write)
        log = controller._mk3._driver.log

        async def both():
            task = asyncio.create_task(
                controller.set_prioritize_wind_and_solar_override(True)
            )
            snapshots = []
            while not task.done():
                async with controller._io_lock:
                    snapshots.append(list(log))
                await asyncio.sleep(0)
            await task
            return snapshots

        for snapshot in asyncio.run(both()):
            if ("A", b"\x01\x00") in snapshot:
                self.assertIn(restore, snapshot)


class DeviceInfoTest(unittest.TestCase):
    ADDRESS = ("A", b"\x01\x00")
    PART0 = b"\x05\x00\x00"
    PART1 = b"\x06\x00\x00"
    LONG = ("S", bytes.fromhex("033200" "01d03e06"))
    SESSION = [ADDRESS, ("D", b""), LONG]
    FRAME_REPLIES = {
        ADDRESS: b"\xff\x41\x01\x00",
        ("D", b""): bytes.fromhex("ff44" "03" "3200" "00000000"),
        LONG: S_REPLY,
        SHORT: S_REPLY,
    }
    SHORT_VERSION = {
        PART0: b"\xff\x58\x82\x82\x1f",
        PART1: b"\xff\x59\x83\x28\x00",
    }

    @staticmethod
    def info(maximum):
        return bytes.fromhex("ff5989" "0100" "0000" "1000" "0000") + bytes(
            [maximum & 0xFF, maximum >> 8, 0]
        )

    def read(self, replies):
        controller = make_controller(
            setting_60=None, replies=replies, frame_replies=self.FRAME_REPLIES
        )
        asyncio.run(controller.read_device_info())
        self.assertFalse(controller._io_lock.locked())
        return controller, controller._mk3._driver.log

    def test_short_frame_version_then_setting_info(self):
        controller, log = self.read({**self.SHORT_VERSION, INFO_60: self.info(0x3FF)})
        self.assertEqual(controller.device_firmware, 2629506)
        self.assertTrue(controller.priority_override_supported)
        self.assertEqual(
            log,
            [self.ADDRESS, self.PART0, self.PART1, *self.SESSION, INFO_60, SHORT],
        )

    def test_maximum_without_bit_9_is_unsupported(self):
        controller, _ = self.read({**self.SHORT_VERSION, INFO_60: self.info(0x1FF)})
        self.assertFalse(controller.priority_override_supported)

    def test_old_firmware_skips_the_long_frame_session(self):
        controller, log = self.read(
            {self.PART0: b"\xff\x58\x82\x81\x1f", self.PART1: b"\xff\x59\x83\x28\x00"}
        )
        self.assertEqual(controller.device_firmware, 2629505)
        self.assertFalse(controller.priority_override_supported)
        self.assertEqual(log, [self.ADDRESS, self.PART0, self.PART1])

    def test_long_frame_version_when_short_frames_fail(self):
        controller, log = self.read(
            {
                self.PART0: b"\xff\x58\x82\x82\x1f",
                self.PART1: b"\xff\x59\x80\x00\x00",
                VERSION: bytes([0xFF, 0x5A, 0x82]) + (2629506).to_bytes(4, "little"),
                INFO_60: self.info(0x3FF),
            }
        )
        self.assertEqual(controller.device_firmware, 2629506)
        self.assertTrue(controller.priority_override_supported)
        self.assertEqual(
            log,
            [
                self.ADDRESS,
                self.PART0,
                self.PART1,
                *self.SESSION,
                VERSION,
                INFO_60,
                SHORT,
            ],
        )

    def test_unreadable(self):
        controller, log = self.read({})
        self.assertIsNone(controller.device_firmware)
        self.assertFalse(controller.priority_override_supported)
        self.assertEqual(log[-3:], [VERSION, INFO_60, SHORT])


class SetRemotePanelStateServiceTest(unittest.TestCase):
    def _call(self, data, **kwargs):
        context = mock.MagicMock()
        context.controller.set_remote_panel_state = mock.AsyncMock()
        context.coordinator.async_request_refresh = mock.AsyncMock()
        context.coordinator.data = data
        hass = mock.MagicMock()
        hass.data = {integration.DOMAIN: {"entry": {integration.KEY_CONTEXT: context}}}
        device = mock.MagicMock(config_entries=["entry"])
        with mock.patch.object(integration, "device_registry") as registry:
            registry.async_get.return_value.async_get.return_value = device
            asyncio.run(
                integration.set_remote_panel_state(
                    hass, "device", integration.Mode.ON, **kwargs
                )
            )
        return context.controller.set_remote_panel_state

    def test_current_limit_sources(self):
        data = mock.MagicMock()
        data.config.actual_current_limit = 4.2
        for kwargs, expected in (
            ({"current_limit": None}, 4.2),
            ({"current_limit": 12.5}, 12.5),
            ({"current_limit": None, "keep_current_limit": True}, 4.2),
            ({"current_limit": None, "keep_current_limit": False}, None),
        ):
            with self.subTest(kwargs=kwargs):
                send = self._call(data, **kwargs)
                send.assert_awaited_once_with(integration.Mode.ON, expected)

    def test_keep_current_limit_unavailable_raises(self):
        data = mock.MagicMock()
        data.config = None
        for data in (None, data):
            with self.subTest(data=data):
                for keep in (None, True):
                    with self.assertRaises(HomeAssistantError):
                        self._call(data, current_limit=None, keep_current_limit=keep)


if __name__ == "__main__":
    unittest.main()
