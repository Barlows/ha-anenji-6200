from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRANSLATION_FILES = (
    ROOT / "custom_components" / "eybond_local" / "strings.json",
    *sorted((ROOT / "custom_components" / "eybond_local" / "translations").glob("*.json")),
)


class TranslationShapeTests(unittest.TestCase):
    def test_option_flow_errors_are_declared_at_options_error_level(self) -> None:
        for path in TRANSLATION_FILES:
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("proxy_capture_action_failed", payload["options"]["error"])
                invalid_steps = [
                    step_id
                    for step_id, step_payload in payload["options"]["step"].items()
                    if isinstance(step_payload, dict) and "errors" in step_payload
                ]
                self.assertEqual(invalid_steps, [])


if __name__ == "__main__":
    unittest.main()
