# tools/ledger.py — the internal ledger tool. A plain function over SQLite.
# Structured filters only (NO raw SQL from the caller) — safe + predictable.
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "reconassist.db"

def ledger_query(account_id=None, unreconciled_only=False, min_amount=None, month=None):
    """Query the internal ledger with structured filters. Returns a list of transaction dicts.

    account_id:        e.g. "CSA-001"  (None = all accounts)
    unreconciled_only: True → only reconciled = 0
    min_amount:        only transactions with amount >= this
    month:             "YYYY-MM" → only that month
    """
    clauses, params = [], []
    if account_id is not None:
        clauses.append("account_id = ?"); params.append(account_id)
    if unreconciled_only:
        clauses.append("reconciled = 0")
    if min_amount is not None:
        clauses.append("amount >= ?"); params.append(min_amount)
    if month is not None:
        clauses.append("substr(txn_date, 1, 7) = ?"); params.append(month)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row                    # rows behave like dicts
    rows = con.execute(
        "SELECT txn_id, txn_date, account_id, amount, description, reference, reconciled"
        f" FROM transactions{where} ORDER BY txn_date, txn_id", params,
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    # Hand-test against the oracle: unreconciled transactions over $1000.
    result = ledger_query(unreconciled_only=True, min_amount=1000)
    print([r["txn_id"] for r in result])
    assert len(result) == 2, f"expected 2 (hand-derived), got {len(result)}"
    print("OK: unreconciled >$1000 → 2 (matches the hand oracle)")