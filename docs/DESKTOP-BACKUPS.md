# PFOS backups, restore, and moving to another Mac

Open **File → Backup and Migration Guide** in the macOS app for these instructions
and a check of the signed-in household's current Plaid configuration. The guide opens
automatically after a successful restore and is also linked from Settings → Plaid.

## What moves with a backup

A `.pfosbackup` file contains the financial database, local users and password hashes,
preferences stored in the database, encrypted bank/exchange tokens, and the runtime
keys needed to read the database's credentials. It is **not encrypted as an archive**.
Since the decryption keys are included, protect it as you would readable financial
data and account secrets. Share the DMG with someone who needs the app, not a copy of
your household backup.

The installation's Plaid developer secret and its Keychain-protected configuration
file are excluded. Bank records can still contain the associated Plaid client ID and
environment as identity metadata. Browser sign-in sessions and device preferences,
such as Blur financial numbers, are excluded. Destination Plaid developer settings
remain unchanged on restore. Browser local storage is cleared, so sign in again and
re-enable device preferences as needed.

The archive format is unchanged: `pfos.db`, `runtime.json`, and `manifest.json` with
integrity checksums and a migration revision. Do not edit or extract those files as
a substitute for the restore command.

## Back up

1. Finish or cancel bank authorization and wait for sync/credential operations.
2. Choose **File → Back Up Local Data…** and a new `.pfosbackup` filename.
3. Keep it in a protected location and maintain a separate copy away from this Mac.
4. Keep a known-good backup before application updates or moving machines. Copying
   the app bundle does not back up your data. Copying a live database file can miss
   pending writes; use PFOS's backup command.

## Restore or move machines

1. Install a compatible PFOS version on the destination Mac and transfer the backup
   privately. Keep the source Mac and backup until you have verified the destination.
2. Choose **File → Restore Local Backup…**. This is available before registering a
   household. If startup fails, the error dialog also offers restore.
3. Review the confirmation: this replaces destination data and does not merge it.
   PFOS validates the archive and preserves current data in a recovery copy first.
4. Sign in with the account/password that existed when the backup was made. A newer
   password changed after that backup will not be the restored password.
5. Review accounts, transaction history, and preferences. Re-enable the visual privacy
   toggle if desired, then review Plaid before syncing. Other providers' restored
   tokens may also require renewed access from their provider.
6. Keep your backup and recovery copy until the restored household is verified.

Both Macs maintain independent databases. There is no automatic synchronization or
merge between them. Replacing the app with an updated DMG on the same Mac normally
needs no restore: quit PFOS, replace the application, and reopen it. The local data
profile and protected Plaid configuration stay on that Mac.

## Plaid after restoring

| Situation | Action |
| --- | --- |
| New Mac, no developer credentials | Enter your own settings in Settings → Plaid. Do not copy another Mac's encrypted credential file. |
| Same Plaid Client ID/environment | Validate with the account's current secret. Existing bank tokens may work; verify by syncing. |
| Bank requests authorization | Connected Sources → Manage → Reauthorize bank preserves existing accounts/history. |
| Different or unknown client/environment, or invalid token | Restore the original credentials or connect separately. Review overlap before importing from the new source. |
| No Plaid account wanted | Review restored data, use manual entry, or import CSV. Plaid stays disabled. |

A pending Link session from an old backup can be expired or tied to another setup.
Cancel it and start again if needed. PFOS does not merge account IDs/history across
Plaid accounts. A stored token or matching configuration is not evidence that live
bank access is healthy. See [Plaid setup](DESKTOP-PLAID.md).

## Recovery

**File → Show Data Folder…** opens the local data directory. Its `backups` folder
contains `before-restore-*.pfosbackup` recovery files. Damaged/incomplete original
files can instead be kept in a `before-restore-raw-*` folder for manual recovery;
keep that folder rather than treating it as a normal backup archive.

Unsupported, corrupted, or tampered archives are rejected before replacing the live
database. Use a known-good backup or a compatible newer application. Do not delete
original files when troubleshooting. The existing startup recovery mechanism handles
interrupted restore operations before opening the database.

Verification uses synthetic households, malformed archives, and isolated desktop
profiles; it does not contact banks or alter the user's live household.
