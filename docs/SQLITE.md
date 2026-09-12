# SQLite storage: desktop step 1

PFOS can initialize and use a local SQLite database through the existing Python API.
This covers the database compatibility step. The [desktop window and bundled API](DESKTOP.md)
are now implemented in steps 2–3. An installer, automatic backups, and transfer of
an existing PostgreSQL database remain subsequent work.

## Development setup

Use Python 3.12 for the current pinned backend dependencies. From `backend/`,
install `requirements.txt` into a virtual environment. Choose a new database file
in an existing directory, then run:

```sh
export DATABASE_URL='sqlite:////absolute/path/to/pfos.db'
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The generated secret above is for temporary development. Preserve a stable secret
in private configuration for continued use; changing it invalidates logins and,
without a separate `CREDENTIAL_ENCRYPTION_KEY`, affects stored connector credentials.
The desktop first-launch setup will manage these secrets in a later step.

An absolute SQLite path has four slashes after `sqlite:` on macOS/Linux. The
backend's default `sqlite:///./pfos.db` is relative to the working directory, so use
an explicit absolute path when checking persistence. Environment variables override
`.env` settings. No database is seeded automatically.

SQLite database files and their journal/WAL sidecars are ignored by Git.

## Migration and connection behavior

- The initial revision now contains a frozen schema rather than importing current
  models. Later revisions introduce their own tables and columns exactly once.
- The existing revision IDs and migration chain are retained. SQLite uses Alembic
  batch table alterations; PostgreSQL continues to use ordinary ALTER statements.
- Symbol backfills, category deduplication, date backfills, and SQL aliases work on
  SQLite. The category expression index is explicitly preserved during rebuilding.
- New non-null columns receive their backfill defaults before those defaults are
  removed in a separate batch, preserving existing records during upgrades.
- Every application SQLite connection enables foreign keys and a 30-second lock
  timeout. SQLAlchemy explicitly begins transactions for reads, writes, and DDL.
- Migrations use a separate connection with foreign-key enforcement temporarily
  disabled for table rebuilding. A foreign-key integrity check runs before commit;
  a failure rolls back schema changes, data changes, and the revision marker.
  Run migrations with the application stopped.
- Authenticated user IDs are converted from token strings to UUID objects before
  database lookup. CSV account links are flushed before the import pipeline queries
  them, preventing the first import from silently skipping rows.

These connection choices follow the [SQLAlchemy SQLite documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
and [Alembic batch migration guidance](https://alembic.sqlalchemy.org/en/latest/batch.html).

## Verification

From `backend/`, with the test dependencies installed:

```sh
python -m pytest -q
python -m pytest -q --migrated-sqlite
```

The second command copies a freshly migrated, empty database into a separate file
for each existing database scenario and uses the application connection settings.
The dedicated storage tests always use temporary migrated files, with either command.
Neither command needs real household data or a running PostgreSQL server.

Verified on Python 3.12:

- Fresh upgrade through `0034_smart_tagging_learning` and a repeated upgrade.
- Tables, columns, nullability, and foreign keys match the application models.
- A populated initial database upgrades while preserving UUIDs, amounts, dates,
  transaction/category relationships, and the recurring-expense start-date backfill.
- Orphan records and duplicate category names are rejected; delete cascades and
  SET NULL actions work; failed writes and failed upgrades roll back.
- Registration, authenticated requests, CSV import/re-import deduplication,
  dashboard totals, planner, reports, forecast, category tracker, and goals.
- Closing all connections and reopening the same file preserves login and totals.
- Existing savings, household settlement, and smart-tagging scenarios pass with
  foreign-key enforcement and the migrated schema.

Four existing financial tests used August 2026 scenarios with the real current
clock. Their scenario dates and expense-rule start dates are now explicit so results
remain stable as time passes. Financial formulas were not changed.

## Limits of this verification

PostgreSQL migration SQL was generated successfully, but this change was not tested
against a live PostgreSQL server. Existing deployed revision markers are retained;
already-applied historical migrations do not automatically rerun.

SQLite stores numeric values differently from PostgreSQL's fixed-decimal NUMERIC.
The tests cover the current financial scenarios, cent-valued imports and totals,
and crypto balance persistence; they do not establish arbitrary-precision accounting
at every magnitude. The existing numeric models and calculation formulas are unchanged.

A database created directly with `Base.metadata.create_all()` without an Alembic
revision is not automatically adopted. Test with a new file. Migration of existing
household data, backup/restore, and automatic desktop upgrades remain separate steps.
