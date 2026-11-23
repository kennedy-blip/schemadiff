import json
import re
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def quote_ident(value):
    if not IDENT.match(value):
        raise ValueError("Unsupported SQL identifier: " + str(value))
    return '"' + value.replace('"', '""') + '"'

def connect_and_inspect(ddl):
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(ddl)
    tables = {}
    indexes = {}
    for (name, sql) in db.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        qname = quote_ident(name)
        cols = []
        for row in db.execute("PRAGMA table_info(" + qname + ")"):
            cols.append({
                "name": row[1], "type": (row[2] or "").upper(),
                "notnull": bool(row[3]), "default": row[4], "pk": int(row[5])
            })
        tables[name] = {"columns": cols, "sql": sql or ""}
        indexes[name] = []
        for idx in db.execute("PRAGMA index_list(" + qname + ")"):
            idx_name = idx[1]
            idx_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)).fetchone()
            indexes[name].append({"name": idx_name, "unique": bool(idx[2]), "sql": idx_sql[0] if idx_sql else None})
    db.close()
    return tables, indexes

def column_map(table):
    return {c["name"]: c for c in table["columns"]}

def type_rank(value):
    t = (value or "").upper()
    if "INT" in t: return 4
    if any(x in t for x in ("CHAR", "TEXT", "CLOB")): return 3
    if any(x in t for x in ("REAL", "FLOA", "DOUB")): return 2
    if any(x in t for x in ("NUM", "DEC")): return 2
    return 1

def create_table_sql(name, sql):
    if not sql:
        raise ValueError("Cannot reconstruct table " + name)
    return sql.rstrip().rstrip(";") + ";"

def plan_changes(old, new, old_idx, new_idx):
    changes, forward, rollback = [], [], []
    old_names, new_names = set(old), set(new)
    for name in sorted(new_names - old_names):
        forward.append(create_table_sql(name, new[name]["sql"]))
        changes.append({"table": name, "kind": "table_added", "severity": "SAFE_ADDITIVE", "message": "New table added"})
    for name in sorted(old_names - new_names):
        forward.append("DROP TABLE " + quote_ident(name) + ";")
        rollback.insert(0, create_table_sql(name, old[name]["sql"]))
        changes.append({"table": name, "kind": "table_removed", "severity": "BREAKING_DESTRUCTIVE", "message": "Table removal destroys stored data"})
    for name in sorted(old_names & new_names):
        before, after = column_map(old[name]), column_map(new[name])
        added, removed = sorted(set(after)-set(before)), sorted(set(before)-set(after))
        modified = []
        for col in sorted(set(before)&set(after)):
            if before[col] != after[col]:
                modified.append((col, before[col], after[col]))
        if removed or modified:
            # SQLite table rebuild preserves common columns; defaults/nullability are applied by target DDL.
            temp = quote_ident("__schemadiff_new_" + name)
            target_sql = new[name]["sql"]
            if not target_sql:
                raise ValueError("Cannot rebuild table without CREATE TABLE SQL: " + name)
            rebuilt = re.sub(r"(?is)^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[\"\x60\[][^)\"\x60\]]+[\"\x60\]]|[A-Za-z_][A-Za-z0-9_]*)", "CREATE TABLE " + temp, target_sql, count=1)
            if rebuilt == target_sql:
                raise ValueError("Could not safely rewrite CREATE TABLE for " + name)
            common = [c for c in before if c in after]
            if common:
                cols = ", ".join(quote_ident(c) for c in common)
                forward.extend(["ALTER TABLE " + quote_ident(name) + " RENAME TO " + quote_ident("__schemadiff_old_" + name) + ";",
                                rebuilt + ";",
                                "INSERT INTO " + temp + " (" + cols + ") SELECT " + cols + " FROM " + quote_ident("__schemadiff_old_" + name) + ";",
                                "DROP TABLE " + quote_ident("__schemadiff_old_" + name) + ";",
                                "ALTER TABLE " + temp + " RENAME TO " + quote_ident(name) + ";"])
            else:
                forward.extend(["DROP TABLE " + quote_ident(name) + ";", create_table_sql(name, new[name]["sql"])])
            changes.append({"table": name, "kind": "column_removed" if removed else "column_modified", "columns": removed + [x[0] for x in modified], "severity": "BREAKING_DESTRUCTIVE", "message": "Column removal or modification requires a table rebuild"})
            rollback.insert(0, "/* Rollback rebuild for " + name + " should restore a verified backup when data was removed. */\n" + create_table_sql(name, old[name]["sql"]))
        for col in added:
            c = after[col]
            clause = "ALTER TABLE " + quote_ident(name) + " ADD COLUMN " + quote_ident(col) + " " + (c["type"] or "TEXT")
            if c["notnull"]:
                if c["default"] is None:
                    clause += " /* NOT NULL requires staged backfill before enforcement */"
                else:
                    clause += " NOT NULL DEFAULT " + str(c["default"])
            elif c["default"] is not None:
                clause += " DEFAULT " + str(c["default"])
            forward.append(clause + ";")
            rollback.insert(0, "/* SQLite cannot DROP COLUMN on all supported versions; rebuild " + name + " from the previous schema. */")
            severity = "CAUTION_LOCK_RISK" if c["notnull"] and c["default"] is None else "SAFE_ADDITIVE"
            changes.append({"table": name, "kind": "column_added", "column": col, "severity": severity, "message": "Column added" + ("; NOT NULL without DEFAULT requires expand/backfill/contract" if severity != "SAFE_ADDITIVE" else "")})
        old_set = {i["name"]: i for i in old_idx.get(name, []) if i["sql"]}
        new_set = {i["name"]: i for i in new_idx.get(name, []) if i["sql"]}
        for idx in sorted(set(new_set)-set(old_set)):
            forward.append(new_set[idx]["sql"].rstrip(";") + ";")
            rollback.insert(0, "DROP INDEX " + quote_ident(idx) + ";")
            changes.append({"table": name, "kind": "index_added", "index": idx, "severity": "CAUTION_LOCK_RISK", "message": "Index creation may scan or lock a large table"})
        for idx in sorted(set(old_set)-set(new_set)):
            forward.append("DROP INDEX " + quote_ident(idx) + ";")
            rollback.insert(0, old_set[idx]["sql"].rstrip(";") + ";")
            changes.append({"table": name, "kind": "index_removed", "index": idx, "severity": "CAUTION_LOCK_RISK", "message": "Index removed"})
    return changes, forward, rollback

