#!/usr/bin/env bash
#
# Backup the Postgres database to timestamped custom-format dumps, then prune
# anything older than the retention window.
#
#   ./scripts/backup_db.sh                 # dump $PGDATABASE, keep 14 days
#   RETENTION_DAYS=30 ./scripts/backup_db.sh
#   ./scripts/backup_db.sh --restore latest  # list + restore a dump (manual)
#
# Connection settings come from the usual environment variables (PGHOST,
# PGPORT, PGUSER, PGPASSWORD, PGDATABASE) and fall back to the dev stack in
# backend/docker-compose.dev.yml. Point it at production by exporting the same
# variables in the cron/systemd unit that runs it.
#
# Exit codes: 0 ok, 1 usage/restore error, 2 dump failed, 3 no dump to restore.
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5433}"
PGUSER="${PGUSER:-postgres}"
PGDATABASE="${PGDATABASE:-mydatabase}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/polymarket}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

log() { printf '[backup] %s\n' "$*" >&2; }

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
}

restore() {
  local which="${1:-latest}"
  local dump
  if [ "$which" = "latest" ]; then
    dump="$(ls -1t "$BACKUP_DIR"/*.dump 2>/dev/null | head -1 || true)"
  else
    dump="$BACKUP_DIR/$which"
  fi
  if [ -z "$dump" ] || [ ! -f "$dump" ]; then
    log "no dump found for '$which' in $BACKUP_DIR"
    exit 3
  fi
  log "restoring $dump into $PGUSER@$PGHOST:$PGPORT/$PGDATABASE"
  log "target database must exist and be empty (dropdb/createdb first)"
  # --clean --if-exists lets a non-empty target work, but destructive: the
  # restore is deliberately a separate, manual command.
  pg_restore --no-owner --clean --if-exists \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$dump"
  log "restore complete"
}

case "${1:-}" in
  --restore)
    restore "${2:-latest}"
    exit 0
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/${PGDATABASE}-${stamp}.dump"

# -Fc (custom format): compressed, and pg_restore can take a single table out
# of it — plain SQL dumps cannot.
if ! pg_dump -Fc -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -f "$out"; then
  log "pg_dump FAILED"
  rm -f "$out"
  exit 2
fi

# A dump that cannot be listed is a dump that cannot be restored.
if ! pg_restore --list "$out" > /dev/null; then
  log "dump written but unreadable: $out"
  exit 2
fi

size="$(du -h "$out" | cut -f1)"
log "wrote $out ($size)"

# Retention: only prune once a *new* dump exists, so a permanently failing
# backup never deletes the last good copy.
pruned=0
while IFS= read -r old; do
  [ -n "$old" ] || continue
  rm -f "$old"
  pruned=$((pruned + 1))
done < <(find "$BACKUP_DIR" -name "${PGDATABASE}-*.dump" -mtime "+$RETENTION_DAYS")
log "pruned $pruned dump(s) older than ${RETENTION_DAYS}d"
log "verified $(ls -1 "$BACKUP_DIR"/*.dump | wc -l | tr -d ' ') dump(s) retained in $BACKUP_DIR"
