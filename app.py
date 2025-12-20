"""
The Clubhouse - A simple, local-first community platform
Phone numbers only. No passwords. SQLite database. Pure simplicity.
"""

# Use sqlcipher3 for encrypted database (falls back to sqlite3 if not available)
try:
    from sqlcipher3 import dbapi2 as sqlite3
    ENCRYPTION_AVAILABLE = True
except ImportError:
    import sqlite3
    ENCRYPTION_AVAILABLE = False

import random
import os
import html
import re
import calendar
from datetime import datetime, timedelta
from typing import Optional
from contextlib import contextmanager
import requests
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import hashlib

# Load environment variables
load_dotenv()

# Create our app
app = FastAPI(title="The Clubhouse", docs_url=None, redoc_url=None)

# Mount static files for uploads
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuration
ADMIN_PHONES = os.getenv("ADMIN_PHONES", "").split(",")
TEXTBELT_KEY = os.getenv("TEXTBELT_KEY", "textbelt")
SECRET_SALT = os.getenv("SECRET_SALT", "change-me-please")
DATABASE_PATH = os.getenv("DATABASE_PATH", "clubhouse.db")
SITE_NAME = os.getenv("SITE_NAME", "The Clubhouse")
SITE_URL = os.getenv("SITE_URL", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
MAX_MEMBERS = 200

# Database encryption key
DATABASE_KEY = os.getenv("DATABASE_KEY", "")

# Production mode: enables secure cookies, hides SMS codes on screen
PRODUCTION_MODE = os.getenv("PRODUCTION_MODE", "false").lower() == "true"

# Dev mode: allows auto-login without SMS verification
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true" or not PRODUCTION_MODE

# Warn if running in production without changing defaults
if PRODUCTION_MODE and SECRET_SALT == "change-me-please":
    print("⚠️  WARNING: Running in production mode with default SECRET_SALT!")
    print("   Generate a secure salt with: openssl rand -hex 32")

# Warn about encryption status
if ENCRYPTION_AVAILABLE and DATABASE_KEY:
    print("🔐 Database encryption enabled")
elif ENCRYPTION_AVAILABLE and not DATABASE_KEY:
    print("⚠️  WARNING: sqlcipher3 available but DATABASE_KEY not set - database is NOT encrypted")
    print("   Generate a key with: openssl rand -hex 32")
else:
    print("ℹ️  Database encryption not available (sqlcipher3 not installed)")

# In-memory storage
phone_codes = {}  # {phone: {"code": 123456, "created": datetime}}
rate_limits = {}  # {phone: {"attempts": 0, "reset_time": datetime}}
csrf_tokens = {}  # {phone: token}


# ============ DATABASE ============

@contextmanager
def get_db():
    """Open database, do stuff, close database"""
    conn = sqlite3.connect(DATABASE_PATH)

    # Set encryption key if available
    if ENCRYPTION_AVAILABLE and DATABASE_KEY:
        conn.execute(f"PRAGMA key = '{DATABASE_KEY}'")

    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Create our simple tables"""
    with get_db() as db:
        # Members table
        db.execute("""
            CREATE TABLE IF NOT EXISTS members (
                phone TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                joined_date TEXT DEFAULT CURRENT_TIMESTAMP,
                is_admin BOOLEAN DEFAULT 0,
                is_moderator BOOLEAN DEFAULT 0,
                is_active BOOLEAN DEFAULT 1
            )
        """)

        # Add is_moderator column if it doesn't exist (for existing databases)
        try:
            db.execute("ALTER TABLE members ADD COLUMN is_moderator BOOLEAN DEFAULT 0")
        except:
            pass  # Column already exists

        # Add status column if it doesn't exist (for existing databases)
        try:
            db.execute("ALTER TABLE members ADD COLUMN status TEXT DEFAULT 'available'")
        except:
            pass  # Column already exists

        # Add handle column if it doesn't exist (unique username, admin can change)
        try:
            db.execute("ALTER TABLE members ADD COLUMN handle TEXT")
        except:
            pass  # Column already exists

        # Add display_name column if it doesn't exist (user can change)
        try:
            db.execute("ALTER TABLE members ADD COLUMN display_name TEXT")
        except:
            pass  # Column already exists

        # Add avatar icon column (stores Lucide icon name)
        try:
            db.execute("ALTER TABLE members ADD COLUMN avatar TEXT DEFAULT 'user'")
        except:
            pass  # Column already exists

        # Add birthday column
        try:
            db.execute("ALTER TABLE members ADD COLUMN birthday TEXT")
        except:
            pass  # Column already exists

        # Add bio column (future-proofing for member profiles)
        try:
            db.execute("ALTER TABLE members ADD COLUMN bio TEXT")
        except:
            pass  # Column already exists

        # Add first_login column for welcome tour
        try:
            db.execute("ALTER TABLE members ADD COLUMN first_login BOOLEAN DEFAULT 1")
        except:
            pass  # Column already exists

        # Events table
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                event_date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                max_spots INTEGER,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                is_cancelled BOOLEAN DEFAULT 0
            )
        """)

        # Add time columns if they don't exist (for existing databases)
        try:
            db.execute("ALTER TABLE events ADD COLUMN start_time TEXT")
        except:
            pass
        try:
            db.execute("ALTER TABLE events ADD COLUMN end_time TEXT")
        except:
            pass

        # Add location column (future-proofing for event venues)
        try:
            db.execute("ALTER TABLE events ADD COLUMN location TEXT")
        except:
            pass

        # Add created_by_phone column (audit trail for who created events)
        try:
            db.execute("ALTER TABLE events ADD COLUMN created_by_phone TEXT")
        except:
            pass

        # RSVPs table
        db.execute("""
            CREATE TABLE IF NOT EXISTS rsvps (
                event_id INTEGER,
                phone TEXT,
                rsvp_date TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, phone)
            )
        """)

        # Add attended column if it doesn't exist
        try:
            db.execute("ALTER TABLE rsvps ADD COLUMN attended BOOLEAN DEFAULT 0")
        except:
            pass

        # Invite codes table
        db.execute("""
            CREATE TABLE IF NOT EXISTS invite_codes (
                code TEXT PRIMARY KEY,
                created_by_phone TEXT,
                used_by_phone TEXT,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                used_date TEXT
            )
        """)

        # Posts table
        db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                content TEXT NOT NULL,
                posted_date TEXT DEFAULT CURRENT_TIMESTAMP,
                is_pinned BOOLEAN DEFAULT 0
            )
        """)

        # Add is_pinned column if it doesn't exist (for existing databases)
        try:
            db.execute("ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT 0")
        except:
            pass  # Column already exists

        # Reactions table
        db.execute("""
            CREATE TABLE IF NOT EXISTS reactions (
                post_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                emoji TEXT NOT NULL,
                reacted_date TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (post_id, phone, emoji)
            )
        """)

        # Comments table
        db.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                content TEXT NOT NULL,
                posted_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Notifications table
        db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_phone TEXT NOT NULL,
                actor_phone TEXT NOT NULL,
                type TEXT NOT NULL,
                related_id INTEGER,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Bookmarks table
        db.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                phone TEXT NOT NULL,
                post_id INTEGER NOT NULL,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (phone, post_id)
            )
        """)

        # Event photos table
        db.execute("""
            CREATE TABLE IF NOT EXISTS event_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                photo_url TEXT NOT NULL,
                caption TEXT,
                uploaded_by_phone TEXT NOT NULL,
                uploaded_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Polls table
        db.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                created_by_phone TEXT NOT NULL,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """)

        # Poll options table
        db.execute("""
            CREATE TABLE IF NOT EXISTS poll_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                option_text TEXT NOT NULL,
                vote_count INTEGER DEFAULT 0
            )
        """)

        # Poll votes table (track who voted)
        db.execute("""
            CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                option_id INTEGER NOT NULL,
                voted_date TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (poll_id, phone)
            )
        """)

        db.commit()

    print(f"📚 Database ready at {DATABASE_PATH}")


