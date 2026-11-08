"""Test-only control of SQLite's database clock ('now') for an isolated in-memory connection.

The schema evaluates expiry with the database clock (date('now') and strftime(..., 'now')). To test the
passage of time without waiting, this helper overrides date() and strftime() on ONE test connection only.
Every argument except 'now' goes to the real SQLite implementation, so the SQL under test is unchanged. It
is never used outside the test suite.
"""

from __future__ import annotations

import sqlite3


class DatabaseClock:
    def __init__(self, db) -> None:
        self._real = sqlite3.connect(":memory:")
        self.now: str | None = None          # None = real clock
        conn = db._conn
        for n in (1, 2, 3, 4):
            conn.create_function("date", n, self._fn("date"))
        for n in (2, 3, 4, 5):
            conn.create_function("strftime", n, self._fn("strftime"))

    def _fn(self, name):
        def f(*args):
            args = list(args)
            idx = 0 if name == "date" else 1
            if self.now is not None and len(args) > idx and args[idx] == "now":
                args[idx] = self.now
            return self._real.execute(f"SELECT {name}({', '.join('?' * len(args))})", args).fetchone()[0]
        return f

    def advance_days(self, days: int) -> None:
        """Move the database clock to the real current time plus `days` days."""
        self.now = self._real.execute("SELECT datetime('now', ?)", (f"{days:+d} days",)).fetchone()[0]

    def today(self) -> str:
        return self._real.execute("SELECT date(?)", (self.now or "now",)).fetchone()[0]
