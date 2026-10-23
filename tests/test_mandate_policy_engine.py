"""47-test deterministic engine suite.

Run with ``python -m unittest discover -s tests`` or ``python -m mandate test``.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from mandate.mandate_policy_engine import (
    POLICY_VERSION,
    CashContext,
    Flow,
    FlowKind,
    FlowOutsideHorizon,
    FlowValidationError,
    InvalidTerms,
    PurchaseTerms,
    build_monthly_payments,
    evaluate_live_plan,
    evaluate_policy,
    forecast_plan,
    policy_output,
)
from mandate.money import MoneyError, format_money, parse_money


def terms(
    monthly: str = "2000.00",
    annual: str = "19680.00",
    *,
    currency: str = "USD",
    mcc: str = "5734",
    monthly_first_week: int = 0,
    annual_week: int = 0,
) -> PurchaseTerms:
    return PurchaseTerms(
        vendor="CloudMetrics Inc",
        monthly_price=Decimal(monthly),
        annual_price=Decimal(annual),
        currency=currency,
        merchant_category=mcc,
        monthly_first_week=monthly_first_week,
        annual_payment_week=annual_week,
    )


def context(
    balance: str,
    *,
    floor: str = "15000.00",
    flows: tuple[Flow, ...] = (),
    horizon: int = 8,
) -> CashContext:
    return CashContext(
        available_balance=Decimal(balance),
        reserve_floor=Decimal(floor),
        flows=flows,
        horizon_weeks=horizon,
    )


def initial_context() -> CashContext:
    return context(
        "32000.00",
        flows=(Flow(FlowKind.EXPECTED_INFLOW, Decimal("12000.00"), 4),),
    )


class MoneyParsingTests(unittest.TestCase):
    def test_parse_money_string_two_decimals(self):
        self.assertEqual(parse_money("19680.00"), Decimal("19680.00"))

    def test_parse_money_int(self):
        self.assertEqual(parse_money(2000), Decimal("2000"))

    def test_parse_money_decimal(self):
        self.assertEqual(parse_money(Decimal("0.01")), Decimal("0.01"))

    def test_parse_money_rejects_three_decimals(self):
        with self.assertRaises(MoneyError):
            parse_money("1.234")

    def test_parse_money_rejects_scientific_notation(self):
        for value in ("1e3", "1E+3", Decimal("1E+3")):
            with self.subTest(value=value):
                with self.assertRaises(MoneyError):
                    parse_money(value)

    def test_parse_money_rejects_nan_and_infinity(self):
        for value in ("NaN", "Infinity", float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(MoneyError):
                    parse_money(value)

    def test_parse_money_rejects_bool(self):
        with self.assertRaises(MoneyError):
            parse_money(True)

    def test_parse_money_rejects_whitespace(self):
        for value in (" 100.00", "100.00 ", "1,000.00", "+100.00"):
            with self.subTest(value=value):
                with self.assertRaises(MoneyError):
                    parse_money(value)

    def test_parse_money_rejects_negative(self):
        with self.assertRaises(MoneyError):
            parse_money("-1.00")

    def test_format_money_pads_cents(self):
        self.assertEqual(format_money(Decimal("2000")), "2000.00")


class ValidationTests(unittest.TestCase):
    def test_flow_rejects_zero_amount(self):
        with self.assertRaises(FlowValidationError):
            Flow(FlowKind.CONFIRMED_INFLOW, Decimal("0.00"), 0)

    def test_flow_rejects_unknown_kind(self):
        with self.assertRaises(FlowValidationError):
            Flow("NOT_A_KIND", Decimal("1.00"), 0)  # type: ignore[arg-type]

    def test_context_rejects_flow_outside_horizon(self):
        with self.assertRaises(FlowOutsideHorizon):
            context(
                "32000.00",
                flows=(Flow(FlowKind.CONFIRMED_INFLOW, Decimal("1.00"), 9),),
            )

    def test_context_rejects_negative_balance(self):
        with self.assertRaises(FlowValidationError):
            context("-1.00")

    def test_terms_rejects_bad_mcc(self):
        for mcc in ("57A4", "573", "57345", "５７３４"):
            with self.subTest(mcc=mcc):
                with self.assertRaises(InvalidTerms):
                    terms(mcc=mcc)

    def test_terms_normalizes_currency(self):
        self.assertEqual(terms(currency="usd").currency, "USD")

    def test_annual_week_outside_horizon_rejected(self):
        with self.assertRaises(FlowOutsideHorizon):
            evaluate_policy(context("32000.00"), terms(annual_week=9))

    def test_monthly_first_week_outside_horizon_rejected(self):
        with self.assertRaises(FlowOutsideHorizon):
            evaluate_policy(context("32000.00"), terms(monthly_first_week=9))

    def test_monthly_schedule_three_payments(self):
        payments = build_monthly_payments(terms(), 8)
        self.assertEqual([payment.week for payment in payments], [0, 4, 8])
        self.assertTrue(all(payment.amount == Decimal("2000.00") for payment in payments))

    def test_monthly_schedule_respects_first_week(self):
        payments = build_monthly_payments(terms(monthly_first_week=1), 8)
        self.assertEqual([payment.week for payment in payments], [1, 5])


class ScenarioTests(unittest.TestCase):
    def test_scenario_1_decision(self):
        self.assertEqual(
            evaluate_policy(initial_context(), terms()).decision,
            "PROPOSE_MONTHLY",
        )

    def test_scenario_1_annual_minimum(self):
        evaluation = evaluate_policy(initial_context(), terms())
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("12320.00"))
        self.assertEqual(evaluation.annual.confirmed_minimum_week, 0)

    def test_scenario_1_monthly_minimum(self):
        evaluation = evaluate_policy(initial_context(), terms())
        self.assertEqual(evaluation.monthly.confirmed_minimum_balance, Decimal("26000.00"))
        self.assertEqual(evaluation.monthly.confirmed_minimum_week, 8)

    def test_scenario_1_expected_inflow_changes_inclusive_only(self):
        evaluation = evaluate_policy(initial_context(), terms())
        self.assertEqual(
            evaluation.monthly.with_expected_minimum_balance, Decimal("28000.00")
        )
        self.assertEqual(evaluation.monthly.with_expected_minimum_week, 4)
        self.assertEqual(evaluation.monthly.with_expected_ending_balance, Decimal("38000.00"))

    def test_scenario_2_annual(self):
        evaluation = evaluate_policy(context("44000.00"), terms())
        self.assertEqual(evaluation.decision, "PROPOSE_ANNUAL")
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("24320.00"))

    def test_scenario_2_saving(self):
        self.assertEqual(
            evaluate_policy(context("44000.00"), terms()).annual_saving,
            Decimal("4320.00"),
        )

    def test_scenario_3_confirmed_inflow(self):
        ctx = context(
            "32000.00",
            flows=(Flow(FlowKind.CONFIRMED_INFLOW, Decimal("12000.00"), 4),),
        )
        evaluation = evaluate_policy(ctx, terms())
        self.assertEqual(evaluation.decision, "PROPOSE_MONTHLY")
        self.assertEqual(evaluation.monthly.confirmed_minimum_balance, Decimal("28000.00"))
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("12320.00"))

    def test_scenario_4_defer(self):
        evaluation = evaluate_policy(context("20000.00"), terms())
        self.assertEqual(evaluation.decision, "DEFER")
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("320.00"))
        self.assertEqual(evaluation.monthly.confirmed_minimum_balance, Decimal("14000.00"))

    def test_scenario_5_annual_after_confirmed_receipt(self):
        ctx = context(
            "32000.00",
            flows=(Flow(FlowKind.CONFIRMED_INFLOW, Decimal("12000.00"), 3),),
        )
        evaluation = evaluate_policy(ctx, terms(annual_week=4))
        self.assertEqual(evaluation.decision, "PROPOSE_ANNUAL")
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("24320.00"))
        self.assertEqual(evaluation.annual.confirmed_minimum_week, 4)
        self.assertEqual(evaluation.monthly.confirmed_minimum_balance, Decimal("30000.00"))

    def test_scenario_6_monthly_when_annual_costs_more(self):
        evaluation = evaluate_policy(
            context("50000.00"),
            terms(monthly="2000.00", annual="25000.00"),
        )
        self.assertEqual(evaluation.decision, "PROPOSE_MONTHLY")
        self.assertEqual(evaluation.annual_saving, Decimal("-1000.00"))
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("25000.00"))
        self.assertEqual(evaluation.monthly.confirmed_minimum_balance, Decimal("44000.00"))

    def test_scenario_7_exact_floor_is_safe(self):
        evaluation = evaluate_policy(context("34680.00"), terms())
        self.assertEqual(evaluation.decision, "PROPOSE_ANNUAL")
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("15000.00"))
        self.assertTrue(evaluation.annual.cash_safe)

    def test_scenario_8_one_cent_under_floor(self):
        evaluation = evaluate_policy(context("34679.99"), terms())
        self.assertEqual(evaluation.decision, "PROPOSE_MONTHLY")
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("14999.99"))
        self.assertFalse(evaluation.annual.cash_safe)

    def test_scenario_9_defer_expected_outflow(self):
        ctx = context(
            "17000.00",
            flows=(Flow(FlowKind.EXPECTED_OUTFLOW, Decimal("3000.00"), 1),),
        )
        evaluation = evaluate_policy(ctx, terms(monthly="500.00", annual="1000.00"))
        self.assertEqual(evaluation.decision, "DEFER")
        self.assertEqual(evaluation.annual.confirmed_minimum_balance, Decimal("13000.00"))
        self.assertEqual(evaluation.annual.confirmed_minimum_week, 1)
        self.assertEqual(evaluation.monthly.confirmed_minimum_balance, Decimal("12500.00"))
        self.assertEqual(evaluation.monthly.confirmed_minimum_week, 8)


class CashTreatmentTests(unittest.TestCase):
    def test_outflow_before_inflow_same_week(self):
        ctx = context(
            "16000.00",
            flows=(Flow(FlowKind.CONFIRMED_INFLOW, Decimal("10000.00"), 0),),
        )
        forecast = forecast_plan(ctx, build_monthly_payments(terms(monthly="1000.00"), 8), plan="MONTHLY")
        self.assertEqual(forecast.confirmed_minimum_balance, Decimal("15000.00"))
        self.assertEqual(forecast.confirmed_minimum_week, 0)

    def test_expected_outflow_always_counts(self):
        ctx = context(
            "32000.00",
            flows=(Flow(FlowKind.EXPECTED_OUTFLOW, Decimal("20000.00"), 1),),
        )
        forecast = forecast_plan(ctx, build_monthly_payments(terms(), 8), plan="MONTHLY")
        self.assertEqual(forecast.confirmed_minimum_balance, Decimal("6000.00"))
        self.assertEqual(
            forecast.with_expected_minimum_balance, Decimal("6000.00")
        )

    def test_expected_inflow_excluded_from_confirmed(self):
        ctx = context(
            "20000.00",
            flows=(Flow(FlowKind.EXPECTED_INFLOW, Decimal("10000.00"), 1),),
        )
        forecast = forecast_plan(ctx, build_monthly_payments(terms(), 8), plan="MONTHLY")
        self.assertEqual(forecast.confirmed_minimum_balance, Decimal("14000.00"))

    def test_expected_inflow_included_in_inclusive(self):
        ctx = context(
            "20000.00",
            flows=(Flow(FlowKind.EXPECTED_INFLOW, Decimal("10000.00"), 1),),
        )
        forecast = forecast_plan(ctx, build_monthly_payments(terms(), 8), plan="MONTHLY")
        self.assertEqual(forecast.with_expected_minimum_balance, Decimal("18000.00"))
        self.assertEqual(forecast.with_expected_minimum_week, 0)

    def test_annual_saving_can_be_negative(self):
        evaluation = evaluate_policy(
            context("50000.00"),
            terms(monthly="2000.00", annual="25000.00"),
        )
        self.assertLess(evaluation.annual_saving, Decimal("0.00"))

    def test_defer_when_no_plan_safe(self):
        evaluation = evaluate_policy(
            context("40000.00"),
            terms(monthly="10000.00", annual="30000.00"),
        )
        self.assertEqual(evaluation.decision, "DEFER")


class LivePlanTests(unittest.TestCase):
    def test_live_plan_hold_at_32k(self):
        result = evaluate_live_plan(context("32000.00"), terms(), 3)
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["minimum_balance"], "26000.00")
        self.assertEqual(result["minimum_week"], 8)
        self.assertTrue(result["recommendation_only"])

    def test_live_plan_hold_exactly_at_floor_21k(self):
        result = evaluate_live_plan(context("21000.00"), terms(), 3)
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["minimum_balance"], "15000.00")

    def test_live_plan_freeze_below_floor(self):
        result = evaluate_live_plan(context("20000.00"), terms(), 3)
        self.assertEqual(result["decision"], "RECOMMEND_FREEZE_AND_ESCALATE")
        self.assertEqual(result["shortfall"], "1000.00")

    def test_live_plan_zero_payments(self):
        result = evaluate_live_plan(context("16000.00"), terms(), 0)
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["minimum_balance"], "16000.00")

    def test_live_plan_rejects_too_many_payments(self):
        with self.assertRaises(FlowOutsideHorizon):
            evaluate_live_plan(context("32000.00"), terms(), 4)


class PolicyOutputTests(unittest.TestCase):
    def test_policy_output_flat_fields(self):
        output = policy_output(initial_context(), terms())
        for key in (
            "decision",
            "reason",
            "policy_version",
            "reserve_floor",
            "annual_saving",
            "annual_confirmed_minimum_balance",
            "annual_confirmed_minimum_week",
            "annual_with_expected_minimum_balance",
            "monthly_confirmed_minimum_balance",
            "monthly_confirmed_minimum_week",
            "monthly_with_expected_minimum_balance",
            "annual_payments",
            "monthly_payments",
            "live_plan_decision",
            "assumptions",
        ):
            self.assertIn(key, output)
        self.assertEqual(output["policy_version"], POLICY_VERSION)
        self.assertEqual(output["decision"], "PROPOSE_MONTHLY")

    def test_policy_output_live_plan_decision(self):
        output = policy_output(initial_context(), terms(), remaining_payments=3)
        self.assertEqual(output["live_plan_decision"], "HOLD")
        self.assertEqual(output["live_plan"]["minimum_balance"], "26000.00")

    def test_policy_output_assumptions(self):
        assumptions = policy_output(initial_context(), terms())["assumptions"]
        self.assertEqual(assumptions["horizon"], "inclusive 8-week horizon (weeks 0 to 8)")
        self.assertIn("expected inflows excluded", assumptions["conservative_case"])
        self.assertTrue(assumptions["synthetic_demo_data"])
        self.assertEqual(assumptions["available_balance_source"], "wallet available_amount, not total_amount")


if __name__ == "__main__":
    unittest.main()
