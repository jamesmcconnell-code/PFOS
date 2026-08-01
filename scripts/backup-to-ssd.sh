#!/usr/bin/env bash
# Create an encrypted PFOS database backup on the configured external SSD.
set -euo pipefail

# launchd starts with only system paths; Homebrew supplies age and Docker here.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ssd_volume="${PFOS_BACKUP_VOLUME:-/Volumes/Extreme SSD}"
identity_file="${PFOS_BACKUP_IDENTITY_FILE:-$HOME/.config/pfos-backup/age-key.txt}"

if [[ ! -d "$ssd_volume" ]]; then
  echo "PFOS backup skipped: SSD is not mounted at $ssd_volume" >&2
  exit 0
fi
if [[ ! -f "$identity_file" ]]; then
  echo "PFOS backup identity not found: $identity_file" >&2
  exit 1
fi

recipient="$(awk '/^# public key: / { print $4; exit }' "$identity_file")"
if [[ -z "$recipient" ]]; then
  echo "Could not read an age public key from $identity_file" >&2
  exit 1
fi

cd "$project_dir"
BACKUP_DIR="$ssd_volume/PFOS Backups" BACKUP_RECIPIENT="$recipient" ./scripts/backup-db.sh
