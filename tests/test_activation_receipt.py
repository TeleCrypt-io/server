#!/usr/bin/env python3
"""Execute the guards rendered from salt.deploy against receipt transitions."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def state_arguments(rendered, state_name, state_module):
    state = rendered["local"][state_name]
    arguments = state[state_module]
    return {key: value for item in arguments if isinstance(item, dict) for key, value in item.items()}


class ActivationReceiptTest(unittest.TestCase):
    def test_rendered_guards_match_full_receipt_identity(self):
        if len(sys.argv) != 2:
            self.fail("pass the JSON output of salt-call state.show_sls salt.deploy")
        rendered_path = Path(sys.argv[1])
        with rendered_path.open(encoding="utf-8") as stream:
            rendered = json.load(stream)

        pending = state_arguments(rendered, "telecrypt-activation-pending", "file")
        success = state_arguments(rendered, "telecrypt-activation", "cmd")
        expected_pending = pending["dataset"]
        self.assertEqual(expected_pending["status"], "pending")
        receipt_path = pending["name"]
        guards = [pending["unless"], success["unless"]]

        expected_success = dict(expected_pending, status="succeeded")
        same_tag_other_environment = dict(
            expected_success,
            server_name="production.example.invalid",
            billing_environment="live",
        )
        self.assertEqual(expected_success["release"], same_tag_other_environment["release"])

        with tempfile.TemporaryDirectory(prefix="activation-receipt-") as temp_dir:
            fixture_path = Path(temp_dir) / "activation.json"
            for index, guard in enumerate(guards):
                local_guard = guard.replace(receipt_path, str(fixture_path))
                cases = (
                    ("matching success", json.dumps(expected_success), 0),
                    ("same tag, changed environment", json.dumps(same_tag_other_environment), 1),
                    ("pending receipt", json.dumps(expected_pending), 1),
                    ("failed receipt", json.dumps(dict(expected_pending, status="failed")), 1),
                    ("malformed receipt", "{", 1),
                )
                for label, contents, expected_status in cases:
                    with self.subTest(guard=index, receipt=label):
                        fixture_path.write_text(contents, encoding="utf-8")
                        result = subprocess.run(
                            local_guard,
                            shell=True,
                            executable="/bin/bash",
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertEqual(result.returncode, expected_status, result.stderr)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
