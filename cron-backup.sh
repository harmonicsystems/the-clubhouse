#!/bin/bash

# =============================================================================
# The Clubhouse - Automated Backup Script (for cron)
# =============================================================================
# This script is designed to run via cron for automated daily backups.
# Works with both encrypted (SQLCipher) and unencrypted databases.
#
# Setup (run once):
#   chmod +x cron-backup.sh
#   crontab -e
#   # Add this line (runs at 3am daily):
#   0 3 * * * /path/to/clubhouse/cron-backup.sh >> /var/log/clubhouse-backup.log 2>&1
#
# =============================================================================

set -e

# Change to script directory
cd "$(dirname "$0")"

# Load environment variables if .env exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Configuration
DATABASE_PATH="${DATABASE_PATH:-clubhouse.db}"
DATABASE_KEY="${DATABASE_KEY:-}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
MAX_BACKUPS=30
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE_READABLE=$(date +"%Y-%m-%d %H:%M:%S")

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "[$DATE_READABLE] Starting backup..."

# Check if database exists
if [ ! -f "$DATABASE_PATH" ]; then
    echo "[$DATE_READABLE] ERROR: Database file '$DATABASE_PATH' not found"
    exit 1
fi

BACKUP_FILE="$BACKUP_DIR/clubhouse_$TIMESTAMP.db"

# For encrypted databases, use file copy (preserves encryption)
# For unencrypted databases, file copy is equally safe
cp "$DATABASE_PATH" "$BACKUP_FILE"

# Get file size
FILE_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')

# Get stats (only works for unencrypted databases)
if [ -z "$DATABASE_KEY" ]; then
    MEMBER_COUNT=$(sqlite3 "$DATABASE_PATH" "SELECT COUNT(*) FROM members;" 2>/dev/null || echo "?")
    echo "[$DATE_READABLE] Backup created: $BACKUP_FILE ($FILE_SIZE, $MEMBER_COUNT members)"
else
    echo "[$DATE_READABLE] Backup created: $BACKUP_FILE ($FILE_SIZE, encrypted)"
fi

# Cleanup old backups
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/clubhouse_*.db 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - MAX_BACKUPS))
    echo "[$DATE_READABLE] Removing $REMOVE_COUNT old backup(s)..."
    ls -1t "$BACKUP_DIR"/clubhouse_*.db | tail -n "$REMOVE_COUNT" | xargs rm -f
fi

echo "[$DATE_READABLE] Backup complete."