def analyze(current, target):
    old, old_idx = connect_and_inspect(current)
    new, new_idx = connect_and_inspect(target)
    changes, forward, rollback = plan_changes(old, new, old_idx, new_idx)
    severities = {c["severity"] for c in changes}
    risk = "BREAKING_DESTRUCTIVE" if "BREAKING_DESTRUCTIVE" in severities else ("CAUTION_LOCK_RISK" if "CAUTION_LOCK_RISK" in severities else "SAFE_ADDITIVE")
    dry_run = {"passed": False, "message": ""}
    try:
        test = sqlite3.connect(":memory:")
        test.execute("PRAGMA foreign_keys = ON")
        test.executescript(current)
        test.executescript("\n".join(forward))
        test.close()
        dry_run = {"passed": True, "message": "Forward migration executed successfully in isolated SQLite"}
    except Exception as exc:
        dry_run = {"passed": False, "message": str(exc)}
    return {
        "risk": risk, "changes": changes,
        "tables": {"added": sorted(set(new)-set(old)), "removed": sorted(set(old)-set(new))},
        "forwardSql": "\n\n".join(forward) or "-- No schema changes detected.",
        "rollbackSql": "\n\n".join(rollback) or "-- No rollback required.",
        "dryRun": dry_run,
        "metadata": {"currentTables": len(old), "targetTables": len(new), "generatedAt": datetime.now(timezone.utc).isoformat()}
    }

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.split("?")[0] != "/api/diff":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 500_000:
                raise ValueError("Request body must be between 1 byte and 500 KB")
            payload = json.loads(self.rfile.read(length))
            current, target = payload.get("currentDdl", ""), payload.get("targetDdl", "")
            if not isinstance(current, str) or not isinstance(target, str) or not current.strip() or not target.strip():
                raise ValueError("Both currentDdl and targetDdl are required SQL strings")
            if len(current) + len(target) > 400_000:
                raise ValueError("Combined DDL exceeds 400 KB")
            result = analyze(current, target)
            self.respond(200, result)
        except (ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception as exc:
            self.respond(500, {"error": "Diff failed: " + str(exc)})

    def respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()