def seed_demo_data():
    """Seed demo data for testing/demos - only runs if database is empty"""
    with get_db() as db:
        # Check if there are any members
        member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        if member_count > 0:
            return  # Already has data, don't seed

        print("Seeding demo data...")

        # Demo members (using Lucide icon names for avatars)
        demo_members = [
            ("5551234567", "Martin", "martin", "squirrel", 1, 0),  # Admin
            ("5552345678", "Jordan Sample", "jordan", "sprout", 0, 1),  # Moderator
            ("5553456789", "Riley Test", "riley", "star", 0, 0),
            ("5554567890", "Casey Example", "casey", "shell", 0, 0),
            ("5555678901", "Morgan Preview", "morgan", "sailboat", 0, 0),
        ]

        for phone, name, handle, avatar, is_admin, is_mod in demo_members:
            db.execute("""
                INSERT INTO members (phone, name, handle, display_name, avatar, is_admin, is_moderator, first_login, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'available')
            """, (phone, name, handle, name, avatar, is_admin, is_mod))

        # Demo events (next few weeks)
        from datetime import timedelta
        today = datetime.now()

        demo_events = [
            ("Community Coffee Hour", "Casual hangout - bring your own mug!", today + timedelta(days=2), "09:00", "10:30", 15),
            ("Workshop: Getting Started", "Learn how to use all the features", today + timedelta(days=5), "14:00", "15:30", 20),
            ("Game Night", "Board games and snacks!", today + timedelta(days=8), "18:00", "21:00", 12),
            ("Monthly Potluck", "Bring a dish to share with the community", today + timedelta(days=14), "12:00", "14:00", None),
            ("Open Mic Night", "Share your talents - music, poetry, comedy welcome!", today + timedelta(days=21), "19:00", "22:00", 30),
        ]

        for title, desc, date, start, end, spots in demo_events:
            db.execute("""
                INSERT INTO events (title, description, event_date, start_time, end_time, max_spots)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, desc, date.strftime("%Y-%m-%d"), start, end, spots))

        # Add some RSVPs
        db.execute("INSERT INTO rsvps (event_id, phone) VALUES (1, '5551234567')")
        db.execute("INSERT INTO rsvps (event_id, phone) VALUES (1, '5552345678')")
        db.execute("INSERT INTO rsvps (event_id, phone) VALUES (2, '5553456789')")

        # Demo posts
        demo_posts = [
            ("5551234567", "Welcome to the community! Feel free to introduce yourself and say hi to everyone."),
            ("5552345678", "Just tried the new coffee shop down the street - highly recommend the oat milk latte!"),
            ("5553456789", "Anyone interested in starting a book club? I've been wanting to read more this year."),
            ("5554567890", "Thanks for the warm welcome everyone! Excited to be here."),
            ("5555678901", "PSA: The parking lot will be repaved next Tuesday. Plan accordingly!"),
        ]

        for phone, content in demo_posts:
            db.execute("""
                INSERT INTO posts (phone, content)
                VALUES (?, ?)
            """, (phone, content))

        # Add some reactions (using Lucide icon names)
        db.execute("INSERT INTO reactions (post_id, phone, emoji) VALUES (1, '5552345678', 'heart')")
        db.execute("INSERT INTO reactions (post_id, phone, emoji) VALUES (1, '5553456789', 'party-popper')")
        db.execute("INSERT INTO reactions (post_id, phone, emoji) VALUES (2, '5551234567', 'thumbs-up')")
        db.execute("INSERT INTO reactions (post_id, phone, emoji) VALUES (3, '5554567890', 'thumbs-up')")
        db.execute("INSERT INTO reactions (post_id, phone, emoji) VALUES (3, '5555678901', 'heart')")

        # Demo poll
        db.execute("""
            INSERT INTO polls (question, created_by_phone)
            VALUES ('What day works best for our next community meeting?', '5551234567')
        """)
        poll_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        poll_options = ["Monday evening", "Wednesday afternoon", "Saturday morning", "Sunday afternoon"]
        for option in poll_options:
            db.execute("INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)", (poll_id, option))

        # Demo invite codes
        demo_codes = ["DEMO-001", "DEMO-002", "DEMO-003"]
        for code in demo_codes:
            db.execute("""
                INSERT INTO invite_codes (code, created_by_phone)
                VALUES (?, '5551234567')
            """, (code,))

        db.commit()
        print(f"Done: Demo data seeded: {len(demo_members)} members, {len(demo_events)} events, {len(demo_posts)} posts")


# Run this when app starts
init_database()

# Seed demo data if in dev mode
if DEV_MODE:
    seed_demo_data()


# ============ PLAYGROUND (IN-MEMORY SANDBOX) ============

class PlaygroundStore:
    """In-memory data store for playground sessions - no database needed"""

    def __init__(self):
        self.sessions = {}  # session_id -> data dict

    def get_session(self, session_id: str) -> dict:
        """Get or create a session's data"""
        if session_id not in self.sessions:
            self.sessions[session_id] = self._create_fresh_data()
        return self.sessions[session_id]

    def reset_session(self, session_id: str):
        """Reset a session to fresh data"""
        self.sessions[session_id] = self._create_fresh_data()

    def _create_fresh_data(self) -> dict:
        """Create a fresh set of demo data for a new session"""
        from datetime import timedelta
        now = datetime.now()

        # Demo members
        members = {
            "5550000001": {"phone": "5550000001", "name": "You", "handle": "you", "display_name": "You (Playground)", "avatar": "star", "is_admin": 1, "is_moderator": 0, "status": "available", "birthday": None, "joined_date": now.strftime("%Y-%m-%d %H:%M:%S"), "first_login": 0},
            "5550000002": {"phone": "5550000002", "name": "Jordan", "handle": "jordan", "display_name": "Jordan", "avatar": "sprout", "is_admin": 0, "is_moderator": 1, "status": "available", "birthday": None, "joined_date": (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"), "first_login": 0},
            "5550000003": {"phone": "5550000003", "name": "Riley", "handle": "riley", "display_name": "Riley Chen", "avatar": "shell", "is_admin": 0, "is_moderator": 0, "status": "away", "birthday": None, "joined_date": (now - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"), "first_login": 0},
            "5550000004": {"phone": "5550000004", "name": "Morgan", "handle": "morgan", "display_name": "Morgan", "avatar": "sailboat", "is_admin": 0, "is_moderator": 0, "status": "busy", "birthday": None, "joined_date": (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"), "first_login": 0},
            "5550000005": {"phone": "5550000005", "name": "Casey", "handle": "casey", "display_name": "Casey Park", "avatar": "squirrel", "is_admin": 0, "is_moderator": 0, "status": "available", "birthday": None, "joined_date": (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"), "first_login": 0},
        }

        # Demo events
        events = {
            1: {"id": 1, "title": "Community Coffee", "description": "Casual morning hangout. Bring your favorite mug!", "event_date": (now + timedelta(days=3)).strftime("%Y-%m-%d"), "start_time": "09:00", "end_time": "10:30", "max_spots": 12, "is_cancelled": 0},
            2: {"id": 2, "title": "Game Night", "description": "Board games, card games, and good company.", "event_date": (now + timedelta(days=7)).strftime("%Y-%m-%d"), "start_time": "18:00", "end_time": "21:00", "max_spots": 8, "is_cancelled": 0},
            3: {"id": 3, "title": "Book Club", "description": "Discussing this month's pick. All welcome!", "event_date": (now + timedelta(days=14)).strftime("%Y-%m-%d"), "start_time": "19:00", "end_time": "20:30", "max_spots": None, "is_cancelled": 0},
        }

        # Demo RSVPs
        rsvps = [
            {"event_id": 1, "phone": "5550000002"},
            {"event_id": 1, "phone": "5550000003"},
            {"event_id": 2, "phone": "5550000002"},
            {"event_id": 2, "phone": "5550000004"},
            {"event_id": 2, "phone": "5550000005"},
        ]

        # Demo posts
        posts = {
            1: {"id": 1, "phone": "5550000002", "content": "Welcome to the playground! Feel free to try everything - post, react, comment. Nothing here affects the real app.", "posted_date": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "is_pinned": 1},
            2: {"id": 2, "phone": "5550000003", "content": "Just discovered the best coffee shop downtown. The oat milk latte is incredible!", "posted_date": (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"), "is_pinned": 0},
            3: {"id": 3, "phone": "5550000004", "content": "Anyone interested in starting a running group? Thinking Saturday mornings.", "posted_date": (now - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S"), "is_pinned": 0},
            4: {"id": 4, "phone": "5550000005", "content": "Thanks for the warm welcome everyone! Excited to be part of this community.", "posted_date": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), "is_pinned": 0},
        }

        # Demo reactions
        reactions = [
            {"post_id": 1, "phone": "5550000003", "emoji": "heart"},
            {"post_id": 1, "phone": "5550000004", "emoji": "thumbs-up"},
            {"post_id": 2, "phone": "5550000002", "emoji": "flame"},
            {"post_id": 2, "phone": "5550000005", "emoji": "thumbs-up"},
            {"post_id": 3, "phone": "5550000002", "emoji": "thumbs-up"},
            {"post_id": 4, "phone": "5550000002", "emoji": "heart"},
            {"post_id": 4, "phone": "5550000003", "emoji": "party-popper"},
        ]

        # Demo comments
        comments = {
            1: {"id": 1, "post_id": 1, "phone": "5550000003", "content": "This is so cool!", "posted_date": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")},
            2: {"id": 2, "post_id": 2, "phone": "5550000004", "content": "Which shop? I need good coffee recommendations!", "posted_date": (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")},
            3: {"id": 3, "post_id": 3, "phone": "5550000005", "content": "Count me in! What pace are you thinking?", "posted_date": (now - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")},
        }

        # Demo poll
        polls = {
            1: {"id": 1, "question": "What should we do for the next community event?", "created_by_phone": "5550000002", "is_active": 1, "created_date": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")},
        }

        poll_options = {
            1: {"id": 1, "poll_id": 1, "option_text": "Outdoor movie night", "vote_count": 3},
            2: {"id": 2, "poll_id": 1, "option_text": "Potluck dinner", "vote_count": 2},
            3: {"id": 3, "poll_id": 1, "option_text": "Trivia night", "vote_count": 1},
            4: {"id": 4, "poll_id": 1, "option_text": "Volunteer day", "vote_count": 0},
        }

        poll_votes = [
            {"poll_id": 1, "phone": "5550000003", "option_id": 1},
            {"poll_id": 1, "phone": "5550000004", "option_id": 1},
            {"poll_id": 1, "phone": "5550000005", "option_id": 2},
        ]

        # Counters for new IDs
        counters = {
            "post_id": 5,
            "comment_id": 4,
            "event_id": 4,
            "poll_id": 2,
            "poll_option_id": 5,
        }

        return {
            "members": members,
            "events": events,
            "rsvps": rsvps,
            "posts": posts,
            "reactions": reactions,
            "comments": comments,
            "polls": polls,
            "poll_options": poll_options,
            "poll_votes": poll_votes,
            "bookmarks": [],
            "notifications": [],
            "counters": counters,
            "current_user": "5550000001",  # The playground user
        }

# Global playground store
playground = PlaygroundStore()

def get_playground_session_id(request) -> str:
    """Get or create playground session ID from cookie"""
    return request.cookies.get("playground_session", "")

def generate_playground_session() -> str:
    """Generate a new playground session ID"""
    import secrets
    return secrets.token_hex(16)


# ============ HELPER FUNCTIONS ============

def clean_phone(phone: str) -> str:
    """Remove all non-numbers and normalize to 10 digits (US)"""
    digits = ''.join(c for c in phone if c.isdigit())
    # If 11 digits starting with 1, strip the country code
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    return digits


def format_phone(phone: str) -> str:
    """Make phone pretty for display"""
    if len(phone) == 10:
        return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
    return phone


def get_greeting() -> str:
    """Return time-appropriate greeting"""
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    elif hour < 21:
        return "Good evening"
    else:
        return "Good night"


def format_member_since(joined_date: str) -> str:
    """Format join date as 'Member since Dec 2024'"""
    try:
        dt = datetime.strptime(joined_date[:10], "%Y-%m-%d")
        return f"Member since {dt.strftime('%b %Y')}"
    except:
        return ""


def send_sms(phone: str, message: str) -> bool:
    """Send a text message"""
    try:
        # Add US country code if not present (Textbelt requires it)
        sms_phone = phone
        if len(phone) == 10:
            sms_phone = "1" + phone

        response = requests.post('https://textbelt.com/text', {
            'phone': sms_phone,
            'message': message,
            'key': TEXTBELT_KEY
        }, timeout=10)
        return response.json().get('success', False)
    except:
        print(f"Failed to send SMS to {phone}")
        return False


def is_admin(phone: str) -> bool:
    """Check if this phone number is an admin"""
    return phone in ADMIN_PHONES or phone in [clean_phone(p) for p in ADMIN_PHONES]


def is_moderator_or_admin(member) -> bool:
    """Check if member is a moderator or admin"""
    return member["is_admin"] or member["is_moderator"]


def generate_code() -> str:
    """Generate a 6-digit code"""
    return str(random.randint(100000, 999999))


def generate_invite() -> str:
    """Generate a friendly invite code like MOON-742"""
    words = ['MOON', 'STAR', 'TREE', 'BIRD', 'FISH', 'BEAR', 'WOLF', 'FROG', 'LAKE', 'RAIN']
    return f"{random.choice(words)}-{random.randint(100, 999)}"


def icon(name: str, size: str = "", extra_class: str = "") -> str:
    """Generate a Lucide icon element.

    Usage: icon('home'), icon('bell', 'lg'), icon('user', '', 'my-class')
    Sizes: sm, lg, xl (default is 16px)
    """
    size_class = f"icon-{size}" if size else ""
    classes = f"icon {size_class} {extra_class}".strip()
    return f'<i data-lucide="{name}" class="{classes}"></i>'


# Available avatar icons (Lucide icon names)
AVATAR_ICONS = [
    "user", "sprout", "star", "shell", "sailboat", "squirrel",
    "skull", "smile", "square-terminal", "scale", "sword", "sun"
]
DEFAULT_AVATAR = "user"

# Reaction icons (Lucide icon names)
REACTION_ICONS = ["thumbs-up", "heart", "laugh", "party-popper", "flame"]


def avatar_icon(icon_name: str = None, size: str = "") -> str:
    """Generate an avatar using a Lucide icon.

    Usage: avatar_icon('sprout'), avatar_icon('star', 'sm')
    """
    icon_name = icon_name if icon_name in AVATAR_ICONS else DEFAULT_AVATAR
    size_class = f"avatar-{size}" if size else ""
    classes = f"avatar {size_class}".strip()
    return f'<span class="{classes}"><i data-lucide="{icon_name}" class="icon"></i></span>'


def avatar(name: str, size: str = "") -> str:
    """Generate an avatar with initials from a name (fallback).

    Usage: avatar('John Doe'), avatar('Jane', 'sm')
    """
    # Get initials (up to 2 characters)
    parts = name.split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[-1][0]).upper()
    else:
        initials = name[:2].upper() if len(name) >= 2 else name.upper()

    size_class = f"avatar-{size}" if size else ""
    classes = f"avatar {size_class}".strip()
    return f'<span class="{classes}">{html.escape(initials)}</span>'


def check_rate_limit(phone: str, max_attempts: int = 10, window_hours: int = 1) -> bool:
    """Rate limiting for SMS codes (increased for testing)"""
    now = datetime.now()
    if phone in rate_limits:
        if rate_limits[phone]["reset_time"] > now:
            if rate_limits[phone]["attempts"] >= max_attempts:
                return False
            rate_limits[phone]["attempts"] += 1
        else:
            rate_limits[phone] = {"attempts": 1, "reset_time": now + timedelta(hours=window_hours)}
    else:
        rate_limits[phone] = {"attempts": 1, "reset_time": now + timedelta(hours=window_hours)}
    return True


def clean_old_codes():
    """Remove verification codes older than 10 minutes"""
    now = datetime.now()
    expired = [phone for phone, data in phone_codes.items()
               if (now - data["created"]).seconds > 600]
    for phone in expired:
        del phone_codes[phone]


def make_cookie(phone: str) -> str:
    """Create a simple signed cookie value"""
    return hashlib.sha256(f"{phone}{SECRET_SALT}".encode()).hexdigest()[:20] + phone


def read_cookie(cookie: str) -> Optional[str]:
    """Read and verify our cookie"""
    if not cookie or len(cookie) < 21:
        return None
    phone = cookie[20:]
    expected = hashlib.sha256(f"{phone}{SECRET_SALT}".encode()).hexdigest()[:20]
    if cookie[:20] == expected:
        return phone
    return None


def set_auth_cookie(response, phone: str):
    """Set authentication cookie with appropriate security settings"""
    response.set_cookie(
        key="clubhouse",
        value=make_cookie(phone),
        max_age=2592000,  # 30 days
        httponly=True,
        secure=PRODUCTION_MODE,  # Only send over HTTPS in production
        samesite="lax"  # Prevents CSRF while allowing normal navigation
    )


def create_notification(recipient_phone: str, actor_phone: str, notif_type: str, message: str, related_id: int = None):
    """Create a notification for a user"""
    # Don't notify yourself
    if recipient_phone == actor_phone:
        return

    with get_db() as db:
        db.execute("""
            INSERT INTO notifications (recipient_phone, actor_phone, type, related_id, message)
            VALUES (?, ?, ?, ?, ?)
        """, (recipient_phone, actor_phone, notif_type, related_id, message))
        db.commit()


def get_unread_count(phone: str) -> int:
    """Get count of unread notifications for a user"""
    with get_db() as db:
        result = db.execute("""
            SELECT COUNT(*) as count
            FROM notifications
            WHERE recipient_phone = ? AND is_read = 0
        """, (phone,)).fetchone()
        return result["count"] if result else 0


def generate_handle(name: str) -> str:
    """Generate a unique handle from a name"""
    # Clean the name - lowercase, remove special chars, replace spaces with underscores
    base_handle = name.lower().strip()
    base_handle = ''.join(c if c.isalnum() or c == ' ' else '' for c in base_handle)
    base_handle = base_handle.replace(' ', '_')

    if not base_handle:
        base_handle = "user"

    # Try the base handle first
    handle = base_handle
    counter = 1

    with get_db() as db:
        while True:
            existing = db.execute("SELECT * FROM members WHERE handle = ?", (handle,)).fetchone()
            if not existing:
                return handle
            # If taken, add a number
            counter += 1
            handle = f"{base_handle}{counter}"


def get_csrf_token(phone: str) -> str:
    """Generate CSRF token for a user - stable per session"""
    if phone not in csrf_tokens:
        csrf_tokens[phone] = hashlib.sha256(f"{phone}{SECRET_SALT}".encode()).hexdigest()[:16]
    return csrf_tokens[phone]


def verify_csrf_token(phone: str, token: str) -> bool:
    """Verify CSRF token"""
    return phone in csrf_tokens and csrf_tokens[phone] == token


def sanitize_content(content: str) -> str:
    """Escape HTML, make links clickable, and embed rich media"""
    content = html.escape(content)

    # Extract all URLs first
    url_pattern = re.compile(r'(https?://[^\s]+)')
    urls = url_pattern.findall(content)

    embeds = []
    embedded_urls = []  # Track which URLs get embedded

    for url in urls:
        embed_html = None

        # YouTube embeds
        youtube_match = re.match(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)', url)
        if youtube_match:
            video_id = youtube_match.group(1)
            embed_html = f'''
            <div style="margin: 15px 0; border: 1px solid #000; background: #f9f9f9; padding: 10px;">
                <iframe width="100%" height="315" style="max-width: 560px;"
                    src="https://www.youtube.com/embed/{video_id}"
                    frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen>
                </iframe>
                <p class="small" style="margin: 5px 0 0 0;">🎥 YouTube</p>
            </div>
            '''
            embedded_urls.append(url)

        # Spotify embeds
        elif 'spotify.com' in url:
            # Extract Spotify URI (track, album, playlist, artist)
            spotify_match = re.match(r'https?://open\.spotify\.com/(track|album|playlist|artist)/([a-zA-Z0-9]+)', url)
            if spotify_match:
                content_type, content_id = spotify_match.groups()
                height = "352" if content_type == "playlist" else "152"
                embed_html = f'''
                <div style="margin: 15px 0; border: 1px solid #000; background: #f9f9f9; padding: 10px;">
                    <iframe style="border-radius: 12px; width: 100%; max-width: 560px;"
                        src="https://open.spotify.com/embed/{content_type}/{content_id}"
                        height="{height}" frameBorder="0"
                        allowfullscreen=""
                        allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
                        loading="lazy">
                    </iframe>
                    <p class="small" style="margin: 5px 0 0 0;">🎵 Spotify</p>
                </div>
                '''
                embedded_urls.append(url)

        # Image embeds (jpg, jpeg, png, gif, webp)
        elif re.match(r'.*\.(jpg|jpeg|png|gif|webp)(\?.*)?$', url.lower()):
            embed_html = f'''
            <div style="margin: 15px 0; border: 1px solid #000; background: #f9f9f9; padding: 10px;">
                <img src="{url}" style="max-width: 100%; height: auto; display: block;" alt="Image">
                <p class="small" style="margin: 5px 0 0 0;"><i data-lucide="image" class="icon icon-sm"></i> Image</p>
            </div>
            '''
            embedded_urls.append(url)

        # Giphy GIFs
        elif 'giphy.com' in url or 'tenor.com' in url:
            embed_html = f'''
            <div style="margin: 15px 0; border: 1px solid #000; background: #f9f9f9; padding: 10px;">
                <img src="{url}" style="max-width: 100%; height: auto; display: block;" alt="GIF">
                <p class="small" style="margin: 5px 0 0 0;">🎬 GIF</p>
            </div>
            '''
            embedded_urls.append(url)

        if embed_html:
            embeds.append(embed_html)

    # Make URLs clickable, but hide embedded ones
    def replace_url(match):
        url = match.group(1)
        if url in embedded_urls:
            # Hide the URL since it's embedded below
            return ''
        return f'<a href="{url}" target="_blank">{url}</a>'

    content = url_pattern.sub(replace_url, content)

    # Append embeds at the end
    if embeds:
        content += '\n' + '\n'.join(embeds)

    return content


def format_event_time(event_date: str, start_time: str = None, end_time: str = None) -> str:
    """Format event date and time nicely"""
    try:
        # Parse the date
        date_obj = datetime.fromisoformat(event_date) if 'T' in event_date else datetime.strptime(event_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%A, %B %d, %Y")  # "Friday, November 22, 2024"

        # Add time if provided
        if start_time or end_time:
            time_parts = []
            if start_time:
                start = datetime.strptime(start_time, "%H:%M").strftime("%I:%M %p").lstrip("0")
                time_parts.append(start)
            if end_time:
                end = datetime.strptime(end_time, "%H:%M").strftime("%I:%M %p").lstrip("0")
                if start_time:
                    time_parts.append(f"- {end}")
                else:
                    time_parts.append(f"until {end}")

            return f"{date_str} at {' '.join(time_parts)}"

        return date_str
    except:
        return event_date


def format_relative_time(date_str: str) -> str:
    """Convert timestamp to relative time like '5 minutes ago'"""
    try:
        posted = datetime.fromisoformat(date_str)
        now = datetime.now()
        diff = now - posted

        if diff.seconds < 60:
            return "just now"
        elif diff.seconds < 3600:
            mins = diff.seconds // 60
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        elif diff.seconds < 86400:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff.days == 1:
            return "yesterday"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return posted.strftime("%b %d, %Y")
    except:
        return date_str


# ============ HTML TEMPLATE ============

def render_html(content: str, title: str = "The Clubhouse") -> HTMLResponse:
    """Wrap content in our simple HTML template"""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&display=swap" rel="stylesheet">
        <style>
            /* ============ STYLE GUIDE ============ */
            /*
             * THE CLUBHOUSE DESIGN SYSTEM
             *
             * TYPOGRAPHY:
             * --font-body: Source Serif 4 (serif)
             *   → Human content: posts, comments, descriptions, body text
             *   → Warm, readable, inviting
             *
             * --font-mono: IBM Plex Mono (monospace)
             *   → System/data: timestamps, counts, codes, metadata
             *   → Technical, precise, structured
             *
             * HIERARCHY (via weight + density):
             * - Page titles: 600 weight, generous bottom margin
             * - Section heads: 500 weight, tight to content
             * - Body: 400 weight, relaxed line-height (1.6)
             * - Metadata: smaller size, muted color, tighter spacing
             *
             * SPACING RHYTHM:
             * - Cards: 15px padding, 15px margin between
             * - Sections: 30px top margin
             * - Tight metadata: 5px gaps
             * - Generous content: 10-15px gaps
             *
             * COLORS:
             * - Primary text: #1a1a1a (not pure black - softer)
             * - Muted text: #666 (timestamps, hints)
             * - Borders: #e0e0e0 light, #1a1a1a strong
             * - Accent: #1a1a1a (buttons, links)
             */
            :root {{
                --color-bg: #fff;
                --color-text: #1a1a1a;
                --color-text-muted: #666;
                --color-border: #1a1a1a;
                --color-border-light: #e0e0e0;
                --color-accent: #1a1a1a;
                --color-accent-hover: #333;
                --color-success: #2d6a4f;
                --color-highlight: #f8f8f8;
                --font-body: 'Source Serif 4', Georgia, serif;
                --font-mono: 'IBM Plex Mono', monospace;
                --font-size: 16px;
                --max-width: 600px;
                --spacing: 20px;
            }}

            /* Smooth scrolling for anchor navigation */
            html {{
                scroll-behavior: smooth;
            }}

            /* ============ BASE STYLES ============ */
            body {{
                max-width: var(--max-width);
                margin: 50px auto;
                padding: var(--spacing);
                font-family: var(--font-body);
                font-size: var(--font-size);
                line-height: 1.6;
                color: var(--color-text);
                background: var(--color-bg);
            }}
            h1 {{
                font-family: var(--font-body);
                font-size: 26px;
                font-weight: 600;
                margin-bottom: 30px;
                border-bottom: 2px solid var(--color-border);
                padding-bottom: 10px;
                letter-spacing: -0.02em;
            }}
            h2 {{
                font-family: var(--font-body);
                font-size: 18px;
                font-weight: 500;
                margin-top: 30px;
                margin-bottom: 10px;
            }}
            h3 {{
                font-family: var(--font-body);
                font-size: 16px;
                font-weight: 500;
                margin: 0 0 8px 0;
            }}
            /* Monospace for data/system elements */
            .mono, .small, time, .timestamp, .count, code {{
                font-family: var(--font-mono);
            }}
            input, textarea, select {{
                font-family: inherit;
                font-size: inherit;
                padding: 10px 12px;
                margin: 10px 0;
                width: 100%;
                box-sizing: border-box;
                border: 1px solid var(--color-border-light);
                border-radius: 6px;
                background: var(--color-bg);
                color: var(--color-text);
                transition: border-color 0.15s ease, box-shadow 0.15s ease;
            }}
            input:focus, textarea:focus, select:focus {{
                outline: none;
                border-color: var(--color-accent);
                box-shadow: 0 0 0 3px rgba(26, 26, 26, 0.08);
            }}
            button {{
                font-family: var(--font-mono);
                font-size: 14px;
                padding: 10px 20px;
                background: var(--color-accent);
                color: var(--color-bg);
                border: none;
                border-radius: 6px;
                cursor: pointer;
                margin-top: 10px;
                letter-spacing: 0.01em;
                transition: background 0.15s ease, transform 0.1s ease;
                min-height: 44px; /* Touch-friendly tap target */
            }}
            button:hover {{
                background: var(--color-accent-hover);
            }}
            button:active {{
                transform: scale(0.98);
            }}
            .event {{
                border: 1px solid var(--color-border-light);
                border-radius: 8px;
                padding: 15px;
                margin: 15px 0;
                transition: box-shadow 0.15s ease, transform 0.15s ease;
            }}
            .event:hover {{
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            }}
            .photo-gallery {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                gap: 10px;
                margin-top: 15px;
            }}
            .photo-item {{
                border: 1px solid var(--color-border-light);
                border-radius: 6px;
                padding: 5px;
                overflow: hidden;
            }}
            .photo-item img {{
                width: 100%;
                height: auto;
                display: block;
            }}
            .post {{
                border: 1px solid var(--color-border-light);
                border-radius: 8px;
                padding: 15px;
                margin: 15px 0;
                transition: box-shadow 0.15s ease;
            }}
            .post:hover {{
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            }}
            /* Anchor highlight animation - shows where you landed after RSVP/vote/etc */
            @keyframes highlight-flash {{
                0% {{ background-color: rgba(45, 106, 79, 0.15); }}
                100% {{ background-color: transparent; }}
            }}
            .event:target, .post:target {{
                animation: highlight-flash 1.5s ease-out;
            }}
            .post-header {{
                display: flex;
                justify-content: space-between;
                font-family: var(--font-mono);
                font-size: 13px;
                color: var(--color-text-muted);
                margin-bottom: 12px;
                letter-spacing: 0.01em;
            }}
            .post-content {{
                margin: 12px 0;
                line-height: 1.65;
            }}
            .reactions {{
                margin-top: 10px;
                padding-top: 10px;
                border-top: 1px solid var(--color-border-light);
            }}
            .reaction-btn {{
                display: inline-flex;
                align-items: center;
                gap: 4px;
                padding: 4px 10px;
                margin: 2px;
                border: 1px solid transparent;
                background: transparent;
                text-decoration: none;
                border-radius: 20px;
                cursor: pointer;
                transition: all 0.15s ease;
                color: var(--color-text-muted);
            }}
            .reaction-btn .icon {{
                opacity: 0.6;
                transition: all 0.15s ease;
            }}
            .reaction-btn:hover {{
                transform: scale(1.05);
            }}
            .reaction-btn:hover .icon {{
                opacity: 1;
            }}
            .reaction-btn:active {{
                transform: scale(0.95);
            }}
            /* Muted color fills for each reaction type */
            .reaction-btn[data-emoji="thumbs-up"] {{ color: #5b8fb9; }}
            .reaction-btn[data-emoji="thumbs-up"]:hover,
            .reaction-btn[data-emoji="thumbs-up"].active {{ background: rgba(91, 143, 185, 0.12); border-color: rgba(91, 143, 185, 0.3); }}
            .reaction-btn[data-emoji="heart"] {{ color: #c77d8e; }}
            .reaction-btn[data-emoji="heart"]:hover,
            .reaction-btn[data-emoji="heart"].active {{ background: rgba(199, 125, 142, 0.12); border-color: rgba(199, 125, 142, 0.3); }}
            .reaction-btn[data-emoji="laugh"] {{ color: #c9a857; }}
            .reaction-btn[data-emoji="laugh"]:hover,
            .reaction-btn[data-emoji="laugh"].active {{ background: rgba(201, 168, 87, 0.12); border-color: rgba(201, 168, 87, 0.3); }}
            .reaction-btn[data-emoji="party-popper"] {{ color: #9b7bb8; }}
            .reaction-btn[data-emoji="party-popper"]:hover,
            .reaction-btn[data-emoji="party-popper"].active {{ background: rgba(155, 123, 184, 0.12); border-color: rgba(155, 123, 184, 0.3); }}
            .reaction-btn[data-emoji="flame"] {{ color: #d4845a; }}
            .reaction-btn[data-emoji="flame"]:hover,
            .reaction-btn[data-emoji="flame"].active {{ background: rgba(212, 132, 90, 0.12); border-color: rgba(212, 132, 90, 0.3); }}
            .reaction-btn.active {{
                font-weight: 500;
            }}
            .reaction-btn.active .icon {{
                opacity: 1;
            }}
            .small {{
                font-family: var(--font-mono);
                font-size: 12px;
                color: var(--color-text-muted);
                letter-spacing: 0.01em;
            }}
            .hint {{
                font-family: var(--font-mono);
                background: transparent;
                border: 1px solid var(--color-border-light);
                border-radius: 6px;
                padding: 12px 15px;
                margin: 15px 0;
                font-size: 12px;
                color: var(--color-text-muted);
            }}
            .error {{
                color: #c00;
                margin: 10px 0;
            }}
            .success {{
                color: var(--color-success);
                margin: 10px 0;
            }}
            a {{
                color: var(--color-text);
            }}
            .nav {{
                font-family: var(--font-mono);
                font-size: 13px;
                margin-bottom: 30px;
                padding-bottom: 10px;
                border-bottom: 1px solid var(--color-border-light);
                line-height: 2;
            }}
            .nav a {{
                text-decoration: none;
                white-space: nowrap;
            }}
            .nav a:hover {{
                text-decoration: underline;
            }}
            @media (max-width: 600px) {{
                .nav {{
                    font-size: 12px;
                }}
                .mobile-hide {{
                    display: none;
                }}
            }}
            details {{
                margin-top: 10px;
            }}
            summary {{
                cursor: pointer;
                color: var(--color-text-muted);
                font-size: 14px;
            }}

            /* ============ ICONS ============ */
            .icon {{
                width: 16px;
                height: 16px;
                stroke-width: 2;
                vertical-align: middle;
                display: inline-block;
            }}
            .icon-sm {{
                width: 22px;
                height: 22px;
            }}
            .icon-lg {{
                width: 28px;
                height: 28px;
            }}
            .icon-xl {{
                width: 32px;
                height: 32px;
            }}
            .nav .icon {{
                margin-right: 4px;
            }}
            /* Status indicators */
            .status-available {{ color: #6b9080; }}  /* muted sage green */
            .status-away {{ color: #9a8c7d; }}       /* warm taupe */
            .status-busy {{ color: #a07178; }}       /* muted rose */
            /* Avatar circle with initials */
            .avatar {{
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background: var(--color-border);
                color: var(--color-bg);
                display: inline-flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: bold;
                margin-right: 8px;
                flex-shrink: 0;
            }}
            .avatar-sm {{
                width: 24px;
                height: 24px;
                font-size: 10px;
                margin-right: 6px;
            }}

            /* ============ MOBILE STYLES ============ */
            .nav {{
                display: flex;
                flex-wrap: wrap;
                gap: 8px 12px;
                align-items: center;
            }}
            .nav a {{
                white-space: nowrap;
            }}
            .mobile-hide {{
                display: inline;
            }}
            @media (max-width: 600px) {{
                body {{
                    margin: 20px auto;
                    padding: 15px;
                }}
                h1 {{
                    font-size: 20px;
                }}
                .nav {{
                    font-size: 14px;
                    gap: 8px 6px;
                }}
                .nav a {{
                    padding: 4px 0;
                }}
                .mobile-hide {{
                    display: none;
                }}
                button {{
                    width: 100%;
                    padding: 12px 20px;
                }}
                .reaction-btn {{
                    padding: 6px 10px;
                }}
            }}

            /* Button loading state */
            button:disabled {{
                background: #999;
                cursor: wait;
            }}
        </style>
        <script>
            document.addEventListener('DOMContentLoaded', function() {{
                // Update greeting based on user's local timezone
                var greetingEl = document.getElementById('greeting');
                if (greetingEl) {{
                    var hour = new Date().getHours();
                    var greeting = "Hello";
                    if (hour < 12) greeting = "Good morning";
                    else if (hour < 17) greeting = "Good afternoon";
                    else if (hour < 21) greeting = "Good evening";
                    else greeting = "Good night";
                    greetingEl.textContent = greeting;
                }}

                // Prevent double-submit on all forms
                document.querySelectorAll('form').forEach(function(form) {{
                    form.addEventListener('submit', function() {{
                        var btn = form.querySelector('button[type="submit"], button:not([type])');
                        if (btn && !btn.disabled) {{
                            btn.disabled = true;
                            btn.dataset.originalText = btn.textContent;
                            btn.textContent = 'Sending...';
                        }}
                    }});
                }});
            }});
        </script>
        <!-- Lucide Icons -->
        <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
    </head>
    <body>
        {f'''
        <div id="demo-toolbar" style="
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background: #333;
            color: #aaa;
            padding: 4px 12px;
            font-size: 11px;
            z-index: 9999;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 12px;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        ">
            <span>Demo</span>
            <button onclick="setViewMode(false)" id="btn-admin" style="
                padding: 2px 8px;
                border: 1px solid #666;
                background: #555;
                color: white;
                cursor: pointer;
                font-size: 11px;
            ">Admin</button>
            <button onclick="setViewMode(true)" id="btn-member" style="
                padding: 2px 8px;
                border: 1px solid #666;
                background: transparent;
                color: #aaa;
                cursor: pointer;
                font-size: 11px;
            ">Member</button>
        </div>
        <div style="height: 28px;"></div>
        <script>
            function getCookie(name) {{
                const value = "; " + document.cookie;
                const parts = value.split("; " + name + "=");
                if (parts.length === 2) return parts.pop().split(";").shift();
                return null;
            }}

            function setViewMode(asMember) {{
                const url = asMember ? "/admin/view_as_member" : "/admin/view_as_admin";
                fetch(url, {{ method: "POST", credentials: "same-origin" }})
                    .then(() => location.reload())
                    .catch(err => console.error("Toggle failed:", err));
            }}

            // Update toolbar based on current view mode
            (function() {{
                const isViewingAsMember = getCookie("view_as_member") === "1";
                const btnAdmin = document.getElementById("btn-admin");
                const btnMember = document.getElementById("btn-member");

                if (isViewingAsMember) {{
                    btnAdmin.style.background = "transparent";
                    btnAdmin.style.color = "#aaa";
                    btnMember.style.background = "#555";
                    btnMember.style.color = "white";
                }}
            }})();
        </script>
        ''' if DEV_MODE else ''}
        {content}
        <script>lucide.createIcons();</script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ============ ROUTES ============

@app.get("/debug-members")
async def debug_members():
    """Temporary debug route - shows stored phone numbers"""
    with get_db() as db:
        members = db.execute("SELECT phone, name, is_admin FROM members").fetchall()
        if not members:
            return {"members": [], "count": 0}
        return {
            "members": [{"phone": m["phone"], "name": m["name"], "is_admin": m["is_admin"]} for m in members],
            "count": len(members)
        }


@app.get("/bootstrap")
async def bootstrap():
    """First-time setup: Create admin account if database is empty"""
    with get_db() as db:
        member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        if member_count > 0:
            return render_html("""
                <h1>Already Set Up</h1>
                <p>The community already has members. Bootstrap is disabled.</p>
                <a href="/">← Go to home</a>
            """)

    content = f"""
    <h1>Welcome to {SITE_NAME}!</h1>
    <p>No members yet. Let's create the first admin account.</p>

    <form method="POST" action="/bootstrap">
        <input type="text" name="name" placeholder="Your first name" required>
        <input type="tel" name="phone" placeholder="(555) 555-5555" required>
        <button type="submit">Create Admin Account</button>
    </form>

    <p class="small">This page only works when the database is empty.</p>
    """
    return render_html(content)


@app.post("/bootstrap")
async def bootstrap_create(name: str = Form(...), phone: str = Form(...)):
    """Create the first admin account"""
    phone = clean_phone(phone)

    with get_db() as db:
        member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        if member_count > 0:
            raise HTTPException(status_code=400, detail="Bootstrap disabled - members exist")

        # Create admin account
        db.execute(
            "INSERT INTO members (phone, name, is_admin) VALUES (?, ?, 1)",
            (phone, name)
        )

        # Create a few invite codes for them
        for _ in range(3):
            code = generate_invite()
            db.execute(
                "INSERT INTO invite_codes (code, created_by_phone) VALUES (?, ?)",
                (code, phone)
            )

        db.commit()

    # Log them in and show welcome tour
    response = RedirectResponse(url="/welcome", status_code=303)
    set_auth_cookie(response, phone)
    return response


@app.get("/dev")
async def dev_login(redirect: str = "/dashboard"):
    """Auto-login for development - only works when DEV_MODE is enabled"""
    if not DEV_MODE:
        raise HTTPException(status_code=404, detail="Not found")

    with get_db() as db:
        # Try to find an existing admin, or any member
        member = db.execute(
            "SELECT phone, name FROM members WHERE is_admin = 1 LIMIT 1"
        ).fetchone()

        if not member:
            member = db.execute(
                "SELECT phone, name FROM members LIMIT 1"
            ).fetchone()

        if not member:
            # No members exist - redirect to bootstrap
            return RedirectResponse(url="/bootstrap", status_code=303)

    # Auto-login as this member
    response = RedirectResponse(url=redirect, status_code=303)
    set_auth_cookie(response, member["phone"])
    return response


@app.get("/dev/admin")
async def dev_admin_login():
    """Auto-login and go straight to admin panel"""
    if not DEV_MODE:
        raise HTTPException(status_code=404, detail="Not found")
    return await dev_login(redirect="/admin")


@app.get("/dev/reset")
async def dev_reset():
    """Reset database and reseed demo data - only in dev mode"""
    if not DEV_MODE:
        raise HTTPException(status_code=404, detail="Not found")

    with get_db() as db:
        # Clear all data
        tables = ["poll_votes", "poll_options", "polls", "bookmarks", "notifications",
                  "comments", "reactions", "event_photos", "posts", "rsvps", "events",
                  "invite_codes", "members"]
        for table in tables:
            try:
                db.execute(f"DELETE FROM {table}")
            except:
                pass  # Table might not exist
        db.commit()

    # Re-seed demo data
    seed_demo_data()

    content = """
    <h1>Database Reset</h1>
    <p class="success">Demo data has been reseeded!</p>
    <p><a href="/dev">→ Login as demo admin</a></p>
    <p><a href="/demo">→ View public demo</a></p>
    """
    return render_html(content)


@app.get("/demo")
async def public_demo():
    """Public read-only demo of the community feed - only in dev mode"""
    if not DEV_MODE:
        raise HTTPException(status_code=404, detail="Not found")

    with get_db() as db:
        # Get recent posts
        posts = db.execute("""
            SELECT p.*, m.name, m.display_name, m.avatar
            FROM posts p
            JOIN members m ON p.phone = m.phone
            ORDER BY p.is_pinned DESC, p.posted_date DESC
            LIMIT 20
        """).fetchall()

        posts_html = ""
        if posts:
            for post in posts:
                relative_time = format_relative_time(post["posted_date"])
                post_content = sanitize_content(post['content'])

                # Get reactions (read-only display)
                reactions = db.execute("""
                    SELECT emoji, COUNT(*) as count
                    FROM reactions
                    WHERE post_id = ?
                    GROUP BY emoji
                """, (post["id"],)).fetchall()

                reactions_html = '<div class="reactions">'
                for reaction in reactions:
                    reactions_html += f'<span class="reaction-btn">{reaction["emoji"]} <span class="count">{reaction["count"]}</span></span>'
                reactions_html += '</div>'

                # Get comment count
                comment_count = db.execute(
                    "SELECT COUNT(*) FROM comments WHERE post_id = ?",
                    (post["id"],)
                ).fetchone()[0]

                comments_html = ""
                if comment_count > 0:
                    comments_html = f'<p class="small" style="margin-top: 10px;">Comments: {comment_count} comment{"s" if comment_count != 1 else ""}</p>'

                pinned_badge = ""
                if post["is_pinned"]:
                    pinned_badge = '<span style="background: #28a745; color: white; padding: 2px 6px; font-size: 11px; border-radius: 3px; margin-right: 8px;">PINNED</span>'

                post_name = post["display_name"] or post["name"]
                post_avatar = avatar_icon(post["avatar"], "sm")

                posts_html += f"""
                <div class="post" style="{'border: 2px solid #28a745;' if post['is_pinned'] else ''}">
                    <div class="post-header">
                        <span>{post_avatar}{pinned_badge}{html.escape(post_name)}</span>
                        <span>{relative_time}</span>
                    </div>
                    <div class="post-content">{post_content}</div>
                    {reactions_html}
                    {comments_html}
                </div>
                """
        else:
            posts_html = """
            <div style="text-align: center; padding: 40px 20px; color: #666;">
                <p style="font-size: 18px;">No posts yet</p>
                <p>The community feed is waiting for its first post!</p>
            </div>
            """

        # Get active polls (read-only results)
        polls = db.execute("""
            SELECT p.*, m.name as creator_name
            FROM polls p
            JOIN members m ON p.created_by_phone = m.phone
            WHERE p.is_active = 1
            ORDER BY p.created_date DESC
            LIMIT 3
        """).fetchall()

        polls_html = ""
        for poll in polls:
            options = db.execute("""
                SELECT option_text, vote_count
                FROM poll_options
                WHERE poll_id = ?
                ORDER BY vote_count DESC
            """, (poll["id"],)).fetchall()

            total_votes = sum(opt["vote_count"] for opt in options)
            poll_time = format_relative_time(poll["created_date"])

            options_html = ""
            for opt in options:
                percentage = (opt["vote_count"] / total_votes * 100) if total_votes > 0 else 0
                bar_width = int(percentage)
                options_html += f'''
                <div style="margin: 8px 0; padding: 8px; background: #fff; border: 1px solid #ddd; border-radius: 4px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span>{html.escape(opt["option_text"])}</span>
                        <span style="font-weight: bold;">{percentage:.0f}%</span>
                    </div>
                    <div style="background: #eee; height: 8px; border-radius: 4px; overflow: hidden;">
                        <div style="background: #666; height: 100%; width: {bar_width}%;"></div>
                    </div>
                </div>
                '''

            polls_html += f'''
            <div class="post" style="background: rgba(135, 206, 250, 0.1); border: 2px solid #1e90ff;">
                <div class="post-header">
                    <span>Poll by {html.escape(poll["creator_name"])}</span>
                    <span>{poll_time}</span>
                </div>
                <h3 style="margin: 10px 0;">{html.escape(poll["question"])}</h3>
                {options_html}
                <p class="small" style="margin-top: 10px;">Total votes: {total_votes}</p>
            </div>
            '''

        # Get upcoming events
        events = db.execute("""
            SELECT e.*, COUNT(r.phone) as rsvp_count
            FROM events e
            LEFT JOIN rsvps r ON e.id = r.event_id
            WHERE e.event_date >= date('now') AND e.is_cancelled = 0
            GROUP BY e.id
            ORDER BY e.event_date ASC
            LIMIT 3
        """).fetchall()

        events_html = ""
        if events:
            events_html = "<h2>Upcoming Events</h2>"
            for event in events:
                spots_text = ""
                if event["max_spots"]:
                    spots_left = event["max_spots"] - event["rsvp_count"]
                    spots_text = f" · {spots_left} spots left"
                else:
                    spots_text = f" · {event['rsvp_count']} attending"

                events_html += f"""
                <div class="event">
                    <strong>{html.escape(event['title'])}</strong>
                    <p class="small">{event['event_date']} {event['start_time'] or ''}{spots_text}</p>
                </div>
                """

        # Get member count
        member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]

        # Get unused demo invite codes
        demo_codes = db.execute("""
            SELECT code FROM invite_codes
            WHERE code LIKE 'DEMO-%' AND used_by_phone IS NULL
            LIMIT 3
        """).fetchall()

        invite_codes_html = ""
        if demo_codes:
            codes = ", ".join([f"<code>{c['code']}</code>" for c in demo_codes])
            invite_codes_html = f"<p>Try these invite codes: {codes}</p>"

    content = f"""
    <div style="background: #f0f7ff; border: 2px solid #1e90ff; padding: 20px; margin-bottom: 30px; border-radius: 8px;">
        <h2 style="margin: 0 0 10px 0;">Welcome to the Demo!</h2>
        <p style="margin: 0 0 15px 0;">This is a preview of The Clubhouse community. {member_count} members are already here.</p>
        {invite_codes_html}
        <p style="margin: 0;">
            <a href="/" style="background: #000; color: #fff; padding: 10px 20px; text-decoration: none; display: inline-block;">Join the Community →</a>
            <a href="/dev" style="margin-left: 10px;">or quick login as demo user</a>
        </p>
    </div>

    {events_html}

    <h2>Community Feed</h2>
    <p class="small">A preview of recent community posts and discussions.</p>

    {polls_html}
    {posts_html}

    <div style="text-align: center; padding: 30px; background: #f9f9f9; margin-top: 30px;">
        <p>Want to join the conversation?</p>
        <a href="/" style="background: #000; color: #fff; padding: 12px 24px; text-decoration: none; display: inline-block;">Get Started →</a>
    </div>
    """

    return render_html(content, title=f"Demo - {SITE_NAME}")


@app.get("/")
async def home(request: Request):
    """The front door"""
    cookie = request.cookies.get("clubhouse")
    if cookie:
        phone = read_cookie(cookie)
        if phone:
            # Verify member still exists in database
            with get_db() as db:
                member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
                if member:
                    return RedirectResponse(url="/dashboard", status_code=303)
                else:
                    # Invalid cookie - member doesn't exist, clear it
                    response = RedirectResponse(url="/", status_code=303)
                    response.delete_cookie("clubhouse")
                    return response

    content = f"""
    <h1>{SITE_NAME}</h1>
    <p>A small, local community space.</p>

    <h2>Members Sign In</h2>
    <form method="POST" action="/send_code">
        <input type="tel" name="phone" placeholder="(555) 555-5555" required>
        <button type="submit">Send me a code</button>
    </form>

    <h2>Have an Invite Code?</h2>
    <form method="POST" action="/join">
        <input type="text" name="invite_code" placeholder="STAR-123" required>
        <button type="submit">Join the clubhouse</button>
    </form>

    <p class="small">This is a private community. Invite codes only.</p>
    {'<p style="margin-top: 20px;"><a href="/demo">👀 Preview the community →</a></p>' if DEV_MODE else ''}

    <hr style="margin-top: 40px; border: none; border-top: 1px solid var(--color-border-light);">
    <p class="small"><a href="/help">Help</a> · <a href="/contact">Contact</a> · <a href="/privacy">Privacy</a></p>
    """
    return render_html(content)


@app.post("/send_code")
async def send_code(phone: str = Form(...)):
    """Send a login code to an existing member"""
    phone = clean_phone(phone)

    if not check_rate_limit(phone):
        content = """
        <h1>Slow down</h1>
        <p class="error">Too many attempts. Try again in an hour.</p>
        <a href="/">← Back</a>
        """
        return render_html(content)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            content = """
            <h1>Not Found</h1>
            <p>This phone number isn't registered.</p>
            <p>You need an invite code to join.</p>
            <a href="/">← Back</a>
            """
            return render_html(content)

    code = generate_code()
    phone_codes[phone] = {"code": code, "created": datetime.now()}

    message = f"{SITE_NAME} login code: {code}\n\nThis code expires in 10 minutes."

    # Send SMS
    sms_sent = send_sms(phone, message)

    if PRODUCTION_MODE:
        # Production: Don't show code on screen, user must check their phone
        content = f"""
        <h1>Code Sent</h1>
        <p>We sent a 6-digit code to {format_phone(phone)}</p>

        <form method="POST" action="/verify">
            <input type="hidden" name="phone" value="{phone}">
            <input type="text" name="code" placeholder="Enter 6-digit code" maxlength="6" required
                   inputmode="numeric" pattern="[0-9]*" autocomplete="one-time-code">
            <button type="submit">Verify</button>
        </form>

        <p class="small">Didn't receive it? Check your spam folder or <a href="/">try again</a>.</p>
        """
    else:
        # Development: Show code on screen for easy testing
        print(f"\nSMS CODE FOR {format_phone(phone)}: {code}\n")

        content = f"""
        <h1>Code Generated</h1>
        <p>Your login code for {format_phone(phone)} is:</p>
        <h2 style="background: #f0f0f0; padding: 20px; text-align: center; font-size: 32px;">
            {code}
        </h2>

        <form method="POST" action="/verify">
            <input type="hidden" name="phone" value="{phone}">
            <input type="text" name="code" placeholder="000000" maxlength="6" required value="{code}">
            <button type="submit">Verify</button>
        </form>

        <p class="small"><i data-lucide="wrench" class="icon icon-sm"></i> Dev mode: Code shown on screen. Set PRODUCTION_MODE=true to hide.</p>
        <a href="/">← Back</a>
        """

    return render_html(content)


@app.post("/verify")
async def verify(phone: str = Form(...), code: str = Form(...)):
    """Check if the code is correct"""
    phone = clean_phone(phone)
    clean_old_codes()

    if phone in phone_codes and phone_codes[phone]["code"] == code:
        del phone_codes[phone]
        response = RedirectResponse(url="/dashboard", status_code=303)
        set_auth_cookie(response, phone)
        return response
    else:
        content = """
        <h1>Wrong Code</h1>
        <p>That code isn't right. Try again?</p>
        <a href="/">← Back</a>
        """
        return render_html(content)


@app.post("/join")
async def join(invite_code: str = Form(...)):
    """Join with an invite code"""
    invite_code = invite_code.upper().strip()

    with get_db() as db:
        invite = db.execute(
            "SELECT * FROM invite_codes WHERE code = ? AND used_by_phone IS NULL",
            (invite_code,)
        ).fetchone()

        if not invite:
            content = """
            <h1>Invalid Code</h1>
            <p>That invite code doesn't work.</p>
            <a href="/">← Back</a>
            """
            return render_html(content)

        member_count = db.execute("SELECT COUNT(*) as count FROM members").fetchone()["count"]
        if member_count >= MAX_MEMBERS:
            content = f"""
            <h1>We're Full</h1>
            <p>The clubhouse has reached {MAX_MEMBERS} members.</p>
            <a href="/">← Back</a>
            """
            return render_html(content)

    content = f"""
    <h1>Welcome!</h1>
    <p>Your invite code <strong>{invite_code}</strong> is valid!</p>

    <form method="POST" action="/register">
        <input type="hidden" name="invite_code" value="{invite_code}">
        <input type="text" name="name" placeholder="Your first name" required>
        <input type="tel" name="phone" placeholder="(555) 555-5555" required>
        <button type="submit">Join the clubhouse</button>
    </form>

    <a href="/">← Back</a>
    """
    return render_html(content)


@app.post("/register")
async def register(invite_code: str = Form(...), name: str = Form(...), phone: str = Form(...)):
    """Complete registration"""
    phone = clean_phone(phone)
    invite_code = invite_code.upper().strip()

    with get_db() as db:
        invite = db.execute(
            "SELECT * FROM invite_codes WHERE code = ? AND used_by_phone IS NULL",
            (invite_code,)
        ).fetchone()

        if not invite:
            raise HTTPException(status_code=400, detail="Invalid invite code")

        existing = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if existing:
            content = """
            <h1>Already Registered</h1>
            <p>This phone number is already in the clubhouse.</p>
            <a href="/">← Sign in instead</a>
            """
            return render_html(content)

        # Generate unique handle
        handle = generate_handle(name)

        is_admin_user = is_admin(phone)
        db.execute(
            "INSERT INTO members (phone, name, handle, is_admin) VALUES (?, ?, ?, ?)",
            (phone, name, handle, 1 if is_admin_user else 0)
        )

        db.execute(
            "UPDATE invite_codes SET used_by_phone = ?, used_date = CURRENT_TIMESTAMP WHERE code = ?",
            (phone, invite_code)
        )

        db.commit()

    message = f"Welcome to {SITE_NAME}, {name}!"
    send_sms(phone, message)

    # New users go to welcome tour
    response = RedirectResponse(url="/welcome", status_code=303)
    set_auth_cookie(response, phone)
    return response


@app.get("/welcome")
async def welcome_tour(request: Request):
    """Welcome page for first-time users"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT name, first_login FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

        # Mark welcome as seen
        db.execute("UPDATE members SET first_login = 0 WHERE phone = ?", (phone,))
        db.commit()

    content = f"""
    <h1>Welcome to {SITE_NAME}!</h1>

    <p style="font-size: 18px;">Hey {html.escape(member["name"])}, you're in! Here's what you can do:</p>

    <div class="event" style="margin: 20px 0;">
        <h3>Events</h3>
        <p>See what's happening and RSVP to community gatherings. This is your main dashboard.</p>
    </div>

    <div class="event" style="margin: 20px 0;">
        <h3>Feed</h3>
        <p>Share updates, thoughts, and questions with the community. React with emoji and comment on posts.</p>
    </div>

    <div class="event" style="margin: 20px 0;">
        <h3><i data-lucide="users" class="icon"></i> Members</h3>
        <p>See who's in the community. Set your status to let others know if you're available to chat.</p>
    </div>

    <div class="event" style="margin: 20px 0;">
        <h3>Notifications</h3>
        <p>Get notified when someone reacts to or comments on your posts.</p>
    </div>

    <div style="background: #f5f5f5; padding: 20px; margin: 30px 0; text-align: center;">
        <p style="margin: 0 0 15px 0;"><strong>First thing to do:</strong> Set up your profile!</p>
        <p style="margin: 0;">Pick an avatar emoji and customize your display name.</p>
    </div>

    <div style="text-align: center; margin-top: 30px;">
        <a href="/profile" style="display: inline-block; padding: 15px 30px; background: #000; color: #fff; text-decoration: none; margin-right: 10px;">Set Up Profile →</a>
        <a href="/dashboard" style="display: inline-block; padding: 15px 30px; border: 1px solid #000; text-decoration: none;">Skip to Events</a>
    </div>

    <p class="small" style="text-align: center; margin-top: 20px;">Need help? Click the <strong>?</strong> in the navigation bar anytime.</p>
    """

    return render_html(content, f"Welcome to {SITE_NAME}")


@app.get("/dashboard")
async def dashboard(request: Request, year: int = None, month: int = None):
    """Main page - events with calendar"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

        # Get calendar month (default to current)
        now = datetime.now()
        if year is None or month is None:
            year = now.year
            month = now.month

        # Get all events for this month
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        month_events = db.execute("""
            SELECT e.*,
                   COUNT(r.phone) as rsvp_count,
                   EXISTS(SELECT 1 FROM rsvps WHERE event_id = e.id AND phone = ?) as is_attending
            FROM events e
            LEFT JOIN rsvps r ON e.id = r.event_id
            WHERE e.event_date >= ? AND e.event_date < ? AND e.is_cancelled = 0
            GROUP BY e.id
            ORDER BY e.event_date ASC
        """, (phone, month_start.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d"))).fetchall()

        # Build events by day dictionary for calendar
        events_by_day = {}
        for event in month_events:
            event_date = datetime.fromisoformat(event["event_date"])
            day = event_date.day
            if day not in events_by_day:
                events_by_day[day] = []
            events_by_day[day].append(event)

        # Build calendar HTML
        # Set calendar to start on Sunday (US style)
        calendar.setfirstweekday(calendar.SUNDAY)
        month_name = calendar.month_name[month]

        # Calculate prev/next month
        if month == 1:
            prev_month = 12
            prev_year = year - 1
        else:
            prev_month = month - 1
            prev_year = year

        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year

        # CSS for calendar
        calendar_css = """
        <style>
            .calendar {
                width: 100%;
                border-collapse: separate;
                border-spacing: 0;
                margin: 20px 0;
                font-size: 14px;
                table-layout: fixed;
                border: 1px solid var(--color-border-light);
                border-radius: 8px;
                overflow: hidden;
            }
            .calendar th {
                background: #f8f8f8;
                color: var(--color-text);
                padding: 12px 10px;
                text-align: center;
                font-weight: 500;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                border-bottom: 1px solid var(--color-border-light);
            }
            .calendar td {
                border: 1px solid var(--color-border-light);
                border-top: none;
                border-left: none;
                padding: 6px;
                vertical-align: top;
                height: 80px;
                width: 14.28%;
                overflow: hidden;
                background: #fff;
                transition: background 0.15s ease;
            }
            .calendar td:first-child {
                border-left: none;
            }
            .calendar tr:last-child td:first-child {
                border-bottom-left-radius: 7px;
            }
            .calendar tr:last-child td:last-child {
                border-bottom-right-radius: 7px;
            }
            .calendar td.empty {
                background: #fafafa;
            }
            .day-number {
                font-weight: 600;
                margin-bottom: 4px;
                font-size: 13px;
                color: var(--color-text);
            }
            .calendar-event {
                font-size: 10px;
                padding: 3px 5px;
                margin: 2px 0;
                background: #f5f5f5;
                border-left: 3px solid var(--color-text-muted);
                border-radius: 0 4px 4px 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                line-height: 1.3;
                display: block;
                text-decoration: none;
                color: var(--color-text);
                transition: background 0.15s ease;
            }
            .calendar-event:hover {
                background: #ebebeb;
                cursor: pointer;
            }
            .calendar-event.attending {
                background: rgba(45, 106, 79, 0.12);
                border-left-color: var(--color-success);
                color: var(--color-success);
            }
            .today {
                background: #fffef5;
                box-shadow: inset 0 0 0 2px rgba(200, 180, 50, 0.3);
            }
            .today .day-number {
                color: #8b7500;
            }
            .calendar-nav {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin: 10px 0;
            }
            .calendar-nav h2 {
                margin: 0;
                font-size: 18px;
            }
            .calendar-nav a {
                text-decoration: none;
            }
            .calendar-nav button {
                padding: 8px 16px;
                background: transparent;
                color: var(--color-text);
                border: 1px solid var(--color-border);
                border-radius: 6px;
                cursor: pointer;
                font-size: 13px;
                transition: all 0.15s ease;
                min-height: 40px;
            }
            .calendar-nav button:hover {
                background: var(--color-text);
                color: #fff;
            }
        </style>
        """

        calendar_html = f"""
        {calendar_css}
        <div class="calendar-nav">
            <a href="/dashboard?year={prev_year}&month={prev_month}"><button>← {calendar.month_name[prev_month]}</button></a>
            <h2>{month_name} {year}</h2>
            <a href="/dashboard?year={next_year}&month={next_month}"><button>{calendar.month_name[next_month]} →</button></a>
        </div>

        <table class="calendar">
            <thead>
                <tr>
                    <th>Sun</th>
                    <th>Mon</th>
                    <th>Tue</th>
                    <th>Wed</th>
                    <th>Thu</th>
                    <th>Fri</th>
                    <th>Sat</th>
                </tr>
            </thead>
            <tbody>
        """

        # Get the calendar for this month
        cal = calendar.monthcalendar(year, month)
        today = now.day if now.year == year and now.month == month else None

        for week in cal:
            calendar_html += "<tr>"
            for day in week:
                if day == 0:
                    calendar_html += '<td class="empty"></td>'
                else:
                    today_class = "today" if day == today else ""
                    calendar_html += f'<td class="{today_class}">'
                    calendar_html += f'<div class="day-number">{day}</div>'

                    # Add events for this day
                    if day in events_by_day:
                        for event in events_by_day[day]:
                            attending_class = "attending" if event["is_attending"] else ""

                            # Format time display for calendar (just start time to save space)
                            if event["start_time"]:
                                event_time = datetime.strptime(event["start_time"], "%H:%M").strftime("%I:%M%p").lstrip("0").lower()
                            else:
                                event_time = ""

                            calendar_html += f'<a href="#event-{event["id"]}" class="calendar-event {attending_class}" title="{html.escape(event["title"])}">{event_time} {html.escape(event["title"])}</a>'

                    calendar_html += '</td>'
            calendar_html += "</tr>"

        calendar_html += """
            </tbody>
        </table>
        <p class="hint"><i data-lucide="lightbulb" class="icon icon-sm"></i> <strong>Tip:</strong> Click an event on the calendar to jump to it below. Green = you're going. Yellow = today.</p>
        """

        # Get upcoming events list
        events = db.execute("""
            SELECT e.*,
                   COUNT(r.phone) as rsvp_count,
                   EXISTS(SELECT 1 FROM rsvps WHERE event_id = e.id AND phone = ?) as is_attending
            FROM events e
            LEFT JOIN rsvps r ON e.id = r.event_id
            WHERE e.event_date > datetime('now') AND e.is_cancelled = 0
            GROUP BY e.id
            ORDER BY e.event_date ASC
        """, (phone,)).fetchall()

        events_html = ""
        for event in events:
            spots_text = ""
            if event["max_spots"]:
                spots_left = event["max_spots"] - event["rsvp_count"]
                spots_text = f"<p class='small'>{spots_left} of {event['max_spots']} spots available</p>"
            else:
                spots_text = f"<p class='small'>{event['rsvp_count']} people attending</p>"

            button = ""
            if event["is_attending"]:
                button = f'<form method="POST" action="/cancel_rsvp/{event["id"]}"><button type="submit">Cancel RSVP</button></form>'
            elif not event["max_spots"] or event["rsvp_count"] < event["max_spots"]:
                button = f'<form method="POST" action="/rsvp/{event["id"]}"><button type="submit">RSVP</button></form>'
            else:
                button = "<p><em>Event is full</em></p>"

            # Format event time
            event_time_str = format_event_time(event['event_date'], event['start_time'], event['end_time'])

            # Admin attendance link for past events
            attendance_link = ""
            try:
                # Try parsing with just date first
                event_date = datetime.strptime(event["event_date"], "%Y-%m-%d").date()
            except ValueError:
                # Fall back to datetime format (old data)
                event_date = datetime.strptime(event["event_date"].split()[0], "%Y-%m-%d").date()

            if member["is_admin"] and event_date <= datetime.now().date() and event["rsvp_count"] > 0:
                attendance_link = f'<p class="small"><a href="/attendance/{event["id"]}">📋 Track Attendance</a></p>'

            # Get photos for this event
            photos = db.execute("""
                SELECT ep.*, m.name as uploader_name
                FROM event_photos ep
                JOIN members m ON ep.uploaded_by_phone = m.phone
                WHERE ep.event_id = ?
                ORDER BY ep.uploaded_date DESC
            """, (event["id"],)).fetchall()

            photos_html = ""
            if photos:
                photos_html = '<div class="photo-gallery">'
                for photo in photos:
                    caption_text = f'<p class="small">{html.escape(photo["caption"])}</p>' if photo["caption"] else ''
                    photos_html += f'''
                    <div class="photo-item">
                        <img src="{photo['photo_url']}" alt="Event photo">
                        {caption_text}
                    </div>
                    '''
                photos_html += '</div>'

            # Photo upload form for admins on past events
            upload_form = ""
            if member["is_admin"] and event_date <= datetime.now().date():
                upload_form = f'''
                <details style="margin-top: 15px;">
                    <summary style="cursor: pointer; color: #666;">📷 Add Photos</summary>
                    <form method="POST" action="/events/{event["id"]}/upload_photo" enctype="multipart/form-data" style="margin-top: 10px;">
                        <input type="file" name="photo" accept="image/*" required style="margin-bottom: 10px;">
                        <input type="text" name="caption" placeholder="Caption (optional)" style="margin-bottom: 10px;">
                        <button type="submit">Upload Photo</button>
                    </form>
                </details>
                '''

            events_html += f"""
            <div class="event" id="event-{event['id']}">
                <h3>{html.escape(event['title'])}</h3>
                <p>{html.escape(event['description']) if event['description'] else 'No description'}</p>
                <p>{event_time_str}</p>
                {spots_text}
                {button}
                {attendance_link}
                {photos_html}
                {upload_form}
            </div>
            """

        if not events_html:
            if member["is_admin"]:
                events_html = """
                <div style="text-align: center; padding: 30px 20px; color: #666; border: 1px dashed #ccc;">
                    <p style="font-size: 18px;">No upcoming events</p>
                    <p>Ready to bring the community together?</p>
                    <p><a href="/admin">Create an event in the Admin Panel →</a></p>
                </div>
                """
            else:
                events_html = """
                <div style="text-align: center; padding: 30px 20px; color: #666; border: 1px dashed #ccc;">
                    <p style="font-size: 18px;">No upcoming events</p>
                    <p>Check back soon for community gatherings!</p>
                </div>
                """

        # Get unread notification count
        unread_count = get_unread_count(phone)
        notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

        user_display_name = member["display_name"] or member["name"]
        user_avatar = avatar_icon(member["avatar"], "sm")

        # Check if admin is viewing as member
        viewing_as_member = member["is_admin"] and request.cookies.get("view_as_member") == "1"

        nav_html = '<div class="nav">'
        nav_html += f'<a href="/profile">{user_avatar}<strong>{html.escape(user_display_name)}</strong></a> | '
        nav_html += f'<a href="/dashboard">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> | '
        nav_html += f'<a href="/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> | '
        nav_html += f'<a href="/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> | '
        nav_html += f'<a href="/notifications">{icon("bell")}<span class="mobile-hide"> Notifications</span>{notif_badge}</a> | '
        nav_html += f'<a href="/bookmarks">{icon("book-marked")}<span class="mobile-hide"> Bookmarks</span></a> | '
        if member["is_admin"] and not viewing_as_member:
            nav_html += f'<a href="/admin">{icon("terminal")}<span class="mobile-hide"> Admin</span></a> | '
        nav_html += f'<a href="/logout">{icon("log-out")}<span class="mobile-hide"> Sign out</span></a> | '
        nav_html += f'<a href="/help">{icon("help-circle")}</a>'
        nav_html += '</div>'

        invite_html = """
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ccc;">
            <h3>Know someone who'd fit in?</h3>
            <p>Send them an invite to join the community!</p>
            <form method="POST" action="/send_invite" style="margin: 15px 0;">
                <input type="tel" name="invite_phone" placeholder="Their phone number" required style="margin-bottom: 10px;">
                <button type="submit">Send Invite via Text</button>
            </form>
            <details style="margin-top: 15px;">
                <summary style="cursor: pointer; color: #666;">Or share a code manually →</summary>
                <p style="margin-top: 10px;"><a href="/create_invite" style="display: inline-block; padding: 8px 16px; background: #f0f0f0; text-decoration: none;">Generate Invite Code</a></p>
            </details>
        </div>
        """

    # Create heading with event count
    event_count_text = ""
    if len(events) > 0:
        event_count_text = f" <span class='small' style='color: #666;'>({len(events)} upcoming)</span>"

    content = f"""
    {nav_html}

    <p class="small" style="margin-bottom: -10px;"><span id="greeting">Hello</span>, {html.escape(member["name"])}</p>
    <h1>{SITE_NAME}{event_count_text}</h1>

    {calendar_html}

    {events_html}

    {invite_html}
    """

    return render_html(content)


@app.post("/rsvp/{event_id}")
async def rsvp(event_id: int, request: Request):
    """RSVP to an event"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/dashboard", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/dashboard", status_code=303)

    with get_db() as db:
        event = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        existing = db.execute(
            "SELECT * FROM rsvps WHERE event_id = ? AND phone = ?",
            (event_id, phone)
        ).fetchone()

        if not existing:
            if event["max_spots"]:
                count = db.execute(
                    "SELECT COUNT(*) as count FROM rsvps WHERE event_id = ?",
                    (event_id,)
                ).fetchone()

                if count["count"] >= event["max_spots"]:
                    raise HTTPException(status_code=400, detail="Event is full")

            db.execute(
                "INSERT INTO rsvps (event_id, phone) VALUES (?, ?)",
                (event_id, phone)
            )
            db.commit()

            message = f"You're confirmed for: {event['title']}\n {event['event_date']}"
            send_sms(phone, message)

    return RedirectResponse(url=f"/dashboard#event-{event_id}", status_code=303)


@app.post("/cancel_rsvp/{event_id}")
async def cancel_rsvp(event_id: int, request: Request):
    """Cancel an RSVP"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/dashboard", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/dashboard", status_code=303)

    with get_db() as db:
        db.execute("DELETE FROM rsvps WHERE event_id = ? AND phone = ?", (event_id, phone))
        db.commit()

    return RedirectResponse(url=f"/dashboard#event-{event_id}", status_code=303)


@app.get("/create_invite")
async def create_invite(request: Request):
    """Generate invite code (manual sharing)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/dashboard", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/dashboard", status_code=303)

    code = generate_invite()

    with get_db() as db:
        while db.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone():
            code = generate_invite()

        db.execute(
            "INSERT INTO invite_codes (code, created_by_phone) VALUES (?, ?)",
            (code, phone)
        )
        db.commit()

    join_url = f"{SITE_URL}/join/{code}" if SITE_URL else f"/join/{code}"

    content = f"""
    <h1>Invite Code Created</h1>

    <p>Share these instructions with your friend:</p>

    <div style="background: #f5f5f5; padding: 20px; margin: 20px 0; border-left: 4px solid #000;">
        <p style="margin: 0 0 15px 0;"><strong>How to join:</strong></p>
        <ol style="margin: 0; padding-left: 20px; line-height: 1.8;">
            <li>Go to: <strong>{join_url}</strong></li>
            <li>Enter your name and phone number</li>
            <li>You're in!</li>
        </ol>
    </div>

    <div style="background: #fffde7; padding: 15px; margin: 20px 0;">
        <p style="margin: 0;"><strong>Or just share the code:</strong> <span style="font-size: 20px; font-weight: bold;">{code}</span></p>
        <p class="small" style="margin: 10px 0 0 0;">They can enter this at the homepage.</p>
    </div>

    <p class="small"><i data-lucide="alert-triangle" class="icon icon-sm"></i> This code can only be used once and expires after use.</p>

    <a href="/dashboard">← Back to dashboard</a>
    """

    return render_html(content)


@app.post("/send_invite")
async def send_invite(request: Request, invite_phone: str = Form(...)):
    """Generate invite code and send via SMS"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/dashboard", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/dashboard", status_code=303)

    invite_phone = clean_phone(invite_phone)

    # Check if they're already a member
    with get_db() as db:
        existing = db.execute("SELECT * FROM members WHERE phone = ?", (invite_phone,)).fetchone()
        if existing:
            content = f"""
            <h1>Already a Member</h1>
            <p>{format_phone(invite_phone)} is already in {SITE_NAME}!</p>
            <a href="/dashboard">← Back to dashboard</a>
            """
            return render_html(content)

    code = generate_invite()

    with get_db() as db:
        while db.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone():
            code = generate_invite()

        db.execute(
            "INSERT INTO invite_codes (code, created_by_phone) VALUES (?, ?)",
            (code, phone)
        )
        db.commit()

        # Get inviter's name
        inviter = db.execute("SELECT name FROM members WHERE phone = ?", (phone,)).fetchone()
        inviter_name = inviter["name"] if inviter else "Someone"

    # Send the invite SMS
    if SITE_URL:
        join_url = f"{SITE_URL}/join/{code}"
        message = f"{inviter_name} invited you to {SITE_NAME}!\n\nTap to join: {join_url}\n\nYou'll enter your name and phone number to sign up."
    else:
        message = f"{inviter_name} invited you to {SITE_NAME}!\n\nYour invite code: {code}\n\nVisit the site and enter this code with your phone number to join."

    if send_sms(invite_phone, message):
        content = f"""
        <h1>Invite Sent!</h1>
        <p>We texted an invite to {format_phone(invite_phone)}</p>
        <p class="small">They'll get a link to join {SITE_NAME}.</p>
        <a href="/dashboard">← Back to dashboard</a>
        """
    else:
        content = f"""
        <h1>Couldn't Send Text</h1>
        <p>SMS failed. You can share this code manually:</p>
        <div style="background: #f0f0f0; padding: 20px; margin: 20px 0;">
            <p><strong>Code:</strong> {code}</p>
        </div>
        <a href="/dashboard">← Back to dashboard</a>
        """

    return render_html(content)


@app.get("/join/{code}")
async def join_with_code(code: str):
    """Pre-filled join page with invite code"""
    code = code.upper().strip()

    with get_db() as db:
        invite = db.execute(
            "SELECT * FROM invite_codes WHERE code = ? AND used_by_phone IS NULL",
            (code,)
        ).fetchone()

        if not invite:
            content = """
            <h1>Invalid Code</h1>
            <p>This invite code doesn't work or has already been used.</p>
            <a href="/">← Back to home</a>
            """
            return render_html(content)

    content = f"""
    <h1>You're Invited!</h1>
    <p>Enter your details to join {SITE_NAME}.</p>

    <form method="POST" action="/register">
        <input type="hidden" name="invite_code" value="{code}">
        <input type="text" name="name" placeholder="Your first name" required>
        <input type="tel" name="phone" placeholder="(555) 555-5555" required>
        <button type="submit">Join</button>
    </form>
    """
    return render_html(content)


@app.get("/feed")
async def feed(request: Request, q: str = ""):
    """Community feed with optional search"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

        # Check if admin is viewing as member
        viewing_as_member = member["is_admin"] and request.cookies.get("view_as_member") == "1"

        # Get all posts (pinned first, then by date), with optional search
        if q:
            # Search posts by content
            search_term = f"%{q}%"
            posts = db.execute("""
                SELECT p.*, m.name, m.display_name, m.avatar
                FROM posts p
                JOIN members m ON p.phone = m.phone
                WHERE p.content LIKE ?
                ORDER BY p.is_pinned DESC, p.posted_date DESC
                LIMIT 50
            """, (search_term,)).fetchall()
        else:
            posts = db.execute("""
                SELECT p.*, m.name, m.display_name, m.avatar
                FROM posts p
                JOIN members m ON p.phone = m.phone
                ORDER BY p.is_pinned DESC, p.posted_date DESC
                LIMIT 50
            """).fetchall()

        posts_html = ""
        if posts:
            for post in posts:
                relative_time = format_relative_time(post["posted_date"])
                post_content = sanitize_content(post['content'])

                # Get reactions
                reactions = db.execute("""
                    SELECT emoji, COUNT(*) as count,
                           EXISTS(SELECT 1 FROM reactions WHERE post_id = ? AND phone = ? AND emoji = r.emoji) as user_reacted
                    FROM reactions r
                    WHERE post_id = ?
                    GROUP BY emoji
                """, (post["id"], phone, post["id"])).fetchall()

                reactions_html = f'<div class="reactions" id="reactions-{post["id"]}">'
                for reaction in reactions:
                    active_class = "active" if reaction["user_reacted"] else ""
                    # Render as icon if it's a known icon name, otherwise show as text
                    reaction_name = reaction["emoji"]
                    if reaction_name in REACTION_ICONS:
                        reaction_display = f'<i data-lucide="{reaction_name}" class="icon icon-sm"></i>'
                    else:
                        reaction_display = reaction_name
                    reactions_html += f'<button onclick="toggleReaction({post["id"]}, \'{reaction_name}\')" class="reaction-btn {active_class}" data-emoji="{reaction_name}">{reaction_display} <span class="count">{reaction["count"]}</span></button>'

                # Quick reaction buttons (using Lucide icons)
                existing_reactions = [r["emoji"] for r in reactions]
                for reaction_icon in REACTION_ICONS:
                    if reaction_icon not in existing_reactions:
                        reactions_html += f'<button onclick="toggleReaction({post["id"]}, \'{reaction_icon}\')" class="reaction-btn" data-emoji="{reaction_icon}"><i data-lucide="{reaction_icon}" class="icon icon-sm"></i> <span class="count"></span></button>'

                reactions_html += '</div>'

                # Get comments
                comments = db.execute("""
                    SELECT c.*, m.name, m.display_name, m.avatar
                    FROM comments c
                    JOIN members m ON c.phone = m.phone
                    WHERE c.post_id = ?
                    ORDER BY c.posted_date ASC
                """, (post["id"],)).fetchall()

                comments_html = ""
                if comments:
                    comments_html = '<div style="margin-top: 10px; padding-left: 20px; border-left: 2px solid #ddd;">'
                    for comment in comments:
                        comment_time = format_relative_time(comment["posted_date"])
                        comment_content = sanitize_content(comment["content"])

                        # Moderator/Admin delete button
                        comment_delete = ""
                        if is_moderator_or_admin(member) and not viewing_as_member:
                            comment_delete = f'''
                            <form method="POST" action="/delete_comment/{comment['id']}" style="display: inline; margin-left: 5px;">
                                <button type="submit" onclick="return confirm('Delete?')" style="background: #d00; color: white; padding: 2px 6px; font-size: 11px;" title="Delete"><i data-lucide="trash" class="icon icon-sm"></i></button>
                            </form>
                            '''

                        comment_name = comment["display_name"] or comment["name"]
                        comment_avatar = avatar_icon(comment["avatar"], "sm")

                        comments_html += f'''
                        <div style="margin: 8px 0; padding: 8px; background: rgba(0,0,0,0.02);">
                            <div style="font-size: 12px; color: #666; margin-bottom: 4px;">
                                {comment_avatar}<strong>{html.escape(comment_name)}</strong> · {comment_time}{comment_delete}
                            </div>
                            <div style="font-size: 14px;">{comment_content}</div>
                        </div>
                        '''
                    comments_html += '</div>'

                # Reply form
                csrf_token = get_csrf_token(phone)
                reply_form = f'''
                <details style="margin-top: 10px;">
                    <summary>Reply ({len(comments)})</summary>
                    <form method="POST" action="/reply/{post['id']}" style="margin-top: 8px;">
                        <input type="hidden" name="csrf_token" value="{csrf_token}">
                        <textarea name="content" placeholder="Write a reply..." rows="2" required maxlength="300" style="width: 100%; font-family: inherit; font-size: 14px; padding: 8px;"></textarea>
                        <button type="submit" style="padding: 6px 12px; font-size: 13px;">Post Reply</button>
                    </form>
                </details>
                '''

                # Moderator/Admin controls
                mod_controls = ""
                if is_moderator_or_admin(member) and not viewing_as_member:
                    pin_button = ""
                    if post["is_pinned"]:
                        pin_button = f'''
                        <form method="POST" action="/unpin_post/{post['id']}" style="display: inline; margin-left: 5px;">
                            <button type="submit" style="background: #666; color: white; padding: 4px 8px; font-size: 12px;" title="Unpin"><i data-lucide="pin-off" class="icon icon-sm"></i></button>
                        </form>
                        '''
                    else:
                        pin_button = f'''
                        <form method="POST" action="/pin_post/{post['id']}" style="display: inline; margin-left: 5px;">
                            <button type="submit" style="background: #333; color: white; padding: 4px 8px; font-size: 12px;" title="Pin"><i data-lucide="pin" class="icon icon-sm"></i></button>
                        </form>
                        '''

                    delete_button = f'''
                    <form method="POST" action="/delete_post/{post['id']}" style="display: inline; margin-left: 5px;">
                        <button type="submit" onclick="return confirm('Delete post?')" style="background: #d00; color: white; padding: 4px 8px; font-size: 12px;" title="Delete"><i data-lucide="trash" class="icon icon-sm"></i></button>
                    </form>
                    '''
                    mod_controls = pin_button + delete_button

                pinned_badge = ""
                if post["is_pinned"]:
                    pinned_badge = '<span style="background: #28a745; color: white; padding: 2px 6px; font-size: 11px; border-radius: 3px; margin-right: 8px;">PINNED</span>'

                # Check if bookmarked
                is_bookmarked = db.execute(
                    "SELECT 1 FROM bookmarks WHERE phone = ? AND post_id = ?",
                    (phone, post["id"])
                ).fetchone()

                bookmark_icon = icon("bookmark-check") if is_bookmarked else icon("bookmark")
                bookmark_link = f'<a href="/bookmark/{post["id"]}" style="margin-left: 10px;">{bookmark_icon} {"Saved" if is_bookmarked else "Save"}</a>'

                # Get display name and avatar
                post_name = post["display_name"] or post["name"]
                post_avatar = avatar_icon(post["avatar"], "sm")

                posts_html += f"""
                <div class="post" id="post-{post['id']}" style="{'border: 2px solid #28a745;' if post['is_pinned'] else ''}">
                    <div class="post-header">
                        <span>{post_avatar}{pinned_badge}{html.escape(post_name)}</span>
                        <span>{relative_time}{bookmark_link}{mod_controls}</span>
                    </div>
                    <div class="post-content">{post_content}</div>
                    {reactions_html}
                    {comments_html}
                    {reply_form}
                </div>
                """
        else:
            posts_html = """
            <div style="text-align: center; padding: 40px 20px; color: #666;">
                <p style="font-size: 18px;">No posts yet</p>
                <p>Be the first to start a conversation!</p>
            </div>
            """

        # Get active polls
        polls = db.execute("""
            SELECT p.*, m.name as creator_name
            FROM polls p
            JOIN members m ON p.created_by_phone = m.phone
            WHERE p.is_active = 1
            ORDER BY p.created_date DESC
            LIMIT 5
        """).fetchall()

        polls_html = ""
        for poll in polls:
            # Get poll options and votes
            options = db.execute("""
                SELECT po.id, po.option_text, po.vote_count,
                       EXISTS(SELECT 1 FROM poll_votes WHERE poll_id = ? AND phone = ? AND option_id = po.id) as user_voted
                FROM poll_options po
                WHERE po.poll_id = ?
                ORDER BY po.id
            """, (poll["id"], phone, poll["id"])).fetchall()

            # Check if user has voted
            user_vote = db.execute(
                "SELECT option_id FROM poll_votes WHERE poll_id = ? AND phone = ?",
                (poll["id"], phone)
            ).fetchone()

            total_votes = sum(opt["vote_count"] for opt in options)

            poll_time = format_relative_time(poll["created_date"])

            options_html = ""
            if user_vote:
                # Show results with ability to change vote
                for opt in options:
                    percentage = (opt["vote_count"] / total_votes * 100) if total_votes > 0 else 0
                    bar_width = int(percentage)

                    # Make each option clickable to change vote
                    options_html += f'''
                    <form method="POST" action="/vote/{poll["id"]}/{opt["id"]}" style="margin: 8px 0;">
                        <button type="submit" style="width: 100%; padding: 8px; text-align: left; background: {"rgba(40, 167, 69, 0.1)" if opt["user_voted"] else "#fff"}; color: #000; border: 1px solid {"#28a745" if opt["user_voted"] else "#ddd"}; border-radius: 4px; cursor: pointer;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span>{"✓ " if opt["user_voted"] else ""}{html.escape(opt["option_text"])}</span>
                                <span style="font-weight: bold;">{percentage:.0f}%</span>
                            </div>
                            <div style="background: #eee; height: 8px; border-radius: 4px; overflow: hidden;">
                                <div style="background: {"#28a745" if opt["user_voted"] else "#666"}; height: 100%; width: {bar_width}%;"></div>
                            </div>
                            <p class="small" style="margin: 4px 0 0 0;">{opt["vote_count"]} vote{"s" if opt["vote_count"] != 1 else ""}</p>
                        </button>
                    </form>
                    '''

                # Add undo button and total votes
                options_html += f'''
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px;">
                    <p class="small" style="margin: 0;">Total votes: {total_votes}</p>
                    <form method="POST" action="/undo_vote/{poll["id"]}" style="display: inline;">
                        <button type="submit" style="background: #666; color: #fff; padding: 6px 12px; font-size: 12px; border-radius: 4px;">Undo Vote</button>
                    </form>
                </div>
                '''
            else:
                # Show voting buttons
                for opt in options:
                    options_html += f'''
                    <form method="POST" action="/vote/{poll["id"]}/{opt["id"]}" style="margin: 8px 0;">
                        <button type="submit" style="width: 100%; padding: 12px; text-align: left; background: #fff; color: #000; border: 1px solid #000;">
                            {html.escape(opt["option_text"])}
                        </button>
                    </form>
                    '''

            polls_html += f'''
            <div class="post" id="poll-{poll["id"]}" style="background: rgba(135, 206, 250, 0.1); border: 2px solid #1e90ff;">
                <div class="post-header">
                    <span>Poll by {html.escape(poll["creator_name"])}</span>
                    <span>{poll_time}</span>
                </div>
                <h3 style="margin: 10px 0;">{html.escape(poll["question"])}</h3>
                {options_html}
            </div>
            '''

        # Get unread notification count
        unread_count = get_unread_count(phone)
        notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

        user_display_name = member["display_name"] or member["name"]
        user_avatar = avatar_icon(member["avatar"], "sm")

        nav_html = '<div class="nav">'
        nav_html += f'<a href="/profile"><strong>{html.escape(user_display_name)}</strong></a> | '
        nav_html += f'<a href="/dashboard">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> | '
        nav_html += f'<a href="/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> | '
        nav_html += f'<a href="/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> | '
        nav_html += f'<a href="/notifications">{icon("bell")}<span class="mobile-hide"> Notifications</span>{notif_badge}</a> | '
        nav_html += f'<a href="/bookmarks">{icon("book-marked")}<span class="mobile-hide"> Bookmarks</span></a> | '
        if member["is_admin"] and not viewing_as_member:
            nav_html += f'<a href="/admin">{icon("terminal")}<span class="mobile-hide"> Admin</span></a> | '
        nav_html += f'<a href="/logout">{icon("log-out")}<span class="mobile-hide"> Sign out</span></a> | '
        nav_html += f'<a href="/help">{icon("help-circle")}</a>'
        nav_html += '</div>'

        csrf_token = get_csrf_token(phone)

    # Build search form
    search_form = f"""
    <form method="GET" action="/feed" style="margin: 20px 0;">
        <input type="text" name="q" placeholder="Search posts..." value="{html.escape(q)}" style="width: 70%; display: inline-block;">
        <button type="submit" style="width: 28%; display: inline-block;">🔍 Search</button>
    </form>
    """
    if q:
        search_form += f'<p class="small">Showing results for "{html.escape(q)}" · <a href="/feed">Clear search</a></p>'

    content = f"""
    {nav_html}

    <h1>Community Feed</h1>

    {search_form}

    <form method="POST" action="/post" style="margin-bottom: 30px;">
        <input type="hidden" name="csrf_token" value="{csrf_token}">
        <textarea id="post-textarea" name="content" placeholder="What's on your mind?" rows="3" required maxlength="500" oninput="updateCharCount()"></textarea>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
            <span class="small"><span id="char-count">0</span>/500 characters</span>
            <button type="submit" style="margin: 0; width: auto;">Post</button>
        </div>
    </form>

    <script>
    function updateCharCount() {{
        const textarea = document.getElementById('post-textarea');
        const count = document.getElementById('char-count');
        count.textContent = textarea.value.length;
        // Change color when approaching limit
        if (textarea.value.length > 450) {{
            count.style.color = '#d00';
        }} else {{
            count.style.color = '#666';
        }}
    }}

    function toggleReaction(postId, emoji) {{
        fetch(`/react/${{postId}}/${{encodeURIComponent(emoji)}}`, {{
            method: 'POST',
            credentials: 'same-origin'
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                const container = document.getElementById(`reactions-${{postId}}`);
                const btn = container.querySelector(`button[data-emoji="${{emoji}}"]`);
                if (btn) {{
                    const countSpan = btn.querySelector('.count');
                    if (data.action === 'added') {{
                        btn.classList.add('active');
                        countSpan.textContent = data.count;
                    }} else {{
                        btn.classList.remove('active');
                        countSpan.textContent = data.count > 0 ? data.count : '';
                    }}
                }}
            }}
        }})
        .catch(err => console.error('Reaction failed:', err));
    }}
    </script>

    {polls_html}
    {posts_html}
    """

    return render_html(content)


@app.post("/post")
async def create_post(content: str = Form(...), csrf_token: str = Form(...), request: Request = None):
    """Create a new post"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    if not verify_csrf_token(phone, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    content = content.strip()
    if not content or len(content) > 500:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        db.execute("INSERT INTO posts (phone, content) VALUES (?, ?)", (phone, content))
        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


@app.post("/react/{post_id}/{emoji}")
async def react_to_post(post_id: int, emoji: str, request: Request):
    """Add or remove a reaction (AJAX-friendly)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return {"error": "Not logged in"}

    phone = read_cookie(cookie)
    if not phone:
        return {"error": "Not logged in"}

    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM reactions WHERE post_id = ? AND phone = ? AND emoji = ?",
            (post_id, phone, emoji)
        ).fetchone()

        if existing:
            db.execute(
                "DELETE FROM reactions WHERE post_id = ? AND phone = ? AND emoji = ?",
                (post_id, phone, emoji)
            )
            action = "removed"
        else:
            # Get post author
            post = db.execute("SELECT phone FROM posts WHERE id = ?", (post_id,)).fetchone()

            # Get reactor name
            reactor = db.execute("SELECT name, display_name FROM members WHERE phone = ?", (phone,)).fetchone()
            reactor_name = reactor["display_name"] or reactor["name"] if reactor else "Someone"

            db.execute(
                "INSERT INTO reactions (post_id, phone, emoji) VALUES (?, ?, ?)",
                (post_id, phone, emoji)
            )
            action = "added"

            # Create notification for post author (only when adding reaction, not removing)
            if post:
                create_notification(
                    post["phone"],
                    phone,
                    "reaction",
                    f"{reactor_name} reacted {emoji} to your post",
                    post_id
                )

        # Get updated reaction count
        count = db.execute(
            "SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND emoji = ?",
            (post_id, emoji)
        ).fetchone()["count"]

        db.commit()

    return {"success": True, "action": action, "count": count, "emoji": emoji, "post_id": post_id}


@app.post("/vote/{poll_id}/{option_id}")
async def vote_on_poll(poll_id: int, option_id: int, request: Request):
    """Vote on a poll"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        # Check if already voted
        existing_vote = db.execute(
            "SELECT option_id FROM poll_votes WHERE poll_id = ? AND phone = ?",
            (poll_id, phone)
        ).fetchone()

        if existing_vote:
            # User is changing their vote
            old_option_id = existing_vote["option_id"]

            if old_option_id != option_id:
                # Decrement old option
                db.execute(
                    "UPDATE poll_options SET vote_count = vote_count - 1 WHERE id = ?",
                    (old_option_id,)
                )

                # Update vote record
                db.execute(
                    "UPDATE poll_votes SET option_id = ? WHERE poll_id = ? AND phone = ?",
                    (option_id, poll_id, phone)
                )

                # Increment new option
                db.execute(
                    "UPDATE poll_options SET vote_count = vote_count + 1 WHERE id = ?",
                    (option_id,)
                )
        else:
            # First time voting
            db.execute(
                "INSERT INTO poll_votes (poll_id, phone, option_id) VALUES (?, ?, ?)",
                (poll_id, phone, option_id)
            )

            # Increment vote count
            db.execute(
                "UPDATE poll_options SET vote_count = vote_count + 1 WHERE id = ?",
                (option_id,)
            )

        db.commit()

    return RedirectResponse(url=f"/feed#poll-{poll_id}", status_code=303)


@app.post("/undo_vote/{poll_id}")
async def undo_vote(poll_id: int, request: Request):
    """Remove vote from a poll"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        # Get user's current vote
        existing_vote = db.execute(
            "SELECT option_id FROM poll_votes WHERE poll_id = ? AND phone = ?",
            (poll_id, phone)
        ).fetchone()

        if existing_vote:
            # Decrement vote count
            db.execute(
                "UPDATE poll_options SET vote_count = vote_count - 1 WHERE id = ?",
                (existing_vote["option_id"],)
            )

            # Remove vote record
            db.execute(
                "DELETE FROM poll_votes WHERE poll_id = ? AND phone = ?",
                (poll_id, phone)
            )

            db.commit()

    return RedirectResponse(url=f"/feed#poll-{poll_id}", status_code=303)


@app.get("/bookmark/{post_id}")
async def toggle_bookmark(post_id: int, request: Request):
    """Add or remove a bookmark"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        # Check if already bookmarked
        existing = db.execute(
            "SELECT * FROM bookmarks WHERE phone = ? AND post_id = ?",
            (phone, post_id)
        ).fetchone()

        if existing:
            # Remove bookmark
            db.execute("DELETE FROM bookmarks WHERE phone = ? AND post_id = ?", (phone, post_id))
        else:
            # Add bookmark
            db.execute("INSERT INTO bookmarks (phone, post_id) VALUES (?, ?)", (phone, post_id))

        db.commit()

    # Get referrer to redirect back, append fragment to keep scroll position
    referer = request.headers.get("referer", "/feed")
    # Strip any existing fragment and add the post anchor
    base_url = referer.split("#")[0]
    return RedirectResponse(url=f"{base_url}#post-{post_id}", status_code=303)


@app.get("/bookmarks")
async def bookmarks_page(request: Request):
    """View saved bookmarks"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

        # Get bookmarked posts
        posts = db.execute("""
            SELECT p.*, m.name, m.display_name, m.avatar
            FROM bookmarks b
            JOIN posts p ON b.post_id = p.id
            JOIN members m ON p.phone = m.phone
            WHERE b.phone = ?
            ORDER BY b.created_date DESC
            LIMIT 50
        """, (phone,)).fetchall()

        posts_html = ""
        if posts:
            for post in posts:
                relative_time = format_relative_time(post["posted_date"])
                post_content = sanitize_content(post['content'])
                post_name = post["display_name"] or post["name"]
                post_avatar = avatar_icon(post["avatar"], "sm")

                posts_html += f"""
                <div class="post" id="post-{post['id']}">
                    <div class="post-header">
                        <span>{post_avatar}{html.escape(post_name)}</span>
                        <span>{relative_time} · <a href="/bookmark/{post['id']}">{icon("bookmark-minus")} Remove</a></span>
                    </div>
                    <div class="post-content">{post_content}</div>
                    <p class="small"><a href="/feed#post-{post['id']}">View on feed →</a></p>
                </div>
                """
        else:
            posts_html = """
            <div style="text-align: center; padding: 30px 20px; color: #666; border: 1px dashed #ccc;">
                <p style="font-size: 18px;">No bookmarks yet</p>
                <p>Bookmark posts from the feed by clicking the bookmark icon to save them here.</p>
                <p><a href="/feed">Go to the Feed →</a></p>
            </div>
            """

        # Get unread notification count
        unread_count = get_unread_count(phone)
        notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

        user_display_name = member["display_name"] or member["name"]
        user_avatar = avatar_icon(member["avatar"], "sm")

        nav_html = '<div class="nav">'
        nav_html += f'<a href="/profile"><strong>{html.escape(user_display_name)}</strong></a> | '
        nav_html += f'<a href="/dashboard">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> | '
        nav_html += f'<a href="/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> | '
        nav_html += f'<a href="/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> | '
        nav_html += f'<a href="/notifications">{icon("bell")}<span class="mobile-hide"> Notifications</span>{notif_badge}</a> | '
        nav_html += f'<a href="/bookmarks">{icon("book-marked")}<span class="mobile-hide"> Bookmarks</span></a> | '
        if member["is_admin"]:
            nav_html += f'<a href="/admin">{icon("terminal")}<span class="mobile-hide"> Admin</span></a> | '
        nav_html += f'<a href="/logout">{icon("log-out")}<span class="mobile-hide"> Sign out</span></a> | '
        nav_html += f'<a href="/help">{icon("help-circle")}</a>'
        nav_html += '</div>'

    content = f"""
    {nav_html}

    <h1>Your Bookmarks</h1>
    <p class="small">Posts you've saved for later</p>

    {posts_html}
    """

    return render_html(content)


@app.post("/reply/{post_id}")
async def reply_to_post(post_id: int, content: str = Form(...), csrf_token: str = Form(...), request: Request = None):
    """Post a reply"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    if not verify_csrf_token(phone, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    content = content.strip()
    if not content or len(content) > 300:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        # Get post author
        post = db.execute("SELECT phone FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            return RedirectResponse(url="/feed", status_code=303)

        # Get commenter name
        commenter = db.execute("SELECT name, display_name FROM members WHERE phone = ?", (phone,)).fetchone()
        commenter_name = commenter["display_name"] or commenter["name"] if commenter else "Someone"

        db.execute(
            "INSERT INTO comments (post_id, phone, content) VALUES (?, ?, ?)",
            (post_id, phone, content)
        )
        db.commit()

        # Create notification for post author
        create_notification(
            post["phone"],
            phone,
            "comment",
            f"{commenter_name} commented on your post",
            post_id
        )

    return RedirectResponse(url=f"/feed#post-{post_id}", status_code=303)


@app.post("/pin_post/{post_id}")
async def pin_post(post_id: int, request: Request):
    """Pin a post (moderator/admin)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member or not is_moderator_or_admin(member):
            raise HTTPException(status_code=403, detail="Moderator access required")

        db.execute("UPDATE posts SET is_pinned = 1 WHERE id = ?", (post_id,))
        db.commit()

    return RedirectResponse(url=f"/feed#post-{post_id}", status_code=303)


@app.post("/unpin_post/{post_id}")
async def unpin_post(post_id: int, request: Request):
    """Unpin a post (moderator/admin)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member or not is_moderator_or_admin(member):
            raise HTTPException(status_code=403, detail="Moderator access required")

        db.execute("UPDATE posts SET is_pinned = 0 WHERE id = ?", (post_id,))
        db.commit()

    return RedirectResponse(url=f"/feed#post-{post_id}", status_code=303)


@app.post("/delete_post/{post_id}")
async def delete_post(post_id: int, request: Request):
    """Delete a post (moderator/admin)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member or not is_moderator_or_admin(member):
            raise HTTPException(status_code=403, detail="Moderator access required")

        db.execute("DELETE FROM reactions WHERE post_id = ?", (post_id,))
        db.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


@app.post("/delete_comment/{comment_id}")
async def delete_comment(comment_id: int, request: Request):
    """Delete a comment (moderator/admin)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member or not is_moderator_or_admin(member):
            raise HTTPException(status_code=403, detail="Moderator access required")

        db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


@app.get("/notifications")
async def notifications_page(request: Request):
    """View all notifications"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        # Get current member info
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

        # Get all notifications for this user
        notifications = db.execute("""
            SELECT n.*, m.name, m.display_name, m.handle, m.avatar
            FROM notifications n
            LEFT JOIN members m ON n.actor_phone = m.phone
            WHERE n.recipient_phone = ?
            ORDER BY n.created_date DESC
            LIMIT 50
        """, (phone,)).fetchall()

        # Mark all as read
        db.execute("UPDATE notifications SET is_read = 1 WHERE recipient_phone = ?", (phone,))
        db.commit()

    # Build notifications HTML
    notifs_html = ""
    if notifications:
        for n in notifications:
            actor_name = n["display_name"] or n["name"] or "Someone"
            actor_avatar = n["avatar"] if n["avatar"] in AVATAR_ICONS else DEFAULT_AVATAR
            time_ago = n["created_date"][:16]  # Simple date/time display
            read_class = "" if n["is_read"] else 'style="background: #f0f8ff;"'

            # Link to related content
            link = ""
            if n["type"] == "comment" and n["related_id"]:
                link = f' <a href="/feed#post-{n["related_id"]}">[View Post]</a>'
            elif n["type"] == "reaction" and n["related_id"]:
                link = f' <a href="/feed#post-{n["related_id"]}">[View Post]</a>'

            notifs_html += f"""
            <div class="event" {read_class}>
                <p>{avatar_icon(actor_avatar, "sm")}<strong>{html.escape(n["message"])}</strong>{link}</p>
                <p class="small">{time_ago}</p>
            </div>
            """
    else:
        notifs_html = """
        <div style="text-align: center; padding: 30px 20px; color: #666; border: 1px dashed #ccc;">
            <p style="font-size: 18px;">All caught up!</p>
            <p>Notifications appear when someone reacts to or comments on your posts.</p>
            <p><a href="/feed">Go to the Feed →</a></p>
        </div>
        """

    # Get unread notification count
    unread_count = 0  # Just marked all as read
    notif_badge = ''

    user_display_name = member["display_name"] or member["name"]
    user_avatar = avatar_icon(member["avatar"], "sm")

    nav_html = '<div class="nav">'
    nav_html += f'<a href="/profile">{user_avatar}<strong>{html.escape(user_display_name)}</strong></a> | '
    nav_html += f'<a href="/dashboard">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> | '
    nav_html += f'<a href="/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> | '
    nav_html += f'<a href="/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> | '
    nav_html += f'<a href="/notifications">{icon("bell")}<span class="mobile-hide"> Notifications</span>{notif_badge}</a> | '
    if member["is_admin"]:
        nav_html += f'<a href="/admin">{icon("terminal")}<span class="mobile-hide"> Admin</span></a> | '
    nav_html += '<a href="/logout">Sign out</a> | '
    nav_html += '<a href="/help">?</a>'
    nav_html += '</div>'

    content = f"""
    {nav_html}

    <h1>Notifications</h1>

    {notifs_html}
    """

    return render_html(content)


@app.get("/profile")
async def profile_page(request: Request):
    """User profile - edit display name"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

    display_name = member["display_name"] or member["name"]
    handle = member["handle"] or "Not set"
    current_avatar = member["avatar"] if member["avatar"] in AVATAR_ICONS else DEFAULT_AVATAR
    birthday = member["birthday"] or ""

    # Icon picker
    icon_picker = '<div style="display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; max-width: 360px;">'
    for icon_name in AVATAR_ICONS:
        is_selected = icon_name == current_avatar
        bg = "var(--color-text)" if is_selected else "var(--color-bg)"
        fg = "var(--color-bg)" if is_selected else "var(--color-text)"
        icon_picker += f'''<button type="button" onclick="selectAvatar('{icon_name}')" class="avatar-option" id="avatar-{icon_name}" style="padding: 12px; cursor: pointer; border: 1px solid var(--color-border-light); border-radius: 8px; background: {bg}; color: {fg};"><i data-lucide="{icon_name}" class="icon icon-lg"></i></button>'''
    icon_picker += '</div>'

    # Get unread notification count
    unread_count = get_unread_count(phone)
    notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

    nav_html = '<div class="nav">'
    nav_html += f'<a href="/profile"><strong>{member["name"]}</strong></a> | '
    nav_html += f'<a href="/dashboard">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> | '
    nav_html += f'<a href="/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> | '
    nav_html += f'<a href="/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> | '
    nav_html += f'<a href="/notifications">{icon("bell")}<span class="mobile-hide"> Notifications</span>{notif_badge}</a> | '
    if member["is_admin"]:
        nav_html += '<a href="/admin">Admin</a> | '
    nav_html += '<a href="/logout">Sign out</a> | '
    nav_html += '<a href="/help">?</a>'
    nav_html += '</div>'

    member_since = format_member_since(member["joined_date"])

    content = f"""
    {nav_html}

    <h1><span id="greeting">Hello</span>, {html.escape(member["name"])}!</h1>
    <p class="small" style="margin-top: -20px; margin-bottom: 20px;">{member_since}</p>

    <div class="event">
        <h3>Your Info</h3>
        <p><strong>Avatar:</strong> {avatar_icon(current_avatar, "")}</p>
        <p><strong>Handle:</strong> @{html.escape(handle)}</p>
        <p><strong>Display Name:</strong> {html.escape(display_name)}</p>
        <p><strong>Phone:</strong> {format_phone(phone)}</p>
        <p><strong>Birthday:</strong> {birthday if birthday else "Not set"}</p>
    </div>

    <div class="event">
        <h3>Pick Your Avatar</h3>
        <p>Choose an icon to represent you.</p>
        <form method="POST" action="/update_profile">
            <p>Current: <span id="current-avatar">{avatar_icon(current_avatar, "")}</span></p>
            {icon_picker}
            <input type="hidden" id="avatar-input" name="avatar" value="{current_avatar}">
            <button type="submit" style="margin-top: 15px;">Save Avatar</button>
        </form>
        <p class="small" style="margin-top: 15px;">Your avatar appears next to your posts and comments.</p>
        <script>
        function selectAvatar(iconName) {{
            document.getElementById('avatar-input').value = iconName;
            document.querySelectorAll('.avatar-option').forEach(btn => {{
                btn.style.background = 'var(--color-bg)';
                btn.style.color = 'var(--color-text)';
            }});
            document.getElementById('avatar-' + iconName).style.background = 'var(--color-text)';
            document.getElementById('avatar-' + iconName).style.color = 'var(--color-bg)';
            lucide.createIcons();
        }}
        </script>
    </div>

    <div class="event">
        <h3>Edit Display Name</h3>
        <p>This is the name others see. You can change it anytime!</p>
        <form method="POST" action="/update_display_name">
            <input type="text" name="display_name" value="{html.escape(display_name)}" placeholder="Display name" required maxlength="50">
            <button type="submit">Update Display Name</button>
        </form>
    </div>

    <div class="event">
        <h3>Birthday (Optional)</h3>
        <p>We'll wish you happy birthday and show a badge on your special day!</p>
        <form method="POST" action="/update_birthday">
            <input type="date" name="birthday" value="{birthday}">
            <button type="submit">Save Birthday</button>
        </form>
    </div>

    <p class="small">Only admins can change handles. Contact an admin if you need your handle changed.</p>
    """

    return render_html(content)


@app.post("/update_display_name")
async def update_display_name(request: Request, display_name: str = Form(...)):
    """Update user's display name"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    display_name = display_name.strip()
    if not display_name or len(display_name) > 50:
        return RedirectResponse(url="/profile", status_code=303)

    with get_db() as db:
        db.execute("UPDATE members SET display_name = ? WHERE phone = ?", (display_name, phone))
        db.commit()

    return RedirectResponse(url="/profile", status_code=303)


@app.post("/update_profile")
async def update_profile(request: Request, avatar: str = Form(...)):
    """Update user's avatar"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        db.execute("UPDATE members SET avatar = ? WHERE phone = ?", (avatar, phone))
        db.commit()

    return RedirectResponse(url="/profile", status_code=303)


@app.post("/update_birthday")
async def update_birthday(request: Request, birthday: str = Form(...)):
    """Update user's birthday"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        db.execute("UPDATE members SET birthday = ? WHERE phone = ?", (birthday, phone))
        db.commit()

    return RedirectResponse(url="/profile", status_code=303)


@app.get("/members")
async def members_directory(request: Request):
    """Member directory - see who's in the clubhouse"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        # Get current member info
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            return RedirectResponse(url="/", status_code=303)

        # Get all active members
        members = db.execute("""
            SELECT name, display_name, avatar, phone, joined_date, is_admin, is_moderator, status, birthday
            FROM members
            WHERE is_active = 1
            ORDER BY joined_date DESC
        """).fetchall()

    # Build member list HTML
    members_list = ""
    for m in members:
        # Badge for admin/moderator
        badge = ""
        if m["is_admin"]:
            badge = '<span style="background: #000; color: #fff; padding: 2px 6px; font-size: 11px; margin-left: 8px;">ADMIN</span>'
        elif m["is_moderator"]:
            badge = '<span style="background: #666; color: #fff; padding: 2px 6px; font-size: 11px; margin-left: 8px;">MOD</span>'

        # Status indicator (using distinct icons)
        status = m["status"] or "available"
        status_icons = {
            "available": '<span class="status-available" title="Available"><i data-lucide="circle-dot" class="icon icon-sm"></i></span>',
            "away": '<span class="status-away" title="Away"><i data-lucide="moon" class="icon icon-sm"></i></span>',
            "busy": '<span class="status-busy" title="Busy"><i data-lucide="headphones" class="icon icon-sm"></i></span>'
        }
        status_icon = status_icons.get(status, status_icons["available"])
        status_text = status.capitalize()

        # Member card
        join_date = datetime.strptime(m["joined_date"], "%Y-%m-%d %H:%M:%S").strftime("%B %d, %Y")
        member_avatar = m["avatar"] if m["avatar"] in AVATAR_ICONS else DEFAULT_AVATAR
        member_name = m["display_name"] or m["name"]

        # Check if it's their birthday today
        birthday_badge = ""
        if m["birthday"]:
            try:
                # birthday is in format YYYY-MM-DD
                bday_month_day = m["birthday"][5:]  # Get MM-DD
                today_month_day = datetime.now().strftime("%m-%d")
                if bday_month_day == today_month_day:
                    birthday_badge = f'<span style="margin-left: 8px;"><i data-lucide="cake" class="icon"></i></span>'
            except:
                pass

        members_list += f"""
        <div class="event" style="padding: 12px;">
            <h3 style="margin: 0;">{avatar_icon(member_avatar)} {status_icon} {html.escape(member_name)}{badge}{birthday_badge}</h3>
            <p class="small" style="margin: 5px 0 0 0;">{status_text} • Joined {join_date}</p>
        </div>
        """

    user_display_name = member["display_name"] or member["name"]
    user_avatar = avatar_icon(member["avatar"], "sm")

    nav_html = '<div class="nav">'
    nav_html += f'<a href="/profile">{user_avatar}<strong>{html.escape(user_display_name)}</strong></a> | '
    nav_html += f'<a href="/dashboard">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> | '
    nav_html += f'<a href="/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> | '
    nav_html += f'<a href="/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> | '
    nav_html += f'<a href="/bookmarks">{icon("book-marked")}<span class="mobile-hide"> Bookmarks</span></a> | '
    if member["is_admin"]:
        nav_html += f'<a href="/admin">{icon("terminal")}<span class="mobile-hide"> Admin</span></a> | '
    nav_html += '<a href="/logout">Sign out</a> | '
    nav_html += '<a href="/help">?</a>'
    nav_html += '</div>'

    # Get current user status
    current_status = member["status"] or "available"

    content = f"""
    {nav_html}

    <h1>Members ({len(members)})</h1>

    <div class="event" style="background: #f9f9f9; margin-bottom: 20px;">
        <form method="POST" action="/update_status" style="display: flex; gap: 10px; align-items: center;">
            <select name="status" style="width: auto;">
                <option value="available" {"selected" if current_status == "available" else ""}>Available</option>
                <option value="away" {"selected" if current_status == "away" else ""}>Away</option>
                <option value="busy" {"selected" if current_status == "busy" else ""}>Busy</option>
            </select>
            <button type="submit">Update Status</button>
        </form>
    </div>

    <p class="hint"><i data-lucide="lightbulb" class="icon icon-sm"></i> Status icons: <span class="status-available"><i data-lucide="circle-dot" class="icon icon-sm"></i></span> available, <span class="status-away"><i data-lucide="moon" class="icon icon-sm"></i></span> away, <span class="status-busy"><i data-lucide="headphones" class="icon icon-sm"></i></span> busy</p>

    {members_list}
    """

    return render_html(content)


@app.post("/update_status")
async def update_status(request: Request, status: str = Form(...)):
    """Update member's status"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    # Validate status
    if status not in ["available", "away", "busy"]:
        return RedirectResponse(url="/members", status_code=303)

    with get_db() as db:
        db.execute("UPDATE members SET status = ? WHERE phone = ?", (status, phone))
        db.commit()

    return RedirectResponse(url="/members", status_code=303)


@app.get("/admin")
async def admin_panel(request: Request):
    """Admin panel"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        return RedirectResponse(url="/", status_code=303)

    with get_db() as db:
        member_count = db.execute("SELECT COUNT(*) as count FROM members").fetchone()["count"]
        event_count = db.execute(
            "SELECT COUNT(*) as count FROM events WHERE event_date > datetime('now')"
        ).fetchone()["count"]

        # Get all members with moderator status
        all_members = db.execute("""
            SELECT name, phone, joined_date, is_moderator, is_admin
            FROM members
            ORDER BY is_admin DESC, is_moderator DESC, joined_date DESC
        """).fetchall()

        members_html = "<table style='width: 100%; border-collapse: collapse;'>"
        members_html += "<tr style='background: #000; color: #fff;'>"
        members_html += "<th style='padding: 8px; text-align: left;'>Name</th>"
        members_html += "<th style='padding: 8px; text-align: left;'>Phone</th>"
        members_html += "<th style='padding: 8px; text-align: left;'>Role</th>"
        members_html += "<th style='padding: 8px; text-align: left;'>Joined</th>"
        members_html += "<th style='padding: 8px; text-align: left;'>Actions</th>"
        members_html += "</tr>"

        for m in all_members:
            role = "Admin" if m["is_admin"] else ("Moderator" if m["is_moderator"] else "Member")
            role_color = "#28a745" if m["is_admin"] else ("#007bff" if m["is_moderator"] else "#666")

            actions = ""
            if not m["is_admin"]:  # Can't demote admins
                if m["is_moderator"]:
                    actions = f'''
                    <form method="POST" action="/admin/demote_moderator/{m['phone']}" style="display: inline;">
                        <button type="submit" style="background: #666; color: white; padding: 4px 8px; font-size: 11px;">Remove Mod</button>
                    </form>
                    '''
                else:
                    actions = f'''
                    <form method="POST" action="/admin/promote_moderator/{m['phone']}" style="display: inline;">
                        <button type="submit" style="background: #007bff; color: white; padding: 4px 8px; font-size: 11px;">Make Mod</button>
                    </form>
                    '''

            members_html += f"<tr style='border-bottom: 1px solid #ddd;'>"
            members_html += f"<td style='padding: 8px;'>{m['name']}</td>"
            members_html += f"<td style='padding: 8px;'>{format_phone(m['phone'])}</td>"
            members_html += f"<td style='padding: 8px;'><span style='color: {role_color}; font-weight: bold;'>{role}</span></td>"
            members_html += f"<td style='padding: 8px;'>{m['joined_date'][:10]}</td>"
            members_html += f"<td style='padding: 8px;'>{actions}</td>"
            members_html += "</tr>"

        members_html += "</table>"

    nav_html = '<div class="nav">'
    nav_html += '<a href="/dashboard">← Back to dashboard</a>'
    nav_html += '</div>'

    content = f"""
    {nav_html}

    <h1>Admin Panel</h1>

    <div class="event">
        <h3>Stats</h3>
        <p>Total Members: {member_count} / {MAX_MEMBERS}</p>
        <p>Upcoming Events: {event_count}</p>
    </div>

    <form method="POST" action="/admin/create_event" style="margin: 30px 0; padding: 20px; border: 1px solid #000;">
        <input type="text" name="title" placeholder="Event title" required>
        <textarea name="description" placeholder="Description (optional)" rows="3"></textarea>
        <label style="display: block; margin-top: 10px;">Event Date:</label>
        <input type="date" name="event_date" required>
        <label style="display: block; margin-top: 10px;">Start Time (optional):</label>
        <input type="time" name="start_time">
        <label style="display: block; margin-top: 10px;">End Time (optional):</label>
        <input type="time" name="end_time">
        <input type="number" name="max_spots" placeholder="Max attendees (leave empty for unlimited)" min="1">
        <button type="submit">+ Create Event</button>
    </form>

    <form method="POST" action="/admin/create_poll" style="margin: 30px 0; padding: 20px; border: 1px solid #000;">
        <h3 style="margin-top: 0;">Create Poll</h3>
        <input type="text" name="question" placeholder="Poll question" required maxlength="200">
        <input type="text" name="option1" placeholder="Option 1" required maxlength="100">
        <input type="text" name="option2" placeholder="Option 2" required maxlength="100">
        <input type="text" name="option3" placeholder="Option 3 (optional)" maxlength="100">
        <input type="text" name="option4" placeholder="Option 4 (optional)" maxlength="100">
        <button type="submit">+ Create Poll</button>
    </form>

    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ccc;">
        <p class="small">Moderators can pin/unpin posts and delete posts/comments.</p>
        {members_html}
    </div>

    <div style="margin-top: 30px; padding: 20px; background: #f0f8ff; border-left: 4px solid #007bff;">
        <h3 style="margin-top: 0;"><i data-lucide="eye" class="icon"></i> View as Member</h3>
        <p class="small">See what the site looks like for regular members (hides admin controls).</p>
        <form method="POST" action="/admin/view_as_member">
            <button type="submit" style="background: #007bff;">Switch to Member View</button>
        </form>
    </div>
    """

    return render_html(content)


@app.post("/admin/create_event")
async def create_event(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    event_date: str = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    max_spots: Optional[int] = Form(None)
):
    """Create a new event"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/admin", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Convert empty strings to None for optional time fields
    start_time = start_time if start_time else None
    end_time = end_time if end_time else None

    with get_db() as db:
        db.execute(
            "INSERT INTO events (title, description, event_date, start_time, end_time, max_spots) VALUES (?, ?, ?, ?, ?, ?)",
            (title, description, event_date, start_time, end_time, max_spots)
        )
        db.commit()

    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/create_poll")
async def create_poll(
    request: Request,
    question: str = Form(...),
    option1: str = Form(...),
    option2: str = Form(...),
    option3: str = Form(""),
    option4: str = Form("")
):
    """Create a new poll"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/admin", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Create poll
    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO polls (question, created_by_phone) VALUES (?, ?)",
            (question, phone)
        )
        poll_id = cursor.lastrowid

        # Add options (at least 2 required)
        options = [option1, option2]
        if option3:
            options.append(option3)
        if option4:
            options.append(option4)

        for option_text in options:
            db.execute(
                "INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)",
                (poll_id, option_text)
            )

        db.commit()

    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/promote_moderator/{member_phone}")
async def promote_moderator(member_phone: str, request: Request):
    """Promote a member to moderator"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/admin", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        db.execute("UPDATE members SET is_moderator = 1 WHERE phone = ?", (member_phone,))
        db.commit()

        # Get member name for notification
        member = db.execute("SELECT name FROM members WHERE phone = ?", (member_phone,)).fetchone()
        if member:
            send_sms(member_phone, f"Hey {member['name']}! You've been promoted to Moderator in The Clubhouse. You can now pin posts and help manage the community.")

    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/demote_moderator/{member_phone}")
async def demote_moderator(member_phone: str, request: Request):
    """Demote a moderator to regular member"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/admin", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        db.execute("UPDATE members SET is_moderator = 0 WHERE phone = ?", (member_phone,))
        db.commit()

    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/view_as_member")
async def view_as_member(request: Request):
    """Toggle to member view mode"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    # Check admin status from database (not just ADMIN_PHONES env var)
    with get_db() as db:
        member = db.execute("SELECT is_admin FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member or not member["is_admin"]:
            return RedirectResponse(url="/", status_code=303)

    # Set the view mode cookie and redirect to dashboard
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="view_as_member",
        value="1",
        max_age=3600,  # 1 hour
        httponly=False  # Allow JS to read for toolbar UI
    )
    return response


@app.post("/admin/view_as_admin")
async def view_as_admin(request: Request):
    """Toggle back to admin view mode"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/", status_code=303)

    # Check admin status from database (not just ADMIN_PHONES env var)
    with get_db() as db:
        member = db.execute("SELECT is_admin FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member or not member["is_admin"]:
            return RedirectResponse(url="/", status_code=303)

    # Clear the view mode cookie and redirect to dashboard
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.delete_cookie("view_as_member")
    return response


def is_viewing_as_member(request: Request) -> bool:
    """Check if admin is currently viewing as member"""
    return request.cookies.get("view_as_member") == "1"


@app.get("/attendance/{event_id}")
async def attendance_page(event_id: int, request: Request):
    """Attendance tracking page for admins"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        # Get event details
        event = db.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,)
        ).fetchone()

        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        # Get all RSVPs with member info
        rsvps = db.execute("""
            SELECT r.phone, r.attended, m.name
            FROM rsvps r
            JOIN members m ON r.phone = m.phone
            WHERE r.event_id = ?
            ORDER BY m.name
        """, (event_id,)).fetchall()

        # Build attendees list
        attendees_html = ""
        attended_count = 0
        for rsvp in rsvps:
            if rsvp["attended"]:
                attended_count += 1

            checkbox_checked = "checked" if rsvp["attended"] else ""
            attendees_html += f"""
            <div style="padding: 10px; border-bottom: 1px solid #ccc;">
                <label style="cursor: pointer;">
                    <input
                        type="checkbox"
                        {checkbox_checked}
                        onchange="markAttendance('{rsvp['phone']}', this.checked)"
                    >
                    <strong>{rsvp['name']}</strong> <span class="small">({format_phone(rsvp['phone'])})</span>
                </label>
            </div>
            """

        if not attendees_html:
            attendees_html = "<p>No RSVPs for this event.</p>"

        # Format event time
        event_time_str = format_event_time(event['event_date'], event.get('start_time'), event.get('end_time'))

    nav_html = '<div class="nav"><a href="/dashboard">← Back to dashboard</a> | <a href="/admin">Admin</a></div>'

    content = f"""
    {nav_html}

    <h1>📋 Attendance: {event['title']}</h1>
    <p>{event_time_str}</p>
    <p><strong>{attended_count} of {len(rsvps)} attended</strong></p>

    <div id="attendees">
        {attendees_html}
    </div>

    <script>
        async function markAttendance(phone, attended) {{
            const response = await fetch('/attendance/{event_id}/mark', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                }},
                body: `phone=${{phone}}&attended=${{attended ? '1' : '0'}}`
            }});

            if (response.ok) {{
                // Reload to update count
                window.location.reload();
            }} else {{
                alert('Failed to update attendance');
            }}
        }}
    </script>
    """

    return render_html(content)


@app.post("/attendance/{event_id}/mark")
async def mark_attendance(
    event_id: int,
    request: Request,
    phone: str = Form(...),
    attended: str = Form(...)
):
    """Mark a member as attended/not attended"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        raise HTTPException(status_code=401)

    admin_phone = read_cookie(cookie)
    if not admin_phone or not is_admin(admin_phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        db.execute(
            "UPDATE rsvps SET attended = ? WHERE event_id = ? AND phone = ?",
            (1 if attended == "1" else 0, event_id, phone)
        )
        db.commit()

    return {"success": True}


@app.post("/events/{event_id}/upload_photo")
async def upload_event_photo(
    event_id: int,
    request: Request,
    photo: UploadFile = File(...),
    caption: str = Form("")
):
    """Upload a photo to an event (admin only)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        raise HTTPException(status_code=401)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Validate file type
    allowed_types = {"image/jpeg", "image/jpg", "image/png", "image/gif"}
    if photo.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and GIF images allowed")

    # Create unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_ext = photo.filename.split(".")[-1]
    filename = f"event_{event_id}_{timestamp}.{file_ext}"
    file_path = f"static/uploads/events/{filename}"

    # Save file
    with open(file_path, "wb") as f:
        content = await photo.read()
        f.write(content)

    # Save to database
    photo_url = f"/static/uploads/events/{filename}"
    with get_db() as db:
        db.execute(
            "INSERT INTO event_photos (event_id, photo_url, caption, uploaded_by_phone) VALUES (?, ?, ?, ?)",
            (event_id, photo_url, caption, phone)
        )
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
async def logout():
    """Sign out"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("clubhouse")
    return response


# ============ INFO PAGES ============

@app.get("/contact")
async def contact():
    """Contact information page"""
    email_html = ""
    if CONTACT_EMAIL:
        email_html = f'<p>Email us at: <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>'
    else:
        email_html = '<p class="small">Contact email not configured.</p>'

    content = f"""
    <h1>Contact Us</h1>

    <p>Having trouble with {SITE_NAME}? We're here to help.</p>

    <h2>Common Issues</h2>

    <p><strong>Didn't receive your SMS code?</strong></p>
    <ul>
        <li>Check your spam/blocked messages folder</li>
        <li>Make sure you entered the correct phone number</li>
        <li>Wait a minute and try again</li>
    </ul>

    <p><strong>Need to change your phone number?</strong></p>
    <p>Contact an admin to update your account.</p>

    <p><strong>Want to delete your account?</strong></p>
    <p>Email us and we'll remove your data within 30 days.</p>

    <h2>Get in Touch</h2>

    {email_html}

    <p><a href="/">← Back to home</a></p>
    """
    return render_html(content, f"Contact - {SITE_NAME}")


@app.get("/privacy")
async def privacy():
    """Privacy policy page"""
    email_link = f'<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>' if CONTACT_EMAIL else "the site administrator"

    content = f"""
    <h1>Privacy Policy</h1>

    <p class="small">Last updated: December 2024</p>

    <p>{SITE_NAME} is a small, invite-only community platform. We take your privacy seriously and collect only what's necessary to run the service.</p>

    <h2>What We Collect</h2>

    <p><strong>Phone Number</strong></p>
    <p>Your phone number is your identity on {SITE_NAME}. We use it to:</p>
    <ul>
        <li>Send you login verification codes via SMS</li>
        <li>Send you event reminders and community updates (if enabled)</li>
    </ul>

    <p><strong>Profile Information</strong></p>
    <p>Name, avatar, and any other info you choose to add to your profile.</p>

    <p><strong>Content You Create</strong></p>
    <p>Posts, comments, reactions, RSVPs, and other community activity.</p>

    <h2>What We Don't Do</h2>

    <ul>
        <li>We don't sell your data to anyone</li>
        <li>We don't show you ads</li>
        <li>We don't track you across other websites</li>
        <li>We don't share your phone number with other members (they only see your display name)</li>
    </ul>

    <h2>Data Storage</h2>

    <p>Your data is stored in a database on our server. We keep regular backups to prevent data loss.</p>

    <h2>Data Deletion</h2>

    <p>You can request deletion of your account and all associated data at any time. Contact {email_link} and we'll process your request within 30 days.</p>

    <h2>Cookies</h2>

    <p>We use a single cookie to keep you logged in. It contains a secure token linked to your account and expires after 7 days of inactivity.</p>

    <h2>Questions?</h2>

    <p>Contact {email_link} with any privacy concerns.</p>

    <p><a href="/">← Back to home</a></p>
    """
    return render_html(content, f"Privacy - {SITE_NAME}")


@app.get("/help")
async def help_page():
    """Help and FAQ page"""
    content = f"""
    <h1>How to use {SITE_NAME}</h1>

    <p>Welcome! Here's everything you need to know about using this community platform.</p>

    <h2>Getting Around</h2>

    <div class="event">
        <p><strong><i data-lucide="calendar" class="icon icon-sm"></i> Events</strong> - Your main dashboard. See the calendar and upcoming events.</p>
        <p><strong><i data-lucide="message-square" class="icon icon-sm"></i> Feed</strong> - Community message board where members share updates.</p>
        <p><strong><i data-lucide="users" class="icon icon-sm"></i> Members</strong> - See everyone in the community and their profiles.</p>
        <p><strong><i data-lucide="bell" class="icon icon-sm"></i> Notifications</strong> - Get notified when someone reacts to or comments on your posts.</p>
        <p><strong><i data-lucide="book-marked" class="icon icon-sm"></i> Bookmarks</strong> - Save posts to come back to later.</p>
    </div>

    <h2>What You Can Do</h2>

    <div class="event">
        <p><strong>RSVP to events</strong> - Click an event to see details and say you're coming.</p>
        <p><strong>Post updates</strong> - Share thoughts, questions, or announcements (500 characters max).</p>
        <p><strong>React</strong> - Show appreciation with thumbs-up, heart, laugh, celebrate, or fire icons</p>
        <p><strong>Comment on posts</strong> - Join conversations and reply to others.</p>
        <p><strong>Bookmark posts</strong> - Click the bookmark icon to save a post for later.</p>
        <p><strong>Invite new members</strong> - Generate invite codes to bring friends into the community.</p>
    </div>

    <h2>Your Profile</h2>

    <div class="event">
        <p><strong>Avatar</strong> - Pick an icon that appears next to your posts.</p>
        <p><strong>Display Name</strong> - The name others see (you can change it anytime).</p>
        <p><strong>Birthday</strong> - Optional! We'll wish you happy birthday on your special day.</p>
        <p><strong>Status</strong> - Let others know if you're available, away, or busy.</p>
    </div>

    <h2>Member Status Dots</h2>

    <div class="event">
        <p><span class="status-available"><i data-lucide="circle-dot" class="icon icon-sm"></i></span> <strong>Available</strong> - Open to chat</p>
        <p><span class="status-away"><i data-lucide="moon" class="icon icon-sm"></i></span> <strong>Away</strong> - Stepped out</p>
        <p><span class="status-busy"><i data-lucide="headphones" class="icon icon-sm"></i></span> <strong>Busy</strong> - Focused, don't disturb</p>
    </div>

    <h2>Roles</h2>

    <div class="event">
        <p><strong>Members</strong> - Post, react, comment, and invite new people.</p>
        <p><strong>Moderators</strong> - Can also delete posts and pin important updates.</p>
        <p><strong>Admins</strong> - Can create events, polls, and manage the community.</p>
    </div>

    <h2>Frequently Asked Questions</h2>

    <div class="event">
        <p><strong>How do I change my profile picture?</strong></p>
        <p class="small">Go to your profile (click your name in the nav) and pick a new avatar icon.</p>
    </div>

    <div class="event">
        <p><strong>How do I invite someone?</strong></p>
        <p class="small">On the Events page, scroll down to "Invite Someone" and generate a code. Share the code or send an SMS invite directly.</p>
    </div>

    <div class="event">
        <p><strong>What if I don't get the login text?</strong></p>
        <p class="small">Wait a minute and try again. Make sure you're entering your phone number correctly. If it keeps failing, contact an admin.</p>
    </div>

    <div class="event">
        <p><strong>Can others see my phone number?</strong></p>
        <p class="small">No! Other members only see your display name and avatar. Only admins can see phone numbers.</p>
    </div>

    <div class="event">
        <p><strong>How do I leave the community?</strong></p>
        <p class="small">Contact an admin and they can remove your account. You can also just stop logging in - your account won't bother anyone.</p>
    </div>

    <p style="margin-top: 30px;"><a href="/">← Back to home</a></p>
    """
    return render_html(content, f"Help - {SITE_NAME}")


# ============ PLAYGROUND (NO DATABASE) ============

def playground_nav(data: dict) -> str:
    """Generate navigation for playground pages"""
    member = data["members"][data["current_user"]]
    user_avatar = avatar_icon(member["avatar"], "sm")
    return f'''
    <div class="nav">
        <a href="/playground">{user_avatar}<strong>{html.escape(member["display_name"])}</strong></a> |
        <a href="/playground/events">{icon("calendar-days")}<span class="mobile-hide"> Events</span></a> |
        <a href="/playground/feed">{icon("message-square")}<span class="mobile-hide"> Feed</span></a> |
        <a href="/playground/members">{icon("book-heart")}<span class="mobile-hide"> Members</span></a> |
        <a href="/playground/reset" onclick="return confirm('Reset all playground data?')" style="color: #999;">{icon("refresh-cw")}<span class="mobile-hide"> Reset</span></a> |
        <a href="/" style="color: #999;">Exit Playground</a>
    </div>
    <div style="background: #f0f8ff; border: 1px dashed #007bff; padding: 8px 12px; margin-bottom: 20px; font-size: 12px; font-family: var(--font-mono);">
        <i data-lucide="flask-conical" class="icon icon-sm"></i> <strong>Playground Mode</strong> — Changes are temporary and only visible to you
    </div>
    '''

@app.get("/playground")
async def playground_home(request: Request):
    """Playground entry point"""
    session_id = get_playground_session_id(request)

    if not session_id:
        # New visitor - create session
        session_id = generate_playground_session()
        data = playground.get_session(session_id)

        content = f"""
        <h1>Welcome to the Playground</h1>

        <div class="event">
            <p>This is a <strong>fully functional sandbox</strong> where you can try everything:</p>
            <ul style="margin: 15px 0; padding-left: 20px;">
                <li>Create posts, react, and comment</li>
                <li>RSVP to events</li>
                <li>Vote in polls</li>
                <li>Browse members</li>
            </ul>
            <p><strong>Nothing you do here affects the real app.</strong> Your playground is private to you and resets when you click the reset button.</p>
        </div>

        <div style="margin: 30px 0;">
            <a href="/playground/feed"><button>Enter Playground</button></a>
        </div>

        <p class="small">You're signed in as <strong>You (Playground)</strong> with admin privileges so you can try all features.</p>

        <p style="margin-top: 30px;"><a href="/">← Back to main site</a></p>
        """

        response = render_html(content, "Playground - The Clubhouse")
        response.set_cookie("playground_session", session_id, max_age=86400, httponly=True)
        return response

    # Existing session - redirect to feed
    return RedirectResponse(url="/playground/feed", status_code=303)


@app.get("/playground/feed")
async def playground_feed(request: Request):
    """Playground feed - view and create posts"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    member = data["members"][data["current_user"]]

    # Build posts HTML
    posts_html = ""
    sorted_posts = sorted(data["posts"].values(), key=lambda p: (p["is_pinned"], p["posted_date"]), reverse=True)

    for post in sorted_posts:
        author = data["members"].get(post["phone"], {"display_name": "Unknown", "avatar": "user"})
        author_name = author.get("display_name") or author.get("name", "Unknown")
        author_avatar = avatar_icon(author.get("avatar", "user"), "sm")
        time_ago = format_relative_time(post["posted_date"])

        pinned_badge = '<span style="background: var(--color-success); color: white; padding: 2px 6px; font-size: 11px; border-radius: 3px; margin-right: 8px;">PINNED</span>' if post["is_pinned"] else ""

        # Get reactions for this post
        post_reactions = [r for r in data["reactions"] if r["post_id"] == post["id"]]
        reaction_counts = {}
        user_reacted = {}
        for r in post_reactions:
            reaction_counts[r["emoji"]] = reaction_counts.get(r["emoji"], 0) + 1
            if r["phone"] == data["current_user"]:
                user_reacted[r["emoji"]] = True

        reactions_html = f'<div class="reactions">'
        for emoji in REACTION_ICONS:
            count = reaction_counts.get(emoji, 0)
            active = "active" if emoji in user_reacted else ""
            count_display = f' <span class="count">{count}</span>' if count else ' <span class="count"></span>'
            reactions_html += f'<a href="/playground/react/{post["id"]}/{emoji}" class="reaction-btn {active}" data-emoji="{emoji}"><i data-lucide="{emoji}" class="icon icon-sm"></i>{count_display}</a>'
        reactions_html += '</div>'

        # Get comments for this post
        post_comments = [c for c in data["comments"].values() if c["post_id"] == post["id"]]
        comments_html = ""
        if post_comments:
            for comment in sorted(post_comments, key=lambda c: c["posted_date"]):
                c_author = data["members"].get(comment["phone"], {"display_name": "Unknown", "avatar": "user"})
                c_avatar = avatar_icon(c_author.get("avatar", "user"), "sm")
                c_name = c_author.get("display_name") or c_author.get("name", "Unknown")
                c_time = format_relative_time(comment["posted_date"])
                comments_html += f'''
                <div style="margin: 8px 0; padding: 8px; background: rgba(0,0,0,0.02);">
                    <div style="font-size: 12px; color: #666; margin-bottom: 4px;">
                        {c_avatar}<strong>{html.escape(c_name)}</strong> · {c_time}
                    </div>
                    <div style="font-size: 14px;">{html.escape(comment["content"])}</div>
                </div>
                '''

        # Comment form
        comment_form = f'''
        <details style="margin-top: 10px;">
            <summary>{icon("message-circle", "sm")} {len(post_comments)} comment{"s" if len(post_comments) != 1 else ""}</summary>
            <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--color-border-light);">
                {comments_html}
                <form method="POST" action="/playground/comment/{post["id"]}" style="margin-top: 10px;">
                    <input type="text" name="content" placeholder="Add a comment..." maxlength="280" required style="margin: 0;">
                    <button type="submit" style="margin-top: 5px;">Comment</button>
                </form>
            </div>
        </details>
        '''

        content_html = html.escape(post["content"])
        # Simple link detection
        import re
        content_html = re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank">\1</a>', content_html)

        posts_html += f'''
        <div class="post" id="post-{post["id"]}">
            <div class="post-header">
                <span>{author_avatar} <strong>{html.escape(author_name)}</strong></span>
                <span>{time_ago}</span>
            </div>
            <div class="post-content">{pinned_badge}{content_html}</div>
            {reactions_html}
            {comment_form}
        </div>
        '''

    # Build poll HTML
    polls_html = ""
    for poll in data["polls"].values():
        if poll["is_active"]:
            options = [o for o in data["poll_options"].values() if o["poll_id"] == poll["id"]]
            total_votes = sum(o["vote_count"] for o in options)
            user_vote = next((v for v in data["poll_votes"] if v["poll_id"] == poll["id"] and v["phone"] == data["current_user"]), None)

            options_html = ""
            for opt in options:
                pct = (opt["vote_count"] / total_votes * 100) if total_votes > 0 else 0
                checked = "checked disabled" if user_vote and user_vote["option_id"] == opt["id"] else ""
                disabled = "disabled" if user_vote else ""
                options_html += f'''
                <label style="display: block; margin: 10px 0; padding: 10px; border: 1px solid var(--color-border-light); cursor: pointer;">
                    <input type="radio" name="option_id" value="{opt["id"]}" {checked} {disabled}>
                    {html.escape(opt["option_text"])}
                    <span class="small" style="float: right;">{opt["vote_count"]} votes ({pct:.0f}%)</span>
                </label>
                '''

            if user_vote:
                polls_html += f'''
                <div class="event" style="background: #f9f9f9;">
                    <h3>{icon("bar-chart-2", "sm")} {html.escape(poll["question"])}</h3>
                    {options_html}
                    <p class="small">You voted · {total_votes} total votes</p>
                </div>
                '''
            else:
                polls_html += f'''
                <div class="event" style="background: #f9f9f9;">
                    <h3>{icon("bar-chart-2", "sm")} {html.escape(poll["question"])}</h3>
                    <form method="POST" action="/playground/vote/{poll["id"]}">
                        {options_html}
                        <button type="submit">Vote</button>
                    </form>
                </div>
                '''

    content = f"""
    {playground_nav(data)}

    <h1>Feed</h1>

    <form method="POST" action="/playground/post" style="margin-bottom: 30px;">
        <textarea name="content" placeholder="Share something with the community..." rows="3" maxlength="500" required></textarea>
        <button type="submit">Post</button>
    </form>

    {polls_html}
    {posts_html}
    """

    return render_html(content, "Feed - Playground")


@app.post("/playground/post")
async def playground_create_post(request: Request, content: str = Form(...)):
    """Create a post in the playground"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    post_id = data["counters"]["post_id"]
    data["counters"]["post_id"] += 1

    data["posts"][post_id] = {
        "id": post_id,
        "phone": data["current_user"],
        "content": content[:500],
        "posted_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_pinned": 0
    }

    return RedirectResponse(url="/playground/feed", status_code=303)


@app.get("/playground/react/{post_id}/{emoji}")
async def playground_react(post_id: int, emoji: str, request: Request):
    """Toggle reaction on a post"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    user = data["current_user"]

    # Check if already reacted with this emoji
    existing = next((i for i, r in enumerate(data["reactions"]) if r["post_id"] == post_id and r["phone"] == user and r["emoji"] == emoji), None)

    if existing is not None:
        # Remove reaction
        data["reactions"].pop(existing)
    else:
        # Add reaction
        data["reactions"].append({"post_id": post_id, "phone": user, "emoji": emoji})

    return RedirectResponse(url="/playground/feed", status_code=303)


@app.post("/playground/comment/{post_id}")
async def playground_comment(post_id: int, request: Request, content: str = Form(...)):
    """Add comment to a post"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    comment_id = data["counters"]["comment_id"]
    data["counters"]["comment_id"] += 1

    data["comments"][comment_id] = {
        "id": comment_id,
        "post_id": post_id,
        "phone": data["current_user"],
        "content": content[:280],
        "posted_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return RedirectResponse(url="/playground/feed", status_code=303)


@app.post("/playground/vote/{poll_id}")
async def playground_vote(poll_id: int, request: Request, option_id: int = Form(...)):
    """Vote in a poll"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    user = data["current_user"]

    # Check if already voted
    if not any(v for v in data["poll_votes"] if v["poll_id"] == poll_id and v["phone"] == user):
        data["poll_votes"].append({"poll_id": poll_id, "phone": user, "option_id": option_id})
        if option_id in data["poll_options"]:
            data["poll_options"][option_id]["vote_count"] += 1

    return RedirectResponse(url="/playground/feed", status_code=303)


@app.get("/playground/events")
async def playground_events(request: Request):
    """Playground events page"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    user = data["current_user"]

    events_html = ""
    for event in sorted(data["events"].values(), key=lambda e: e["event_date"]):
        if event["is_cancelled"]:
            continue

        rsvp_count = len([r for r in data["rsvps"] if r["event_id"] == event["id"]])
        user_rsvp = any(r for r in data["rsvps"] if r["event_id"] == event["id"] and r["phone"] == user)

        spots_text = ""
        if event["max_spots"]:
            spots_left = event["max_spots"] - rsvp_count
            spots_text = f'<span class="small">{spots_left} of {event["max_spots"]} spots left</span>'
        else:
            spots_text = f'<span class="small">{rsvp_count} attending</span>'

        if user_rsvp:
            button = f'<a href="/playground/unrsvp/{event["id"]}"><button style="background: #666;">Cancel RSVP</button></a>'
            badge = f' <span style="background: var(--color-success); color: white; padding: 2px 6px; font-size: 11px;">GOING</span>'
        else:
            if event["max_spots"] and rsvp_count >= event["max_spots"]:
                button = '<button disabled style="background: #ccc;">Full</button>'
            else:
                button = f'<a href="/playground/rsvp/{event["id"]}"><button>RSVP</button></a>'
            badge = ""

        time_str = format_event_time(event["event_date"], event.get("start_time"), event.get("end_time"))

        events_html += f'''
        <div class="event">
            <h3>{html.escape(event["title"])}{badge}</h3>
            <p>{html.escape(event["description"] or "")}</p>
            <p class="small">{icon("calendar-days", "sm")} {time_str}</p>
            {spots_text}
            {button}
        </div>
        '''

    content = f"""
    {playground_nav(data)}

    <h1>Events</h1>

    {events_html if events_html else '<p>No upcoming events.</p>'}
    """

    return render_html(content, "Events - Playground")


@app.get("/playground/rsvp/{event_id}")
async def playground_rsvp(event_id: int, request: Request):
    """RSVP to an event"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    user = data["current_user"]

    if not any(r for r in data["rsvps"] if r["event_id"] == event_id and r["phone"] == user):
        data["rsvps"].append({"event_id": event_id, "phone": user})

    return RedirectResponse(url="/playground/events", status_code=303)


@app.get("/playground/unrsvp/{event_id}")
async def playground_unrsvp(event_id: int, request: Request):
    """Cancel RSVP"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)
    user = data["current_user"]

    data["rsvps"] = [r for r in data["rsvps"] if not (r["event_id"] == event_id and r["phone"] == user)]

    return RedirectResponse(url="/playground/events", status_code=303)


@app.get("/playground/members")
async def playground_members(request: Request):
    """Playground members page"""
    session_id = get_playground_session_id(request)
    if not session_id:
        return RedirectResponse(url="/playground", status_code=303)

    data = playground.get_session(session_id)

    members_html = ""
    for m in sorted(data["members"].values(), key=lambda x: x["joined_date"], reverse=True):
        m_avatar = avatar_icon(m.get("avatar", "user"))
        m_name = m.get("display_name") or m.get("name", "Unknown")

        status = m.get("status", "available")
        status_icons = {
            "available": '<span class="status-available" title="Available"><i data-lucide="circle-dot" class="icon icon-sm"></i></span>',
            "away": '<span class="status-away" title="Away"><i data-lucide="moon" class="icon icon-sm"></i></span>',
            "busy": '<span class="status-busy" title="Busy"><i data-lucide="headphones" class="icon icon-sm"></i></span>'
        }
        status_icon = status_icons.get(status, status_icons["available"])

        badge = ""
        if m.get("is_admin"):
            badge = '<span style="background: #000; color: #fff; padding: 2px 6px; font-size: 11px; margin-left: 8px;">ADMIN</span>'
        elif m.get("is_moderator"):
            badge = '<span style="background: #666; color: #fff; padding: 2px 6px; font-size: 11px; margin-left: 8px;">MOD</span>'

        members_html += f'''
        <div class="event" style="padding: 12px;">
            <h3 style="margin: 0;">{m_avatar} {status_icon} {html.escape(m_name)}{badge}</h3>
            <p class="small" style="margin: 5px 0 0 0;">{status.capitalize()}</p>
        </div>
        '''

    content = f"""
    {playground_nav(data)}

    <h1>Members ({len(data["members"])})</h1>

    {members_html}
    """

    return render_html(content, "Members - Playground")


@app.get("/playground/reset")
async def playground_reset(request: Request):
    """Reset playground to fresh state"""
    session_id = get_playground_session_id(request)
    if session_id:
        playground.reset_session(session_id)

    return RedirectResponse(url="/playground/feed", status_code=303)


# ============ HEALTH CHECK ============

@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.
    Returns database status, member count, and app info.
    """
    try:
        with get_db() as db:
            member_count = db.execute("SELECT COUNT(*) as count FROM members").fetchone()["count"]
            event_count = db.execute("SELECT COUNT(*) as count FROM events WHERE is_cancelled = 0").fetchone()["count"]
            post_count = db.execute("SELECT COUNT(*) as count FROM posts").fetchone()["count"]
            db_status = "ok"
    except Exception as e:
        member_count = 0
        event_count = 0
        post_count = 0
        db_status = f"error: {str(e)}"

    return JSONResponse({
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "stats": {
            "members": member_count,
            "events": event_count,
            "posts": post_count,
            "max_members": MAX_MEMBERS
        },
        "timestamp": datetime.now().isoformat()
    })


# Run with: uvicorn app:app --reload --host 0.0.0.0 --port 8000
