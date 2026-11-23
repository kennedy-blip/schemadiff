# SchemaDiff

SchemaDiff is a browser-based SQLite schema diff, migration-risk linter, and rollout planner. It compares two real SQLite DDL snapshots, inspects catalog metadata, generates forward and rollback SQL, and dry-runs the forward plan against an isolated in-memory database.

## Features
- Real SQLite parsing and catalog inspection (tables, columns, indexes).
- Added, removed, and modified column detection, including type and nullability changes.
- Risk classification: SAFE_ADDITIVE, CAUTION_LOCK_RISK, BREAKING_DESTRUCTIVE.
- Forward and rollback SQL with a SQLite execution dry-run.
- Three realistic migration presets and a browser-only offline demo fallback.

## Run locally
Requires Python 3.12+ (standard library only).

```bash
python3 -m http.server 8000 --directory public
```

The static server does not provide the API. For full functionality, deploy to Vercel or run a compatible local Python serverless adapter. Open the deployed URL and choose a preset or paste your own SQLite DDL.

## Deploy to Vercel
Import this repository into Vercel. The `public/` directory is the static output and `api/*.py` are Python serverless functions. No Node build step or TypeScript is used.

## API
- `GET /api/presets` — sample migration scenarios.
- `POST /api/diff` — JSON body: `{ "currentDdl": "...", "targetDdl": "..." }`.

## Safety notes
SchemaDiff is an advisory planner, not a production migration runner. Review generated SQL, test against a representative copy, take backups, and plan deployment/locking behavior for your database engine. SQLite dry-run success does not guarantee equivalent behavior on PostgreSQL, MySQL, or a production workload.
