#!/usr/bin/env python3
"""
Migrate existing unencrypted database to encrypted SQLCipher database.

Usage:
    python migrate_to_encrypted.py

This script will:
1. Read your existing unencrypted clubhouse.db
2. Create a new encrypted database with your DATABASE_KEY
3. Copy all data to the encrypted database
4. Rename files so the encrypted database becomes the primary

IMPORTANT: Make sure DATABASE_KEY is set in your .env file before running!
"""

import os
import sys
import sqlite3 as sqlite3_standard
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "clubhouse.db")
DATABASE_KEY = os.getenv("DATABASE_KEY", "")

def main():
    print("=" * 60)
    print("The Clubhouse - Database Encryption Migration")
    print("=" * 60)
    print()

    # Check for sqlcipher3
    try:
        from sqlcipher3 import dbapi2 as sqlite3_cipher
        print("[OK] SQLCipher library found")
    except ImportError:
        print("[ERROR] SQLCipher not installed!")
        print("Run: pip install sqlcipher3-binary")
        sys.exit(1)

    # Check for encryption key
    if not DATABASE_KEY:
        print("[ERROR] DATABASE_KEY not set!")
        print("Add DATABASE_KEY to your .env file:")
        print("  DATABASE_KEY=$(openssl rand -hex 32)")
        sys.exit(1)

    if len(DATABASE_KEY) < 32:
        print("[WARNING] DATABASE_KEY seems short. Recommend 64 hex characters.")
        response = input("Continue anyway? (yes/no): ")
        if response.lower() != "yes":
            sys.exit(0)

    print(f"[OK] DATABASE_KEY is set ({len(DATABASE_KEY)} characters)")

    # Check if source database exists
    if not os.path.exists(DATABASE_PATH):
        print(f"[ERROR] Database not found: {DATABASE_PATH}")
        sys.exit(1)

    print(f"[OK] Source database found: {DATABASE_PATH}")

    # Check if database is already encrypted
    try:
        conn = sqlite3_standard.connect(DATABASE_PATH)
        conn.execute("SELECT COUNT(*) FROM members")
        conn.close()
        print("[OK] Source database is unencrypted (readable)")
    except sqlite3_standard.DatabaseError:
        print("[INFO] Database may already be encrypted or corrupted.")
        response = input("Try to read with DATABASE_KEY? (yes/no): ")
        if response.lower() == "yes":
            try:
                conn = sqlite3_cipher.connect(DATABASE_PATH)
                conn.execute(f"PRAGMA key = '{DATABASE_KEY}'")
                conn.execute("SELECT COUNT(*) FROM members")
                conn.close()
                print("[OK] Database is already encrypted with this key!")
                print("No migration needed.")
                sys.exit(0)
            except:
                print("[ERROR] Cannot read database with current key.")
                sys.exit(1)
        else:
            sys.exit(1)

    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DATABASE_PATH}.backup_{timestamp}"

    print(f"\n[STEP 1] Creating backup: {backup_path}")
    import shutil
    shutil.copy2(DATABASE_PATH, backup_path)
    print(f"[OK] Backup created")

    # Create encrypted database
    encrypted_path = f"{DATABASE_PATH}.encrypted"

    print(f"\n[STEP 2] Creating encrypted database: {encrypted_path}")

    # Connect to source (unencrypted)
    source = sqlite3_standard.connect(DATABASE_PATH)
    source.row_factory = sqlite3_standard.Row

    # Connect to destination (encrypted)
    dest = sqlite3_cipher.connect(encrypted_path)
    dest.execute(f"PRAGMA key = '{DATABASE_KEY}'")

    # Get all table names
    tables = source.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()

    print(f"[OK] Found {len(tables)} tables to migrate")

    # Migrate each table
    for (table_name,) in tables:
        print(f"  - Migrating {table_name}...", end=" ")

        # Get table schema
        schema = source.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        ).fetchone()[0]

        # Create table in destination
        dest.execute(schema)

        # Copy data
        rows = source.execute(f"SELECT * FROM {table_name}").fetchall()
        if rows:
            # Get column count from first row
            placeholders = ",".join(["?" for _ in rows[0]])
            for row in rows:
                dest.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", tuple(row))

        print(f"{len(rows)} rows")

    dest.commit()

    # Verify migration
    print(f"\n[STEP 3] Verifying migration...")

    source_counts = {}
    for (table_name,) in tables:
        count = source.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        source_counts[table_name] = count

    dest_counts = {}
    for (table_name,) in tables:
        count = dest.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        dest_counts[table_name] = count

    all_match = True
    for table in source_counts:
        if source_counts[table] != dest_counts[table]:
            print(f"[ERROR] {table}: {source_counts[table]} -> {dest_counts[table]} (MISMATCH!)")
            all_match = False
        else:
            print(f"[OK] {table}: {source_counts[table]} rows verified")

    source.close()
    dest.close()

    if not all_match:
        print("\n[ERROR] Migration verification failed!")
        print(f"Encrypted database left at: {encrypted_path}")
        print(f"Original database unchanged: {DATABASE_PATH}")
        sys.exit(1)

    # Swap files
    print(f"\n[STEP 4] Swapping databases...")
    old_path = f"{DATABASE_PATH}.old_{timestamp}"
    os.rename(DATABASE_PATH, old_path)
    os.rename(encrypted_path, DATABASE_PATH)

    print(f"[OK] Original moved to: {old_path}")
    print(f"[OK] Encrypted database is now: {DATABASE_PATH}")

    # Final verification
    print(f"\n[STEP 5] Final verification...")
    try:
        conn = sqlite3_cipher.connect(DATABASE_PATH)
        conn.execute(f"PRAGMA key = '{DATABASE_KEY}'")
        member_count = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        conn.close()
        print(f"[OK] Encrypted database readable ({member_count} members)")
    except Exception as e:
        print(f"[ERROR] Cannot read encrypted database: {e}")
        sys.exit(1)

    # Summary
    print()
    print("=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print()
    print("Your database is now encrypted with SQLCipher.")
    print()
    print("Important files:")
    print(f"  Active database: {DATABASE_PATH} (encrypted)")
    print(f"  Original backup: {backup_path} (unencrypted)")
    print(f"  Pre-swap backup: {old_path} (unencrypted)")
    print()
    print("IMPORTANT: Keep your DATABASE_KEY safe!")
    print("If you lose it, you lose access to your data.")
    print()
    print("Once you've verified everything works, you can delete")
    print("the unencrypted backups:")
    print(f"  rm {backup_path}")
    print(f"  rm {old_path}")
    print()

if __name__ == "__main__":
    main()
