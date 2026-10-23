"""Retry registry tests, including a 16-thread duplicate-ID race."""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from mandate.retry_registry import (
    FAILED_RETRYABLE,
    FAILED_TERMINAL,
    SUCCEEDED,
    FingerprintMismatch,
    RequestIdMismatch,
    RetryRegistry,
    RetryRegistryError,
    TerminalNotConfirmed,
    TerminalOperation,
    fingerprint_payload,
)


class RetryRegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="mandate-retry-test-"))
        self.path = self.directory / "registry.sqlite"
        self.registry = RetryRegistry(self.path)
        self.fingerprint = fingerprint_payload({"amount": "2000.00", "vendor": "CloudMetrics"})

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_first_call_mints_request_id(self):
        decision = self.registry.begin_operation("op-1", self.fingerprint)
        self.assertFalse(decision.replay)
        self.assertTrue(decision.request_id.startswith("req_"))
        self.assertEqual(decision.status, "IN_FLIGHT")

    def test_replay_in_flight_same_id(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        second = self.registry.begin_operation("op-1", self.fingerprint)
        self.assertTrue(second.replay)
        self.assertEqual(first.request_id, second.request_id)

    def test_replay_after_retryable_failure_same_id(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        self.registry.record_result(
            "op-1", first.request_id, FAILED_RETRYABLE, result={"http_status": 503}
        )
        retry = self.registry.begin_operation("op-1", self.fingerprint)
        self.assertTrue(retry.replay)
        self.assertEqual(retry.status, FAILED_RETRYABLE)
        self.assertEqual(retry.request_id, first.request_id)
        self.assertEqual(retry.result, {"http_status": 503})

    def test_replay_after_success_returns_result(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        self.registry.record_result(
            "op-1", first.request_id, SUCCEEDED, result={"card_id": "card_123"}
        )
        replay = self.registry.begin_operation("op-1", self.fingerprint)
        self.assertTrue(replay.replay)
        self.assertEqual(replay.status, SUCCEEDED)
        self.assertEqual(replay.request_id, first.request_id)
        self.assertEqual(replay.result, {"card_id": "card_123"})

    def test_fingerprint_change_rejected(self):
        self.registry.begin_operation("op-1", self.fingerprint)
        with self.assertRaises(FingerprintMismatch):
            self.registry.begin_operation("op-1", "different-fingerprint")

    def test_terminal_operation_blocked(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        self.registry.record_result(
            "op-1",
            first.request_id,
            FAILED_TERMINAL,
            result={"confirmed_by": "GET"},
            terminal_confirmed=True,
        )
        with self.assertRaises(TerminalOperation):
            self.registry.begin_operation("op-1", self.fingerprint)

    def test_terminal_requires_get_confirmation(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        with self.assertRaises(TerminalNotConfirmed):
            self.registry.record_result("op-1", first.request_id, FAILED_TERMINAL)
        row = self.registry.get("op-1")
        self.assertEqual(row["status"], "IN_FLIGHT")

    def test_request_id_mismatch_rejected(self):
        self.registry.begin_operation("op-1", self.fingerprint, request_id="req_fixed")
        with self.assertRaises(RequestIdMismatch):
            self.registry.record_result("op-1", "req_other", SUCCEEDED)

    def test_succeeded_cannot_transition_to_failure(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        self.registry.record_result("op-1", first.request_id, SUCCEEDED)
        with self.assertRaises(RetryRegistryError):
            self.registry.record_result("op-1", first.request_id, FAILED_RETRYABLE)

    def test_concurrent_same_operation_gets_one_id(self):
        barrier = threading.Barrier(16)
        ids: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            try:
                decision = self.registry.begin_operation("shared-op", self.fingerprint)
                with lock:
                    ids.append(decision.request_id)
            except Exception as exc:  # pragma: no cover - surfaced by assertion
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(ids), 16)
        self.assertEqual(len(set(ids)), 1)

    def test_concurrent_distinct_operations_get_unique_ids(self):
        barrier = threading.Barrier(16)
        ids: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(index: int):
            barrier.wait()
            try:
                decision = self.registry.begin_operation(
                    f"op-{index}", self.fingerprint
                )
                with lock:
                    ids.append(decision.request_id)
            except Exception as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(ids), 16)
        self.assertEqual(len(set(ids)), 16)

    def test_persistence_across_instances(self):
        first = self.registry.begin_operation("op-1", self.fingerprint)
        reopened = RetryRegistry(self.path)
        decision = reopened.begin_operation("op-1", self.fingerprint)
        self.assertEqual(decision.request_id, first.request_id)
        self.assertTrue(decision.replay)

    def test_fingerprint_payload_stable(self):
        left = fingerprint_payload({"b": 2, "a": 1})
        right = fingerprint_payload({"a": 1, "b": 2})
        self.assertEqual(left, right)
        self.assertNotEqual(left, fingerprint_payload({"a": 1, "b": 3}))


if __name__ == "__main__":
    unittest.main()
