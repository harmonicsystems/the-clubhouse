#!/bin/bash

# =============================================================================
# The Clubhouse - Automated Backup Script (for cron)
# =============================================================================
# This script is designed to run via cron for automated daily backups.
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

# Configuration
DATABASE_PATH="${DATABASE_PATH:-clubhouse.db}"
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

# Create backup using SQLite's backup command
BACKUP_FILE="$BACKUP_DIR/clubhouse_$TIMESTAMP.db"
sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_FILE'"

# Get stats
MEMBER_COUNT=$(sqlite3 "$DATABASE_PATH" "SELECT COUNT(*) FROM members;" 2>/dev/null || echo "?")
FILE_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')

echo "[$DATE_READABLE] Backup created: $BACKUP_FILE ($FILE_SIZE, $MEMBER_COUNT members)"

# Cleanup old backups
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/clubhouse_*.db 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - MAX_BACKUPS))
    echo "[$DATE_READABLE] Removing $REMOVE_COUNT old backup(s)..."
    ls -1t "$BACKUP_DIR"/clubhouse_*.db | tail -n "$REMOVE_COUNT" | xargs rm -f
fi

echo "[$DATE_READABLE] Backup complete."
