# db/seed.py — create + populate a tiny synthetic ledger (SQLite). No LLM here.
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "reconassist.db"

ACCOUNTS = [
    ("CSA-001", "Chase Settlement", "settlement"),
    ("BC-001",  "Bancontrol",       "control"),
    ("OPS-001", "Operating",        "operating"),
]

# (txn_id, date, account_id, amount, description, reference, reconciled)
TRANSACTIONS = [
    ("T-1001", "2026-03-01", "CSA-001", 1250.00, "Paymentech settlement", "PTS-88", 1),
    ("T-1002", "2026-03-02", "CSA-001", -450.00, "Merchant payout",       "PO-12",  1),
    ("T-1003", "2026-03-03", "CSA-001", 1500.00, "AMEX settlement",       "AXD-05", 0),  # unrec, >1000
    ("T-1004", "2026-03-05", "OPS-001",  -25.50, "Processing fee",        "FEE-9",  1),
    ("T-1005", "2026-03-06", "BC-001",  2000.00, "Risk hold",             "RHX-3",  0),  # unrec, >1000
    ("T-1006", "2026-03-08", "CSA-001",  -30.00, "Refund",                "RF-7",   1),
    ("T-1007", "2026-03-11", "OPS-001",  -88.00, "Bank fee",              "BF-2",   0),  # unrec
    ("T-1008", "2026-03-24", "CSA-001",  980.00, "PayPal settlement",     "PPM-4",  1),
]

def seed():
    if DB_PATH.exists():
        DB_PATH.unlink()  # fresh each run → deterministic
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("CREATE TABLE accounts (account_id TEXT PRIMARY KEY, name TEXT, type TEXT)")
    cur.execute("""CREATE TABLE transactions (
        txn_id TEXT PRIMARY KEY, txn_date TEXT, account_id TEXT, amount REAL,
        description TEXT, reference TEXT, reconciled INTEGER)""")
    cur.executemany("INSERT INTO accounts VALUES (?,?,?)", ACCOUNTS)
    cur.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?)", TRANSACTIONS)
    con.commit()
    con.close()
    print(f"seeded {len(ACCOUNTS)} accounts, {len(TRANSACTIONS)} transactions -> {DB_PATH}")

if __name__ == "__main__":
    seed()