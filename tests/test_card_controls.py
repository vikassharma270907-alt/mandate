"""Card-control derivation tests: valid passport in, strict controls out."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mandate.card_controls import (
    CardControlError,
    card_controls_from_passport,
    summarize_controls,
)
from mandate.mandate_policy_engine import POLICY_VERSION
from mandate.passport import ApprovedIntent, issue_passport

KEY = b"mandate-test-key-that-is-at-least-32-bytes"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def make_intent(cadence="MONTHLY", amount="2000.00", currency="USD", mcc="5734"):
    return ApprovedIntent(
        vendor="CloudMetrics Inc",
        amount=Decimal(amount),
        currency=currency,
        billing_cadence=cadence,
        merchant_category=mcc,
        evidence_reference="quote:CM-2026-118;sha256:abc123",
        policy_version=POLICY_VERSION,
    )


class CardControlTests(unittest.TestCase):
    def test_annual_controls_are_single_use(self):
        passport = issue_passport(make_intent("ANNUAL", "19680.00"), KEY, now=NOW)
        controls = card_controls_from_passport(passport, KEY, now=NOW)
        self.assertEqual(controls["allowed_transaction_count"], "SINGLE")
        intervals = [limit["interval"] for limit in controls["transaction_limits"]["limits"]]
        self.assertEqual(intervals, ["PER_TRANSACTION", "ALL_TIME"])

    def test_monthly_controls_are_recurring(self):
        passport = issue_passport(make_intent("MONTHLY", "2000.00"), KEY, now=NOW)
        controls = card_controls_from_passport(passport, KEY, now=NOW)
        self.assertEqual(controls["allowed_transaction_count"], "MULTIPLE")
        intervals = [limit["interval"] for limit in controls["transaction_limits"]["limits"]]
        self.assertEqual(intervals, ["PER_TRANSACTION", "MONTHLY"])

    def test_payload_shape(self):
        passport = issue_passport(make_intent("MONTHLY", "2000.00"), KEY, now=NOW)
        controls = card_controls_from_passport(passport, KEY, now=NOW)
        self.assertEqual(
            set(controls),
            {
                "allowed_transaction_count",
                "allowed_currencies",
                "allowed_merchant_categories",
                "transaction_limits",
            },
        )
        self.assertEqual(controls["allowed_currencies"], ["USD"])
        self.assertEqual(controls["allowed_merchant_categories"], ["5734"])
        self.assertEqual(controls["transaction_limits"]["currency"], "USD")

    def test_both_limits_equal_approved_amount(self):
        passport = issue_passport(make_intent("ANNUAL", "19680.00"), KEY, now=NOW)
        controls = card_controls_from_passport(passport, KEY, now=NOW)
        for limit in controls["transaction_limits"]["limits"]:
            self.assertEqual(limit["amount"], 19680.0)

    def test_invalid_passport_raises(self):
        passport = issue_passport(make_intent(), KEY, now=NOW)
        tampered = replace(passport, amount=Decimal("9999.00"))
        with self.assertRaises(CardControlError):
            card_controls_from_passport(tampered, KEY, now=NOW)

    def test_expired_passport_raises(self):
        passport = issue_passport(
            make_intent(), KEY, now=NOW, expires_in=timedelta(minutes=1)
        )
        with self.assertRaises(CardControlError):
            card_controls_from_passport(
                passport, KEY, now=NOW + timedelta(minutes=2)
            )

    def test_expected_intent_mismatch_raises(self):
        passport = issue_passport(make_intent("ANNUAL", "19680.00"), KEY, now=NOW)
        with self.assertRaises(CardControlError):
            card_controls_from_passport(
                passport,
                KEY,
                now=NOW,
                expected_intent=make_intent("MONTHLY", "2000.00"),
            )

    def test_currency_allowlist_enforced(self):
        passport = issue_passport(make_intent(currency="EUR"), KEY, now=NOW)
        with self.assertRaises(CardControlError):
            card_controls_from_passport(passport, KEY, now=NOW)

    def test_mcc_allowlist_enforced(self):
        passport = issue_passport(make_intent(mcc="5812"), KEY, now=NOW)
        with self.assertRaises(CardControlError):
            card_controls_from_passport(passport, KEY, now=NOW)

    def test_max_amount_catches_cents_for_dollars(self):
        passport = issue_passport(make_intent("ANNUAL", "196800.00"), KEY, now=NOW)
        with self.assertRaises(CardControlError):
            card_controls_from_passport(
                passport, KEY, now=NOW, max_amount=Decimal("25000.00")
            )

    def test_empty_allowlist_rejected(self):
        passport = issue_passport(make_intent(), KEY, now=NOW)
        with self.assertRaises(CardControlError):
            card_controls_from_passport(
                passport, KEY, now=NOW, allowed_currencies=[]
            )

    def test_no_vendor_or_untrusted_text_in_payload(self):
        passport = issue_passport(make_intent(), KEY, now=NOW)
        payload = json.dumps(
            card_controls_from_passport(passport, KEY, now=NOW)
        )
        self.assertNotIn("CloudMetrics", payload)
        self.assertNotIn("vendor", payload.lower())

    def test_summary_mentions_controls(self):
        passport = issue_passport(make_intent("ANNUAL", "19680.00"), KEY, now=NOW)
        summary = summarize_controls(
            card_controls_from_passport(passport, KEY, now=NOW)
        )
        self.assertTrue(any("SINGLE" in line for line in summary))
        self.assertTrue(any("19,680.00" in line for line in summary))


if __name__ == "__main__":
    unittest.main()
