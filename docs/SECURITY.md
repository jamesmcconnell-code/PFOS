# Security and private deployment

PFOS is self-hosted. The public repository contains application code only; your database, `.env`, backup encryption identity, exported CSV files, and provider credentials must remain private.

## Bring your own keys

Copy `.env.example` to `.env`, generate unique secrets, and add only credentials for services you personally control. Use Plaid sandbox while evaluating PFOS. Production Plaid, Coinbase, and Gemini credentials should be least-privilege and read-only whenever the provider supports it.

Never put values in `.env.example`, source files, GitHub Issues, screenshots, or support requests. A contributor should be able to clone the repository without gaining access to any other household's data.

## Backups and recovery

The Docker volume keeps the database across normal reboots, but it is not a disaster-recovery backup. Create encrypted backups with `age`:

```bash
export BACKUP_RECIPIENT='age1...your-public-recipient...'
./scripts/backup-db.sh
```

Store the resulting `backups/*.dump.age` outside the laptop as well as locally. Back up the age private identity separately from the backup files. Test recovery into a non-production copy before relying on it:

```bash
BACKUP_IDENTITY_FILE=/secure/path/age-key.txt \
PFOS_RESTORE_CONFIRM=RESTORE \
./scripts/restore-db.sh backups/pfos-YYYYMMDDTHHMMSSZ.dump.age
```

The restore command destructively replaces the target database. Stop the application or restore into a separate Compose project/database when testing.

Also retain the `.env` values used by that database backup. In particular, a database backup alone cannot recover saved provider credentials without the secret used to encrypt them. Existing PFOS installations that have not configured a dedicated credential-encryption key use `JWT_SECRET` as the compatibility fallback, so preserve that value with their backup.

## Publishing checklist

1. Rotate any credentials that were ever committed or pushed.
2. Remove secret-bearing files from all Git history before making the repository public.
3. Confirm `.env`, `backups/`, exports, and database files are ignored.
4. Enable GitHub secret scanning and push protection.
5. Keep PostgreSQL private; expose the web/API only through authenticated HTTPS.
