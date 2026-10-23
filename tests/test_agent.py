"""Agent-boundary tests: untrusted text in, validated JSON out."""

from __future__ import annotations

import unittest
from decimal import Decimal

from mandate.agent import (
    AgentOutputRejected,
    DemoAgent,
    build_envelope,
    load_system_prompt,
    scan_document,
    terms_from_agent_output,
    validate_agent_output,
)
from mandate.application import (
    DEFAULT_INJECTION_PATH,
    DEFAULT_QUOTE_PATH,
)
from mandate.mandate_policy_engine import (
    CashContext,
    Flow,
    FlowKind,
    PurchaseTerms,
    policy_output,
)


def envelope():
    terms = PurchaseTerms(
        vendor="CloudMetrics Inc",
        monthly_price=Decimal("2000.00"),
        annual_price=Decimal("19680.00"),
    )
    context = CashContext(
        available_balance=Decimal("32000.00"),
        reserve_floor=Decimal("15000.00"),
        flows=(Flow(FlowKind.EXPECTED_INFLOW, Decimal("12000.00"), 4),),
    )
    policy = policy_output(context, terms)
    text = DEFAULT_QUOTE_PATH.read_text(encoding="utf-8")
    return build_envelope(
        request_id="req-test",
        trigger="initial",
        trusted_context={
            "available_balance": "32000.00",
            "reserve_floor": "15000.00",
            "purchase_request": {
                "vendor": "CloudMetrics Inc",
                "monthly_price": "2000.00",
                "annual_price": "19680.00",
                "merchant_category": "5734",
            },
        },
        policy_result=policy,
        passport=None,
        passport_status="NOT_PRESENT",
        documents=[{"id": "doc-quote-01", "text": text}],
    )


class DemoAgentTests(unittest.TestCase):
    def test_demo_agent_extracts_quote_and_echoes_engine(self):
        output = DemoAgent().analyze(envelope())
        self.assertEqual(output["recommendation"], "PROPOSE_MONTHLY")
        self.assertEqual(
            output["extracted_terms"]["vendor"]["value"], "CloudMetrics Inc"
        )
        self.assertEqual(
            output["extracted_terms"]["monthly_price"]["value"], "2000.00"
        )
        self.assertEqual(output["security_flags"], [])

    def test_terms_from_output_builds_purchase_request(self):
        output = DemoAgent().analyze(envelope())
        terms = terms_from_agent_output(output)
        self.assertEqual(terms["vendor"], "CloudMetrics Inc")
        self.assertEqual(terms["monthly_price"], "2000.00")
        self.assertEqual(terms["annual_price"], "19680.00")

    def test_envelope_keeps_untrusted_document_isolated(self):
        payload = envelope()
        self.assertIn("untrusted_documents", payload)
        self.assertNotIn("text", payload["trusted_context"])
        self.assertEqual(payload["policy_result"]["decision"], "PROPOSE_MONTHLY")

    def test_scan_document_flags_injection(self):
        text = DEFAULT_INJECTION_PATH.read_text(encoding="utf-8")
        flags = scan_document(text, "doc-injection")
        self.assertGreaterEqual(len(flags), 3)
        self.assertTrue(all(flag["disposition"] == "IGNORED_AS_DATA" for flag in flags))
        self.assertTrue(any("API key" in flag["excerpt"] for flag in flags))


class AgentValidationTests(unittest.TestCase):
    def _base(self):
        return DemoAgent().analyze(envelope())

    def test_rejects_card_control_fields(self):
        output = self._base()
        output["card_controls"] = {"allowed_transaction_count": "MULTIPLE"}
        with self.assertRaises(AgentOutputRejected):
            validate_agent_output(output)

    def test_rejects_unknown_recommendation(self):
        output = self._base()
        output["recommendation"] = "PAY_NOW"
        with self.assertRaises(AgentOutputRejected):
            validate_agent_output(output)

    def test_rejects_missing_required_fields(self):
        output = self._base()
        del output["human_action_required"]
        with self.assertRaises(AgentOutputRejected):
            validate_agent_output(output)

    def test_prompt_documents_the_trust_boundary(self):
        prompt = load_system_prompt()
        self.assertIn("TRUST BOUNDARY", prompt)
        self.assertIn("MUST exactly equal policy_result.decision", prompt)
        self.assertIn("Never derive a card limit", prompt)
        self.assertIn("Output one JSON object only", prompt)


if __name__ == "__main__":
    unittest.main()
