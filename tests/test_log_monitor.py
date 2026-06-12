import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_status_light import log_monitor


class LogMonitorTests(unittest.TestCase):
    def test_observed_lamp_mode_prefers_request(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"AGENT_STATUS_LIGHT_HOME": td}):
            Path(td, "state.json").write_text(json.dumps({"mode": "green"}))
            Path(td, "request.json").write_text(json.dumps({"mode": "red_flash"}))
            self.assertEqual(log_monitor.observed_lamp_mode(), "red_flash")

    def test_approval_lamp_active(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"AGENT_STATUS_LIGHT_HOME": td}):
            Path(td, "request.json").write_text(json.dumps({"mode": "red_flash"}))
            self.assertTrue(log_monitor.approval_lamp_active())
            Path(td, "request.json").write_text(json.dumps({"mode": "yellow"}))
            self.assertFalse(log_monitor.approval_lamp_active())

    def test_busy_patterns_match_hermes_logs(self):
        line = "2026-06-12 agent.turn_context: conversation turn: abc"
        self.assertTrue(any(p.search(line) for p in log_monitor.BUSY_PATTERNS))
        line = "2026-06-12 OpenAI client created model=gpt"
        self.assertTrue(any(p.search(line) for p in log_monitor.BUSY_PATTERNS))

    def test_done_patterns_match_hermes_logs(self):
        line = "2026-06-12 agent.conversation_loop: Turn ended: xyz"
        self.assertTrue(any(p.search(line) for p in log_monitor.DONE_PATTERNS))


if __name__ == "__main__":
    unittest.main()
