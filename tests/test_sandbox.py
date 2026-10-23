"""Fake sandbox adapter tests: the card payload is actually enforced."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from mandate.card_controls import card_controls_from_passport
from mandate.mandate_policy_engine import POLICY_VERSION
from mandate.passport import ApprovedIntent, issue_passport
from mandate.sandbox import CardDeclined, FakeAirwallex

KEY = b"mandate-sandbox-test-key-at-least-32-bytes"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def controls(cadence="MONTHLY", amount="2000.00"):
    intent = ApprovedIntent(
        vendor="CloudMetrics Inc",
        amount=Decimal(amount),
        currency="USD",
        billing_cadence=cadence,
        merchant_category="5734",
        evidence_reference="quote:CM-2026-118",
        policy_version=POLICY_VERSION,
    )
    passport = issue_passport(intent, KEY, now=NOW)
    return card_controls_from_passport(passport, KEY, now=NOW)


class FakeSandboxTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = FakeAirwallex("32000.00", now_fn=lambda: NOW)

    def test_monthly_card_allows_within_limit_and_declines_annual(self):
        card = self.sandbox.create_card(controls("MONTHLY", "2000.00"))
        annual = self.sandbox.authorize(card["id"], "19680.00", now=NOW)
        self.assertEqual(annual["status"], "DECLINED")
        self.assertIn("per-transaction", annual["decline_reason"])
        monthly = self.sandbox.authorize(card["id"], "2000.00", now=NOW)
        self.assertEqual(monthly["status"], "APPROVED")

    def test_monthly_cumulative_cap(self):
        card = self.sandbox.create_card(controls("MONTHLY", "2000.00"))
        first = self.sandbox.authorize(card["id"], "2000.00", now=NOW)
        second = self.sandbox.authorize(card["id"], "2000.00", now=NOW)
        self.assertEqual(first["status"], "APPROVED")
        self.assertEqual(second["status"], "DECLINED")
        self.assertIn("cumulative", second["decline_reason"])

    def test_annual_single_use(self):
        card = self.sandbox.create_card(controls("ANNUAL", "19680.00"))
        first = self.sandbox.authorize(card["id"], "19680.00", now=NOW)
        second = self.sandbox.authorize(card["id"], "19680.00", now=NOW)
        self.assertEqual(first["status"], "APPROVED")
        self.assertEqual(second["status"], "DECLINED")
        self.assertIn("single-use", second["decline_reason"])

    def test_currency_and_mcc_allowlists(self):
        card = self.sandbox.create_card(controls())
        eur = self.sandbox.authorize(card["id"], "100.00", currency="EUR", now=NOW)
        other_mcc = self.sandbox.authorize(card["id"], "100.00", mcc="5812", now=NOW)
        self.assertEqual(eur["status"], "DECLINED")
        self.assertEqual(other_mcc["status"], "DECLINED")

    def test_deposit_updates_available_balance(self):
        result = self.sandbox.deposit("12000.00")
        self.assertEqual(result["available_balance"], "44000.00")
        self.assertEqual(self.sandbox.available_balance(), Decimal("44000.00"))

    def test_capture_reduces_balance(self):
        card = self.sandbox.create_card(controls())
        result = self.sandbox.authorize(card["id"], "2000.00", capture=True, now=NOW)
        self.assertTrue(result["captured"])
        self.assertEqual(self.sandbox.available_balance(), Decimal("30000.00"))

    def test_invalid_controls_rejected(self):
        with self.assertRaises(CardDeclined):
            self.sandbox.create_card({})

    def test_unknown_card_declined(self):
        result = self.sandbox.authorize("card_missing", "100.00", now=NOW)
        self.assertEqual(result["status"], "DECLINED")
        self.assertIn("unknown card", result["decline_reason"])


if __name__ == "__main__":
    unittest.main()
