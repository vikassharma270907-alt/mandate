"""Decision Passport, HMAC binding and status-precedence tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mandate.mandate_policy_engine import POLICY_VERSION
from mandate.passport import (
    ApprovedIntent,
    InvalidIntent,
    PassportKeyError,
    STATUS_EXPIRED,
    STATUS_INVALID,
    STATUS_MISMATCH,
    STATUS_VALID,
    compute_intent_hash,
    issue_passport,
    passport_to_dict,
    validate_passport,
)

KEY = b"mandate-test-key-that-is-at-least-32-bytes"
OTHER_KEY = b"another-test-key-that-is-at-least-32-bytes"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def intent(**overrides):
    values = {
        "vendor": "CloudMetrics Inc",
        "amount": Decimal("2000.00"),
        "currency": "USD",
        "billing_cadence": "MONTHLY",
        "merchant_category": "5734",
        "evidence_reference": "quote:CM-2026-118;sha256:abc123",
        "policy_version": POLICY_VERSION,
    }
    values.update(overrides)
    return ApprovedIntent(**values)


class ApprovedIntentTests(unittest.TestCase):
    def test_normalizes_whitespace_and_unicode(self):
        cleaned = intent(vendor="  CloudMetrics\u00a0\u00a0 Inc  ")
        self.assertEqual(cleaned.vendor, "CloudMetrics Inc")

    def test_normalizes_currency_and_cadence_case(self):
        cleaned = intent(currency="usd", billing_cadence="monthly")
        self.assertEqual(cleaned.currency, "USD")
        self.assertEqual(cleaned.billing_cadence, "MONTHLY")

    def test_rejects_bad_mcc(self):
        for mcc in ("573", "57345", "57A4", "５７３４"):
            with self.subTest(mcc=mcc):
                with self.assertRaises(InvalidIntent):
                    intent(merchant_category=mcc)

    def test_rejects_bad_cadence(self):
        for cadence in ("WEEKLY", "MONTH", ""):
            with self.subTest(cadence=cadence):
                with self.assertRaises(InvalidIntent):
                    intent(billing_cadence=cadence)

    def test_rejects_zero_amount(self):
        with self.assertRaises(InvalidIntent):
            intent(amount=Decimal("0.00"))


class PassportIssueTests(unittest.TestCase):
    def test_issue_valid_passport(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        result = validate_passport(passport, KEY, now=NOW)
        self.assertEqual(result.status, STATUS_VALID)
        self.assertEqual(passport.approval_status, "APPROVED")
        self.assertEqual(len(passport.intent_hash), 64)
        self.assertEqual(len(passport.record_seal), 64)

    def test_rejects_short_key(self):
        with self.assertRaises(PassportKeyError):
            issue_passport(intent(), b"short")

    def test_intent_hash_is_deterministic_across_normalization(self):
        left = intent(vendor=" CloudMetrics  Inc ", currency="usd")
        right = intent(vendor="CloudMetrics Inc", currency="USD")
        self.assertEqual(
            compute_intent_hash(left, KEY),
            compute_intent_hash(right, KEY),
        )

    def test_same_intent_different_approval_ids_share_intent_hash(self):
        first = issue_passport(intent(), KEY, approval_id="apr_one", now=NOW)
        second = issue_passport(intent(), KEY, approval_id="apr_two", now=NOW)
        self.assertNotEqual(first.approval_id, second.approval_id)
        self.assertEqual(first.intent_hash, second.intent_hash)
        self.assertNotEqual(first.record_seal, second.record_seal)

    def test_passport_dict_uses_string_amounts(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        payload = passport_to_dict(passport)
        self.assertEqual(payload["amount"], "2000.00")
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["approval_id"], passport.approval_id)


class PassportValidationTests(unittest.TestCase):
    def test_expected_intent_mismatch(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        other = intent(amount=Decimal("19680.00"), billing_cadence="ANNUAL")
        result = validate_passport(passport, KEY, now=NOW, expected_intent=other)
        self.assertEqual(result.status, STATUS_MISMATCH)

    def test_expired_passport(self):
        passport = issue_passport(intent(), KEY, now=NOW, expires_in=timedelta(minutes=5))
        result = validate_passport(passport, KEY, now=NOW + timedelta(minutes=6))
        self.assertEqual(result.status, STATUS_EXPIRED)

    def test_tampered_amount_is_invalid(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        tampered = replace(passport, amount=Decimal("9000.00"))
        result = validate_passport(tampered, KEY, now=NOW)
        self.assertEqual(result.status, STATUS_INVALID)

    def test_tampered_status_is_invalid(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        tampered = replace(passport, approval_status="REVOKED")
        result = validate_passport(tampered, KEY, now=NOW)
        self.assertEqual(result.status, STATUS_INVALID)

    def test_tampered_expiry_is_invalid(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        tampered = replace(passport, approval_expiry="2027-01-01T00:00:00+00:00")
        result = validate_passport(tampered, KEY, now=NOW)
        self.assertEqual(result.status, STATUS_INVALID)

    def test_invalid_precedes_expired(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        tampered = replace(passport, amount=Decimal("9000.00"))
        result = validate_passport(
            tampered,
            KEY,
            now=NOW + timedelta(days=1),
        )
        self.assertEqual(result.status, STATUS_INVALID)

    def test_mismatch_precedes_expired(self):
        passport = issue_passport(intent(), KEY, now=NOW, expires_in=timedelta(minutes=1))
        other = intent(amount=Decimal("19680.00"), billing_cadence="ANNUAL")
        result = validate_passport(
            passport,
            KEY,
            now=NOW + timedelta(hours=1),
            expected_intent=other,
        )
        self.assertEqual(result.status, STATUS_MISMATCH)

    def test_wrong_key_is_invalid(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        result = validate_passport(passport, OTHER_KEY, now=NOW)
        self.assertEqual(result.status, STATUS_INVALID)

    def test_naive_expiry_is_invalid(self):
        passport = issue_passport(intent(), KEY, now=NOW)
        tampered = replace(passport, approval_expiry="2026-10-23T12:15:00")
        result = validate_passport(tampered, KEY, now=NOW)
        self.assertEqual(result.status, STATUS_INVALID)


if __name__ == "__main__":
    unittest.main()
