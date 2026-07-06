"""Tests for the process-wide spend ceiling (H1 cost-DoS backstop)."""

import pytest

from okf_weaver.budget import BudgetExceeded, SpendGuard


def test_disabled_guard_never_blocks_and_reports_no_remaining():
    guard = SpendGuard(0)
    assert guard.enabled is False
    assert guard.remaining() is None
    guard.record(1000.0)  # no-op
    guard.ensure_available()  # does not raise


def test_records_spend_and_reports_remaining():
    guard = SpendGuard(1.0)
    guard.record(0.6)
    assert guard.remaining() == pytest.approx(0.4)
    guard.ensure_available()  # still under the ceiling


def test_blocks_once_ceiling_reached():
    guard = SpendGuard(1.0)
    guard.record(1.0)
    assert guard.remaining() == 0.0
    with pytest.raises(BudgetExceeded):
        guard.ensure_available()


def test_overshoot_is_clamped_to_zero_remaining():
    guard = SpendGuard(1.0)
    guard.record(5.0)  # one big request can overshoot; remaining floors at 0
    assert guard.remaining() == 0.0
    with pytest.raises(BudgetExceeded):
        guard.ensure_available()


def test_window_rolls_over_and_resets_spend():
    now = [0.0]
    guard = SpendGuard(1.0, window_seconds=100, clock=lambda: now[0])
    guard.record(1.0)
    with pytest.raises(BudgetExceeded):
        guard.ensure_available()
    now[0] = 100.0  # window elapsed
    guard.ensure_available()  # rolled over, budget restored
    assert guard.remaining() == 1.0


def test_reset_clears_spend():
    guard = SpendGuard(1.0)
    guard.record(1.0)
    guard.reset()
    assert guard.remaining() == 1.0
