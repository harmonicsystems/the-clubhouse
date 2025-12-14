#!/bin/bash

# =============================================================================
# The Clubhouse - Database Backup Script
# =============================================================================
# Creates timestamped backups of your SQLite database.
#
# Usage:
#   ./backup.sh              # Create a backup
#   ./backup.sh restore      # List available backups to restore
#   ./backup.sh restore 3    # Restore backup #3 from list
# =============================================================================

set -e

# Configuration
DATABASE_PATH="${DATABASE_PATH:-clubhouse.db}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
MAX_BACKUPS=30  # Keep last 30 backups

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Function: Create backup
create_backup() {
    if [ ! -f "$DATABASE_PATH" ]; then
        echo -e "${RED}Error: Database file '$DATABASE_PATH' not found${NC}"
        exit 1
    fi

    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/clubhouse_$TIMESTAMP.db"

    # Use SQLite's backup command for consistency
    sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_FILE'"

    # Get some stats
    MEMBER_COUNT=$(sqlite3 "$DATABASE_PATH" "SELECT COUNT(*) FROM members;" 2>/dev/null || echo "?")
    POST_COUNT=$(sqlite3 "$DATABASE_PATH" "SELECT COUNT(*) FROM posts;" 2>/dev/null || echo "?")
    EVENT_COUNT=$(sqlite3 "$DATABASE_PATH" "SELECT COUNT(*) FROM events;" 2>/dev/null || echo "?")

    FILE_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')

    echo -e "${GREEN}Backup created successfully!${NC}"
    echo ""
    echo "  File: $BACKUP_FILE"
    echo "  Size: $FILE_SIZE"
    echo "  Data: $MEMBER_COUNT members, $POST_COUNT posts, $EVENT_COUNT events"
    echo ""

    # Cleanup old backups
    cleanup_old_backups
}

# Function: Cleanup old backups
cleanup_old_backups() {
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/clubhouse_*.db 2>/dev/null | wc -l)

    if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
        REMOVE_COUNT=$((BACKUP_COUNT - MAX_BACKUPS))
        echo -e "${YELLOW}Cleaning up $REMOVE_COUNT old backup(s)...${NC}"
        ls -1t "$BACKUP_DIR"/clubhouse_*.db | tail -n "$REMOVE_COUNT" | xargs rm -f
    fi
}

# Function: List backups
list_backups() {
    echo ""
    echo "Available backups:"
    echo "=================="

    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR"/clubhouse_*.db 2>/dev/null)" ]; then
        echo "No backups found in $BACKUP_DIR/"
        exit 0
    fi

    # List backups with numbers
    i=1
    for backup in $(ls -1t "$BACKUP_DIR"/clubhouse_*.db); do
        TIMESTAMP=$(basename "$backup" | sed 's/clubhouse_//' | sed 's/.db//')
        FORMATTED_DATE=$(echo "$TIMESTAMP" | sed 's/_/ /' | sed 's/\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)/\1-\2-\3/' | sed 's/ \([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)/ \1:\2:\3/')
        FILE_SIZE=$(ls -lh "$backup" | awk '{print $5}')
        echo "  [$i] $FORMATTED_DATE ($FILE_SIZE)"
        i=$((i + 1))
    done
    echo ""
}

# Function: Restore backup
restore_backup() {
    BACKUP_NUM=$1

    if [ -z "$BACKUP_NUM" ]; then
        list_backups
        echo "To restore, run: ./backup.sh restore <number>"
        echo ""
        exit 0
    fi

    # Get the backup file
    BACKUP_FILE=$(ls -1t "$BACKUP_DIR"/clubhouse_*.db | sed -n "${BACKUP_NUM}p")

    if [ -z "$BACKUP_FILE" ]; then
        echo -e "${RED}Error: Backup #$BACKUP_NUM not found${NC}"
        list_backups
        exit 1
    fi

    echo -e "${YELLOW}WARNING: This will overwrite your current database!${NC}"
    echo "Restoring from: $BACKUP_FILE"
    echo ""
    read -p "Are you sure? (yes/no): " CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        echo "Restore cancelled."
        exit 0
    fi

    # Create a backup of current database first
    if [ -f "$DATABASE_PATH" ]; then
        PRE_RESTORE_BACKUP="$BACKUP_DIR/pre_restore_$(date +%Y%m%d_%H%M%S).db"
        cp "$DATABASE_PATH" "$PRE_RESTORE_BACKUP"
        echo "Current database backed up to: $PRE_RESTORE_BACKUP"
    fi

    # Restore
    cp "$BACKUP_FILE" "$DATABASE_PATH"

    echo -e "${GREEN}Database restored successfully!${NC}"
    echo ""
    echo "If something went wrong, your previous database is at:"
    echo "  $PRE_RESTORE_BACKUP"
}

# Main
case "${1:-backup}" in
    backup)
        create_backup
        ;;
    restore)
        restore_backup "$2"
        ;;
    list)
        list_backups
        ;;
    *)
        echo "Usage: $0 [backup|restore|list]"
        echo ""
        echo "Commands:"
        echo "  backup   - Create a new backup (default)"
        echo "  restore  - Restore from a backup"
        echo "  list     - List available backups"
        exit 1
        ;;
esac
