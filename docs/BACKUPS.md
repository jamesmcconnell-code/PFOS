# PFOS encrypted backups

PFOS stores its working database in Docker's named volume. That volume survives normal shutdowns, but it is not an external backup. The backup workflow creates encrypted PostgreSQL dumps on an external drive.

## Manual backup

With the `Extreme SSD` mounted, run this from the repository:

```bash
./scripts/backup-to-ssd.sh
```

It writes an encrypted file to `/Volumes/Extreme SSD/PFOS Backups/`. If the SSD is not connected, it prints a skip message and makes no local copy. You can override the drive path for another disk:

```bash
PFOS_BACKUP_VOLUME='/Volumes/Another Drive' ./scripts/backup-to-ssd.sh
```

## Encryption key

The private `age` identity is stored only on this Mac at `~/.config/pfos-backup/age-key.txt`, with owner-only permissions. The SSD has encrypted backup files, not that key. Copy the private key separately to a secure location you control; without it, the SSD backups cannot be restored. Do not place it in this repository, on GitHub, or next to the SSD backup files.

## Weekly schedule

The installed macOS launch agent runs Sundays at 10:00 AM. It exits successfully if the SSD is not mounted, so it never writes an unencrypted fallback backup to the laptop. Logs are stored in `~/.local/state/pfos-backup/`.

To run it on demand through launchd:

```bash
launchctl kickstart -k gui/$(id -u)/com.pfos.weekly-backup
```

The direct script above is the preferred manual trigger.

## Restore testing

`scripts/restore-db.sh` intentionally replaces its target database. Test a restore only against a separate database or Compose project. Keep the `.env` file and its `CONNECTION_ENCRYPTION_KEY` with your backup recovery materials; the database dump alone cannot decrypt saved connection credentials.
