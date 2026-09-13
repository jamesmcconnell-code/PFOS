# Local desktop backup and restore (step 7)

Use **File → Back Up Local Data…** and choose a new `.pfosbackup` filename on your
computer or an external drive. PFOS briefly closes its window and pauses its local
API, saves a consistent SQLite snapshot, and reopens the interface. Existing backup
files are not overwritten; choose a new filename each time.

The file contains financial data, household settings, accounts, password hashes,
and the secrets needed to reopen the household and decrypt saved connector credentials.
It is **not encrypted**. Save it in a protected location. Owner-only permissions are
requested, but the destination filesystem determines which permissions are supported.
Browser preferences and saved browser sessions are not included. This workflow does
not send files to a server or configure a backup schedule.

To restore, choose **File → Restore Local Backup…**, select a PFOS backup, and confirm
replacement. PFOS checks the format, checksums, SQLite integrity, foreign keys, and
migration revision before replacing data. It saves a recovery copy of the current
household under `data/backups/before-restore-*.pfosbackup`. After restore, sign in
using an account and password from the restored backup. Current browser login/view
preferences are cleared to avoid retaining a different household's session.

If PFOS cannot start because local files are missing or damaged, the startup error
dialog also offers **Restore Local Backup…**. Damaged originals are preserved as raw
files in `data/backups/before-restore-raw-*/` rather than being discarded. These raw
folders are for manual recovery, not selectable PFOS backup archives.

A restore interrupted between database and secrets replacement is rolled back from
its recovery copy on the next launch, before the API starts. Do not delete
`restore.pending` or its recovery files while an interrupted restore is pending.
If recovery itself cannot finish (for example, disk failure), startup stops and retains
the recovery state for another attempt.

Known older database revisions are backed up under `data/backups/before-upgrade-*`
before automatic migration. Unknown/newer or unversioned databases are refused.
Recovery copies on the same disk do not protect against losing that disk; save a
separate backup to another location for that purpose. Recovery copies are retained
without automatic pruning.

The supported archive limit is a 1 GiB uncompressed database and 64 KiB each for
secrets and metadata. Only restore backups you trust: checksums detect accidental
corruption, not who created a file. Windows and ARM execution remain unverified.

Developer verification:

```sh
npm run build:backend --prefix desktop
npm run test:backup --prefix desktop
DATABASE_URL=sqlite:// PYTHONPATH=backend python -m pytest backend/tests/test_desktop_backup.py -q
```

The Electron test uses native menu handlers with automated test-only file selections,
a temporary household, and the frozen backend. Source tests cover snapshot consistency
with WAL data, restore/recovery copies, corrupted archives, interrupted replacement,
missing/damaged profiles, and backup before schema migration.

Implementation references: [SQLite backup API in Python](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)
and [Electron native dialogs](https://www.electronjs.org/docs/latest/api/dialog).

The existing [encrypted PostgreSQL backup workflow](BACKUPS.md) is for the server
installation and remains separate from these local desktop archives.
