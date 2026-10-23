"""End-to-end application tests against the fake sandbox."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from mandate.application import ApplicationError, MandateApplication

KEY = b"mandate-application-test-key-32-bytes!"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="mandate-app-test-"))
        self.app = MandateApplication(
            passport_key=KEY,
            now_fn=lambda: NOW,
            retry_db_path=self.directory / "retry.sqlite",
        )
        self.snapshot = self.app.snapshot()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _run(self):
        self.snapshot = self.app.run_policy()
        return self.snapshot

    def _approve(self):
        token = self.snapshot["proposal"]["approval_token"]
        self.snapshot = self.app.approve(token)
        return self.snapshot

    def test_initial_snapshot_has_no_proposal(self):
        self.assertIsNone(self.snapshot["proposal"])
        self.assertEqual(self.snapshot["sandbox"]["available_balance"], "32000.00")
        self.assertEqual(self.snapshot["passport_status"], "NOT_PRESENT")
        self.assertEqual(self.snapshot["receivable"]["status"], "EXPECTED")

    def test_run_policy_selects_monthly_and_agent_matches(self):
        snapshot = self._run()
        self.assertEqual(snapshot["proposal"]["decision"], "PROPOSE_MONTHLY")
        self.assertEqual(
            snapshot["proposal"]["agent_output"]["recommendation"], "PROPOSE_MONTHLY"
        )
        self.assertEqual(snapshot["proposal"]["status"], "PENDING_APPROVAL")
        self.assertEqual(
            snapshot["proposal"]["submitted_intent"]["billing_cadence"], "MONTHLY"
        )
        self.assertEqual(snapshot["proposal"]["submitted_intent"]["amount"], "2000.00")

    def test_approve_requires_bound_token(self):
        self._run()
        with self.assertRaises(ApplicationError):
            self.app.approve("not-the-token")

    def test_approve_issues_passport_and_card(self):
        self._run()
        snapshot = self._approve()
        self.assertEqual(snapshot["proposal"]["status"], "APPROVED")
        self.assertEqual(snapshot["passport"]["validation_status"], "VALID")
        self.assertEqual(snapshot["passport"]["billing_cadence"], "MONTHLY")
        self.assertEqual(
            snapshot["passport_matches_current_intent"], "VALID"
        )
        controls = snapshot["card"]["controls"]
        self.assertEqual(controls["allowed_transaction_count"], "MULTIPLE")
        self.assertEqual(
            controls["transaction_limits"]["limits"][0]["amount"], 2000.0
        )

    def test_card_blocks_annual_but_allows_monthly(self):
        self._run()
        self._approve()
        denied = self.app.simulate_authorization("19680.00")
        self.assertEqual(denied["status"], "DECLINED")
        self.assertIn("per-transaction limit", denied["decline_reason"])
        approved = self.app.simulate_authorization("2000.00")
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["captured"], False)

    def test_receipt_marks_pending_proposal_stale(self):
        self._run()
        token = self.snapshot["proposal"]["approval_token"]
        self.snapshot = self.app.simulate_receipt()
        self.assertEqual(self.snapshot["sandbox"]["available_balance"], "44000.00")
        self.assertEqual(self.snapshot["proposal"]["status"], "STALE")
        with self.assertRaises(ApplicationError):
            self.app.approve(token)

    def test_receipt_changes_decision_and_requires_fresh_passport(self):
        self._run()
        self._approve()
        old_card_id = self.snapshot["card"]["id"]
        self.snapshot = self.app.simulate_receipt()
        snapshot = self._run()
        self.assertEqual(snapshot["proposal"]["decision"], "PROPOSE_ANNUAL")
        self.assertEqual(snapshot["sandbox"]["available_balance"], "44000.00")
        self.assertEqual(snapshot["card"]["id"], old_card_id)
        self.assertEqual(snapshot["passport_matches_current_intent"], "MISMATCH")
        denied = self.app.simulate_authorization("19680.00")
        self.assertEqual(denied["status"], "DECLINED")
        snapshot = self._approve()
        self.assertEqual(snapshot["passport"]["billing_cadence"], "ANNUAL")
        self.assertEqual(
            snapshot["card"]["controls"]["allowed_transaction_count"], "SINGLE"
        )
        approved = self.app.simulate_authorization("19680.00")
        self.assertEqual(approved["status"], "APPROVED")

    def test_tamper_probe_rejects_altered_passport(self):
        self._run()
        self._approve()
        result = self.app.tamper_check()
        self.assertEqual(result["tampered_status"], "INVALID")
        self.assertIn("intent_hash", result["reason"])

    def test_injection_probe_flags_text_without_changing_decision(self):
        snapshot = self._run()
        result = self.app.injection_check()
        self.assertGreaterEqual(result["flagged_count"], 3)
        self.assertEqual(
            result["policy_decision_unchanged"], snapshot["proposal"]["decision"]
        )
        self.assertIsNone(result["card_limit_unchanged"])

    def test_retry_probe_reuses_id_and_blocks_terminal(self):
        result = self.app.retry_check()
        steps = result["steps"]
        self.assertTrue(steps[0]["request_id"])
        self.assertTrue(steps[1]["same_request_id"])
        self.assertTrue(steps[2]["same_request_id"])
        self.assertTrue(steps[3]["blocked"])

    def test_live_plan_holds_at_initial_balance(self):
        self._run()
        result = self.app.live_plan_check()
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["minimum_balance"], "26000.00")

    def test_reset_clears_proposal_and_card(self):
        self._run()
        self._approve()
        snapshot = self.app.reset()
        self.assertIsNone(snapshot["proposal"])
        self.assertIsNone(snapshot["card"])
        self.assertIsNone(snapshot["passport"])
        self.assertEqual(snapshot["sandbox"]["available_balance"], "32000.00")


if __name__ == "__main__":
    unittest.main()
