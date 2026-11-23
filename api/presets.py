import json
from http.server import BaseHTTPRequestHandler

PRESETS = [
    {
        "id": "mpesa-idempotency",
        "name": "Add M-Pesa Idempotency Key & Index",
        "description": "Add a nullable request key, then enforce uniqueness with an index to prevent duplicate payment processing.",
        "currentDdl": """CREATE TABLE payments (
  id INTEGER PRIMARY KEY,
  checkout_request_id TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);""",
        "targetDdl": """CREATE TABLE payments (
  id INTEGER PRIMARY KEY,
  checkout_request_id TEXT NOT NULL,
  idempotency_key TEXT,
  amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_payments_idempotency_key ON payments(idempotency_key);"""
    },
    {
        "id": "drop-legacy-ledger",
        "name": "Drop Legacy Ledger Column (Breaking)",
        "description": "Remove a legacy reconciliation field still potentially consumed by reports and downstream jobs.",
        "currentDdl": """CREATE TABLE ledger_entries (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL,
  legacy_reference TEXT,
  memo TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ledger_account ON ledger_entries(account_id);""",
        "targetDdl": """CREATE TABLE ledger_entries (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL,
  memo TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ledger_account ON ledger_entries(account_id);"""
    },
    {
        "id": "split-customer-profile",
        "name": "Split Customer Profile & Add NOT NULL",
        "description": "Introduce a profile table and a required customer tier. A required field without a safe default needs a staged rollout.",
        "currentDdl": """CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT,
  phone TEXT
);""",
        "targetDdl": """CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT,
  phone TEXT,
  tier TEXT NOT NULL
);
CREATE TABLE customer_profiles (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL UNIQUE,
  display_name TEXT,
  FOREIGN KEY(customer_id) REFERENCES customers(id)
);"""
    }
]

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/api/presets":
            self.send_error(404)
            return
        body = json.dumps({"presets": PRESETS}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, OPTIONS")
        self.end_headers()
