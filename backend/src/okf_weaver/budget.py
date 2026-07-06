"""Process-wide spend ceiling — the cost-DoS backstop for the paid endpoint.

The service is stateless with no accounts, so it can't bound a single *user*
(an abuser rotates IPs). Instead it bounds *total* estimated spend within a
rolling window: once the window's ceiling is reached, `/api/generate` refuses
new work until the window rolls over. Per-request table/column caps bound how
far a single in-flight request can overshoot the ceiling.

In-memory and per-process, which is correct for the single-instance Render
deployment. If the backend is ever scaled to multiple instances, back this with
a shared store (e.g. Redis) so the ceiling is global rather than per-instance.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

#: Rolling window length for the budget. Estimated spend resets each window.
DEFAULT_WINDOW_SECONDS = 24 * 60 * 60

#: User-facing refusal text. Deliberately generic — it never reveals the ceiling
#: or current spend, so probing the endpoint leaks nothing about the budget.
CAPACITY_MESSAGE = "Generation is temporarily at capacity. Please try again later."


class BudgetExceeded(Exception):
    """Raised when a generation would run past the window's spend ceiling."""


class SpendGuard:
    """Thread-safe rolling-window ceiling on estimated generation spend.

    Args:
        budget_usd: Ceiling in USD per window. ``<= 0`` disables the guard
            (``remaining`` is ``None``; ``ensure_available``/``record`` no-op).
        window_seconds: Length of the rolling window.
        clock: Monotonic time source; injectable for tests.
    """

    def __init__(
        self,
        budget_usd: float,
        *,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.budget_usd = budget_usd
        self.window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._spent = 0.0
        self._window_start = clock()

    def _roll_locked(self) -> None:
        now = self._clock()
        if now - self._window_start >= self.window_seconds:
            self._window_start = now
            self._spent = 0.0

    @property
    def enabled(self) -> bool:
        return self.budget_usd > 0

    def remaining(self) -> float | None:
        """USD left in the current window, or ``None`` when the guard is off."""
        if not self.enabled:
            return None
        with self._lock:
            self._roll_locked()
            return max(0.0, self.budget_usd - self._spent)

    def ensure_available(self) -> None:
        """Raise `BudgetExceeded` if the window's ceiling is already reached.

        Raises:
            BudgetExceeded: If no budget remains in the current window.
        """
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            raise BudgetExceeded(CAPACITY_MESSAGE)

    def record(self, cost_usd: float) -> None:
        """Add an estimated cost to the current window's running total."""
        if not self.enabled:
            return
        with self._lock:
            self._roll_locked()
            self._spent += max(0.0, cost_usd)

    def reset(self) -> None:
        """Clear the window's spend (used between tests)."""
        with self._lock:
            self._spent = 0.0
            self._window_start = self._clock()


#: Process-wide singleton. Set `OKF_DAILY_BUDGET_USD` to enable (0/unset = off).
guard = SpendGuard(float(os.getenv("OKF_DAILY_BUDGET_USD", "0") or "0"))
