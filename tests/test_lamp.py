import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_status_light import lamp


class LampTests(unittest.TestCase):
    def test_known_frames(self):
        self.assertEqual(lamp.COMMANDS["yellow"], bytes.fromhex("A0 01 01 A2"))
        self.assertEqual(lamp.COMMANDS["red_flash"], bytes.fromhex("A0 03 02 A5"))
        self.assertEqual(lamp.COMMANDS["off"], bytes.fromhex("A0 00 00 A0"))

    def test_hook_mapping(self):
        cases = {
            "pre_approval_request": "red_flash",
            "post_approval_response": "yellow",
            "pre_llm_call": "yellow",
            "pre_tool_call": "yellow",
            "transform_llm_output": "done",
            "on_session_start": "off",
            "on_session_end": "done",
        }
        for event, expected in cases.items():
            with self.subTest(event=event):
                self.assertEqual(lamp.mode_for_hook({"hook_event_name": event}), expected)

    def test_enqueue_writes_atomic_request_and_starts_daemon(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"AGENT_STATUS_LIGHT_HOME": td}):
            with mock.patch.object(lamp, "ensure_daemon") as ensure:
                self.assertTrue(lamp.enqueue_mode("yellow"))
                ensure.assert_called_once()
            data = json.loads((Path(td) / "request.json").read_text())
            self.assertEqual(data["mode"], "yellow")
            self.assertIsInstance(data["ts"], float)

    def test_rejects_unknown_mode(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"AGENT_STATUS_LIGHT_HOME": td}):
            self.assertFalse(lamp.enqueue_mode("purple"))
            self.assertFalse((Path(td) / "request.json").exists())

    def test_done_sequence_can_be_interrupted(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"AGENT_STATUS_LIGHT_HOME": td}):
            active = ("done", 1.0)
            (Path(td) / "request.json").write_text(json.dumps({"mode": "done", "ts": 1.0}))
            self.assertFalse(lamp.sleep_until_changed_or_timeout(active, 0.01))
            (Path(td) / "request.json").write_text(json.dumps({"mode": "yellow", "ts": 2.0}))
            self.assertTrue(lamp.sleep_until_changed_or_timeout(active, 0.2))


if __name__ == "__main__":
    unittest.main()
