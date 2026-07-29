# Personal Financial Operating System (PFOS)

A private, self-hosted financial operating system for one household. It is intentionally not multi-tenant SaaS: each deployment is isolated, low-cost, and controlled by the household.

## Structure

```
backend/       FastAPI, SQLAlchemy domain models, Alembic migration, seed script, tests
frontend/      Next.js App Router, TypeScript, Tailwind responsive dashboard
docker-compose.yml  PostgreSQL + API + web application
```

## Architecture and decisions

- PostgreSQL is the source of truth. All 15 requested entities use UUID keys, foreign keys, and audit timestamps (join-only `transaction_tags` is the intentional exception to audit fields).
- The API scopes every household resource through the authenticated member. Passwords are bcrypt hashes; JWTs are short-lived bearer credentials (24 hours by default).
- Imports use a stable SHA-256 fingerprint of account/date/amount/description, so re-importing a statement does not double-count transactions.
- Financial metrics are derived, not duplicated. Savings rate is monthly savings divided by monthly income; emergency target is surfaced by the dashboard alert using six months of essential monthly spend.

## Run locally

1. `cp .env.example .env` and replace `JWT_SECRET` and database password.
2. `docker compose up --build`
3. In another terminal run `docker compose exec api python -m app.seed` for demo data.
4. Visit http://localhost:3000 and sign in with `james@example.com` / `change-me-now`; change the password by registering a private account for real use.

For development without Docker, install `backend/requirements.txt`, set `DATABASE_URL`, run `cd backend && alembic upgrade head`, and use `uvicorn app.main:app --reload`. Install frontend dependencies with `cd frontend && npm install && npm run dev`.

## API surface

`/api/v1/auth` supplies registration, login and current-user endpoints. Authenticated routes cover `/household`, `/accounts`, `/categories`, `/transactions`, `/imports/preview`, `/imports/commit`, `/imports`, `/goals`, `/dashboard`, `/forecast`, and `/analysis/live-on-one-income`. The interactive OpenAPI contract is at `http://localhost:8000/docs`.

## Tests

Run backend tests with `cd backend && pytest`. The test suite validates password and JWT security primitives; endpoint behavior is designed for integration testing against PostgreSQL.

## Deployment

Deploy the Compose stack to a private VPS or a home server behind HTTPS (Caddy or a managed reverse proxy). Do not expose PostgreSQL publicly. Persist the `postgres_data` volume, set a unique high-entropy JWT secret, maintain encrypted backups, and update images regularly.

## Data integrations

PFOS normalizes CSV, Plaid, Coinbase Advanced Trade, and Gemini data into the same `accounts` and `transactions` tables. Connector credentials are Fernet-encrypted at rest using `CONNECTION_ENCRYPTION_KEY` (separate from `JWT_SECRET` in production); API responses only disclose whether credentials are configured.

- **CSV:** Upload through the CSV Import page. The file must contain `date`, `description`, and `amount` columns (case-insensitive forms are accepted). It runs through the shared normalization and deduplication path.
- **Plaid:** Set `PLAID_CLIENT_ID`, `PLAID_SECRET`, and `PLAID_ENVIRONMENT`. The API provides Link-token and public-token exchange endpoints, then synchronizes accounts and transactions through `/transactions/sync`.
- **Coinbase and Gemini:** Add a read-only API key and secret on the Connections page. The current adapters synchronize exchange balances; their isolated connector classes are the extension point for trade and ledger-history normalization as those account permissions are enabled.

Every remote transaction retains provider provenance (`connection_id` and `external_id`) and is deduplicated first by provider ID and then by a stable PFOS fingerprint. Sync attempts are recorded in `connection_syncs` without recording credential values or raw provider payloads.
