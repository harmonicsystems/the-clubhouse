"""
The Clubhouse - A simple, local-first community platform
Phone numbers only. No passwords. SQLite database. Pure simplicity.
"""

import sqlite3
import random
import os
import html
import re
import calendar
from datetime import datetime, timedelta
from typing import Optional
from contextlib import contextmanager
import requests
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv
import hashlib

# Load environment variables
load_dotenv()

# Create our app
app = FastAPI(title="The Clubhouse", docs_url=None, redoc_url=None)

# Configuration
ADMIN_PHONES = os.getenv("ADMIN_PHONES", "").split(",")
TEXTBELT_KEY = os.getenv("TEXTBELT_KEY", "textbelt")
SECRET_SALT = os.getenv("SECRET_SALT", "change-me-please")
DATABASE_PATH = os.getenv("DATABASE_PATH", "clubhouse.db")
MAX_MEMBERS = 200

# In-memory storage
phone_codes = {}  # {phone: {"code": 123456, "created": datetime}}
rate_limits = {}  # {phone: {"attempts": 0, "reset_time": datetime}}
csrf_tokens = {}  # {phone: token}


# ============ DATABASE ============

@contextmanager
def get_db():
    """Open database, do stuff, close database"""
    conn = sqlite3.connect(DATABASE_PATH)
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

        # Add avatar emoji column
        try:
            db.execute("ALTER TABLE members ADD COLUMN avatar TEXT DEFAULT '👤'")
        except:
            pass  # Column already exists

        # Add birthday column
        try:
            db.execute("ALTER TABLE members ADD COLUMN birthday TEXT")
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

        db.commit()

    print(f"📚 Database ready at {DATABASE_PATH}")


# Run this when app starts
init_database()


# ============ HELPER FUNCTIONS ============

def clean_phone(phone: str) -> str:
    """Remove all non-numbers from phone"""
    return ''.join(c for c in phone if c.isdigit())


def format_phone(phone: str) -> str:
    """Make phone pretty for display"""
    if len(phone) == 10:
        return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
    return phone


def send_sms(phone: str, message: str) -> bool:
    """Send a text message"""
    try:
        response = requests.post('https://textbelt.com/text', {
            'phone': phone,
            'message': message,
            'key': TEXTBELT_KEY
        }, timeout=10)
        return response.json().get('success', False)
    except:
        print(f"📱 Failed to send SMS to {phone}")
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
    """Generate CSRF token for a user"""
    if phone not in csrf_tokens:
        csrf_tokens[phone] = hashlib.sha256(f"{phone}{SECRET_SALT}{datetime.now()}".encode()).hexdigest()[:16]
    return csrf_tokens[phone]


def verify_csrf_token(phone: str, token: str) -> bool:
    """Verify CSRF token"""
    return phone in csrf_tokens and csrf_tokens[phone] == token


def sanitize_content(content: str) -> str:
    """Escape HTML and make links clickable"""
    content = html.escape(content)
    # Make URLs clickable
    url_pattern = re.compile(r'(https?://[^\s]+)')
    content = url_pattern.sub(r'<a href="\1" target="_blank">\1</a>', content)
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
        <style>
            body {{
                max-width: 600px;
                margin: 50px auto;
                padding: 20px;
                font-family: 'Courier New', monospace;
                font-size: 16px;
                line-height: 1.6;
                color: #000;
                background: #fff;
            }}
            h1 {{
                font-size: 24px;
                margin-bottom: 30px;
                border-bottom: 2px solid #000;
                padding-bottom: 10px;
            }}
            h2 {{
                font-size: 18px;
                margin-top: 30px;
            }}
            input, textarea, select {{
                font-family: inherit;
                font-size: inherit;
                padding: 8px;
                margin: 10px 0;
                width: 100%;
                box-sizing: border-box;
                border: 1px solid #000;
            }}
            button {{
                font-family: inherit;
                font-size: inherit;
                padding: 10px 20px;
                background: #000;
                color: #fff;
                border: none;
                cursor: pointer;
                margin-top: 10px;
            }}
            button:hover {{
                background: #333;
            }}
            .event {{
                border: 1px solid #000;
                padding: 15px;
                margin: 15px 0;
            }}
            .post {{
                border: 1px solid #000;
                padding: 15px;
                margin: 15px 0;
            }}
            .post-header {{
                display: flex;
                justify-content: space-between;
                font-size: 14px;
                color: #666;
                margin-bottom: 10px;
            }}
            .post-content {{
                margin: 10px 0;
            }}
            .reactions {{
                margin-top: 10px;
                padding-top: 10px;
                border-top: 1px solid #eee;
            }}
            .reaction-btn {{
                display: inline-block;
                padding: 4px 8px;
                margin: 2px;
                border: 1px solid #ddd;
                text-decoration: none;
                border-radius: 4px;
            }}
            .reaction-btn:hover {{
                background: #f0f0f0;
            }}
            .reaction-btn.active {{
                background: #e0e0e0;
                border-color: #000;
            }}
            .small {{
                font-size: 12px;
                color: #666;
            }}
            .error {{
                color: red;
                margin: 10px 0;
            }}
            .success {{
                color: green;
                margin: 10px 0;
            }}
            a {{
                color: #000;
            }}
            .nav {{
                margin-bottom: 30px;
                padding-bottom: 10px;
                border-bottom: 1px solid #000;
            }}
            details {{
                margin-top: 10px;
            }}
            summary {{
                cursor: pointer;
                color: #666;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        {content}
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ============ ROUTES ============

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

    content = """
    <h1>🏠 The Clubhouse</h1>
    <p>A small, local community space.</p>

    <h2>Members Sign In</h2>
    <form method="POST" action="/send_code">
        <input type="tel" name="phone" placeholder="Your phone number" required>
        <button type="submit">Send me a code</button>
    </form>

    <h2>Have an Invite Code?</h2>
    <form method="POST" action="/join">
        <input type="text" name="invite_code" placeholder="STAR-123" required>
        <button type="submit">Join the clubhouse</button>
    </form>

    <p class="small">This is a private community. Invite codes only.</p>
    """
    return render_html(content)


@app.post("/send_code")
async def send_code(phone: str = Form(...)):
    """Send a login code to an existing member"""
    phone = clean_phone(phone)

    if not check_rate_limit(phone):
        content = """
        <h1>⏰ Slow down!</h1>
        <p class="error">Too many attempts. Try again in an hour.</p>
        <a href="/">← Back</a>
        """
        return render_html(content)

    with get_db() as db:
        member = db.execute("SELECT * FROM members WHERE phone = ?", (phone,)).fetchone()
        if not member:
            content = """
            <h1>🤔 Not Found</h1>
            <p>This phone number isn't registered.</p>
            <p>You need an invite code to join.</p>
            <a href="/">← Back</a>
            """
            return render_html(content)

    code = generate_code()
    phone_codes[phone] = {"code": code, "created": datetime.now()}

    message = f"Clubhouse login code: {code}\n\nThis code expires in 10 minutes."

    # Print code to console for testing
    print(f"\n📱 SMS CODE FOR {format_phone(phone)}: {code}\n")

    # Always show the code on screen for testing (remove this in production!)
    content = f"""
    <h1>📱 Code Generated!</h1>
    <p>Your login code for {format_phone(phone)} is:</p>
    <h2 style="background: #f0f0f0; padding: 20px; text-align: center; font-size: 32px;">
        {code}
    </h2>

    <form method="POST" action="/verify">
        <input type="hidden" name="phone" value="{phone}">
        <input type="text" name="code" placeholder="000000" maxlength="6" required value="{code}">
        <button type="submit">Verify</button>
    </form>

    <p class="small">Note: In production, this would be sent via SMS. For testing, the code is shown here.</p>
    <a href="/">← Back</a>
    """

    # Still try to send SMS in background
    send_sms(phone, message)

    return render_html(content)


@app.post("/verify")
async def verify(phone: str = Form(...), code: str = Form(...)):
    """Check if the code is correct"""
    phone = clean_phone(phone)
    clean_old_codes()

    if phone in phone_codes and phone_codes[phone]["code"] == code:
        del phone_codes[phone]
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            key="clubhouse",
            value=make_cookie(phone),
            max_age=604800,  # 7 days
            httponly=True
        )
        return response
    else:
        content = """
        <h1>❌ Wrong Code</h1>
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
            <h1>🚫 Invalid Code</h1>
            <p>That invite code doesn't work.</p>
            <a href="/">← Back</a>
            """
            return render_html(content)

        member_count = db.execute("SELECT COUNT(*) as count FROM members").fetchone()["count"]
        if member_count >= MAX_MEMBERS:
            content = f"""
            <h1>🏠 We're Full!</h1>
            <p>The clubhouse has reached {MAX_MEMBERS} members.</p>
            <a href="/">← Back</a>
            """
            return render_html(content)

    content = f"""
    <h1>🎉 Welcome!</h1>
    <p>Your invite code <strong>{invite_code}</strong> is valid!</p>

    <form method="POST" action="/register">
        <input type="hidden" name="invite_code" value="{invite_code}">
        <input type="text" name="name" placeholder="Your first name" required>
        <input type="tel" name="phone" placeholder="Your phone number" required>
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
            <h1>📱 Already Registered</h1>
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

    message = f"Welcome to The Clubhouse, {name}! 🏠"
    send_sms(phone, message)

    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="clubhouse",
        value=make_cookie(phone),
        max_age=604800,
        httponly=True
    )
    return response


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
                border-collapse: collapse;
                margin: 20px 0;
                font-size: 14px;
                table-layout: fixed;
            }
            .calendar th {
                background: #000;
                color: #fff;
                padding: 10px;
                text-align: center;
                font-weight: normal;
            }
            .calendar td {
                border: 1px solid #000;
                padding: 6px;
                vertical-align: top;
                height: 80px;
                width: 14.28%;
                overflow: hidden;
            }
            .calendar td.empty {
                background: #f5f5f5;
            }
            .day-number {
                font-weight: bold;
                margin-bottom: 4px;
                font-size: 13px;
            }
            .calendar-event {
                font-size: 10px;
                padding: 2px 4px;
                margin: 2px 0;
                background: #f0f0f0;
                border-left: 3px solid #000;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                line-height: 1.2;
                display: block;
                text-decoration: none;
                color: #000;
            }
            .calendar-event:hover {
                background: #e0e0e0;
                cursor: pointer;
            }
            .calendar-event.attending {
                background: #d4edda;
                border-left-color: #28a745;
            }
            .today {
                background: #fffacd;
            }
            .calendar-nav {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin: 10px 0;
            }
            .calendar-nav button {
                padding: 8px 16px;
                background: #000;
                color: #fff;
                border: none;
                cursor: pointer;
            }
            .calendar-nav button:hover {
                background: #333;
            }
        </style>
        """

        calendar_html = f"""
        {calendar_css}
        <div class="calendar-nav">
            <a href="/dashboard?year={prev_year}&month={prev_month}"><button>← {calendar.month_name[prev_month]}</button></a>
            <h2>📅 {month_name} {year}</h2>
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

                            # Format time display for calendar
                            if event["start_time"]:
                                start = datetime.strptime(event["start_time"], "%H:%M").strftime("%I:%M%p").lstrip("0")
                                if event["end_time"]:
                                    end = datetime.strptime(event["end_time"], "%H:%M").strftime("%I:%M%p").lstrip("0")
                                    event_time = f"{start}-{end}"
                                else:
                                    event_time = start
                            else:
                                event_time = "All day"

                            calendar_html += f'<a href="#event-{event["id"]}" class="calendar-event {attending_class}" title="{html.escape(event["title"])}">{event_time} {html.escape(event["title"])}</a>'

                    calendar_html += '</td>'
            calendar_html += "</tr>"

        calendar_html += """
            </tbody>
        </table>
        <p class="small">Events you're attending are highlighted in green. Today is highlighted in yellow.</p>
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

            events_html += f"""
            <div class="event" id="event-{event['id']}">
                <h3>{html.escape(event['title'])}</h3>
                <p>{html.escape(event['description']) if event['description'] else 'No description'}</p>
                <p>📅 {event_time_str}</p>
                {spots_text}
                {button}
                {attendance_link}
            </div>
            """

        if not events_html:
            events_html = "<p>No upcoming events. Check back soon!</p>"

        # Get unread notification count
        unread_count = get_unread_count(phone)
        notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

        user_avatar = member["avatar"] or "👤"
        user_display_name = member["display_name"] or member["name"]

        nav_html = '<div class="nav">'
        nav_html += f'<a href="/profile"><span style="font-size: 16px; margin-right: 4px;">{user_avatar}</span><strong>{html.escape(user_display_name)}</strong></a> | '
        nav_html += '<a href="/dashboard">Events</a> | '
        nav_html += '<a href="/feed">Feed</a> | '
        nav_html += '<a href="/members">Members</a> | '
        nav_html += f'<a href="/notifications">🔔 Notifications{notif_badge}</a> | '
        nav_html += '<a href="/bookmarks">🔖 Bookmarks</a> | '
        if member["is_admin"]:
            nav_html += '<a href="/admin">Admin</a> | '
        nav_html += '<a href="/logout">Sign out</a>'
        nav_html += '</div>'

        invite_html = ""
        if member["is_admin"]:
            invite_html = """
            <h2>Invite Someone</h2>
            <form method="POST" action="/create_invite">
                <button type="submit">Generate Invite Code</button>
            </form>
            """

    content = f"""
    {nav_html}

    <h1>🏠 The Clubhouse</h1>

    {calendar_html}

    <h2>Upcoming Events</h2>
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

            message = f"You're confirmed for: {event['title']}\n📅 {event['event_date']}"
            send_sms(phone, message)

    return RedirectResponse(url="/dashboard", status_code=303)


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

    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/create_invite")
async def create_invite(request: Request):
    """Generate invite code"""
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

    content = f"""
    <h1>🎟️ Invite Code Created!</h1>

    <p>Share this code with someone you'd like to invite:</p>

    <h2 style="background: #f0f0f0; padding: 20px; text-align: center;">
        {code}
    </h2>

    <p>This code can only be used once.</p>

    <a href="/dashboard">← Back to dashboard</a>
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

                reactions_html = '<div class="reactions">'
                for reaction in reactions:
                    active_class = "active" if reaction["user_reacted"] else ""
                    reactions_html += f'<a href="/react/{post["id"]}/{reaction["emoji"]}" class="reaction-btn {active_class}">{reaction["emoji"]} {reaction["count"]}</a>'

                # Quick reaction buttons
                quick_emojis = ["👍", "❤️", "😂", "🎉", "🔥"]
                existing_emojis = [r["emoji"] for r in reactions]
                for emoji in quick_emojis:
                    if emoji not in existing_emojis:
                        reactions_html += f'<a href="/react/{post["id"]}/{emoji}" class="reaction-btn">{emoji}</a>'

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
                        if is_moderator_or_admin(member):
                            comment_delete = f'''
                            <form method="POST" action="/delete_comment/{comment['id']}" style="display: inline; margin-left: 5px;">
                                <button type="submit" onclick="return confirm('Delete?')" style="background: #d00; color: white; padding: 2px 6px; font-size: 11px;">🗑️</button>
                            </form>
                            '''

                        comment_avatar = comment["avatar"] or "👤"
                        comment_name = comment["display_name"] or comment["name"]

                        comments_html += f'''
                        <div style="margin: 8px 0; padding: 8px; background: rgba(0,0,0,0.02);">
                            <div style="font-size: 12px; color: #666; margin-bottom: 4px;">
                                <span style="font-size: 16px; margin-right: 4px;">{comment_avatar}</span><strong>{html.escape(comment_name)}</strong> · {comment_time}{comment_delete}
                            </div>
                            <div style="font-size: 14px;">{comment_content}</div>
                        </div>
                        '''
                    comments_html += '</div>'

                # Reply form
                csrf_token = get_csrf_token(phone)
                reply_form = f'''
                <details style="margin-top: 10px;">
                    <summary>💬 Reply ({len(comments)})</summary>
                    <form method="POST" action="/reply/{post['id']}" style="margin-top: 8px;">
                        <input type="hidden" name="csrf_token" value="{csrf_token}">
                        <textarea name="content" placeholder="Write a reply..." rows="2" required maxlength="300" style="width: 100%; font-family: inherit; font-size: 14px; padding: 8px;"></textarea>
                        <button type="submit" style="padding: 6px 12px; font-size: 13px;">Post Reply</button>
                    </form>
                </details>
                '''

                # Moderator/Admin controls
                mod_controls = ""
                if is_moderator_or_admin(member):
                    pin_button = ""
                    if post["is_pinned"]:
                        pin_button = f'''
                        <form method="POST" action="/unpin_post/{post['id']}" style="display: inline; margin-left: 5px;">
                            <button type="submit" style="background: #666; color: white; padding: 4px 8px; font-size: 12px;">📌 Unpin</button>
                        </form>
                        '''
                    else:
                        pin_button = f'''
                        <form method="POST" action="/pin_post/{post['id']}" style="display: inline; margin-left: 5px;">
                            <button type="submit" style="background: #333; color: white; padding: 4px 8px; font-size: 12px;">📌 Pin</button>
                        </form>
                        '''

                    delete_button = f'''
                    <form method="POST" action="/delete_post/{post['id']}" style="display: inline; margin-left: 5px;">
                        <button type="submit" onclick="return confirm('Delete post?')" style="background: #d00; color: white; padding: 4px 8px; font-size: 12px;">🗑️</button>
                    </form>
                    '''
                    mod_controls = pin_button + delete_button

                pinned_badge = ""
                if post["is_pinned"]:
                    pinned_badge = '<span style="background: #28a745; color: white; padding: 2px 6px; font-size: 11px; border-radius: 3px; margin-right: 8px;">📌 PINNED</span>'

                # Check if bookmarked
                is_bookmarked = db.execute(
                    "SELECT 1 FROM bookmarks WHERE phone = ? AND post_id = ?",
                    (phone, post["id"])
                ).fetchone()

                bookmark_link = f'<a href="/bookmark/{post["id"]}" style="margin-left: 10px;">{"🔖" if is_bookmarked else "🔗"} {"Saved" if is_bookmarked else "Save"}</a>'

                # Get display name and avatar
                post_avatar = post["avatar"] or "👤"
                post_name = post["display_name"] or post["name"]

                posts_html += f"""
                <div class="post" id="post-{post['id']}" style="{'border: 2px solid #28a745;' if post['is_pinned'] else ''}">
                    <div class="post-header">
                        <span><span style="font-size: 20px; margin-right: 6px;">{post_avatar}</span>{pinned_badge}{html.escape(post_name)}</span>
                        <span>{relative_time}{bookmark_link}{mod_controls}</span>
                    </div>
                    <div class="post-content">{post_content}</div>
                    {reactions_html}
                    {comments_html}
                    {reply_form}
                </div>
                """
        else:
            posts_html = "<p>No posts yet. Be the first!</p>"

        # Get unread notification count
        unread_count = get_unread_count(phone)
        notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

        user_avatar = member["avatar"] or "👤"
        user_display_name = member["display_name"] or member["name"]

        nav_html = '<div class="nav">'
        nav_html += f'<a href="/profile"><span style="font-size: 16px; margin-right: 4px;">{user_avatar}</span><strong>{html.escape(user_display_name)}</strong></a> | '
        nav_html += '<a href="/dashboard">Events</a> | '
        nav_html += '<a href="/feed">Feed</a> | '
        nav_html += '<a href="/members">Members</a> | '
        nav_html += f'<a href="/notifications">🔔 Notifications{notif_badge}</a> | '
        nav_html += '<a href="/bookmarks">🔖 Bookmarks</a> | '
        if member["is_admin"]:
            nav_html += '<a href="/admin">Admin</a> | '
        nav_html += '<a href="/logout">Sign out</a>'
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

    <h1>📝 Community Feed</h1>

    {search_form}

    <h2>Share an Update</h2>
    <form method="POST" action="/post">
        <input type="hidden" name="csrf_token" value="{csrf_token}">
        <textarea name="content" placeholder="What's on your mind?" rows="3" required maxlength="500"></textarea>
        <p class="small">500 characters max</p>
        <button type="submit">Post</button>
    </form>

    <h2>Recent Posts</h2>
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


@app.get("/react/{post_id}/{emoji}")
async def react_to_post(post_id: int, emoji: str, request: Request):
    """Add or remove a reaction"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone:
        return RedirectResponse(url="/feed", status_code=303)

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

            # Create notification for post author (only when adding reaction, not removing)
            if post:
                create_notification(
                    post["phone"],
                    phone,
                    "reaction",
                    f"{reactor_name} reacted {emoji} to your post",
                    post_id
                )

        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


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

    # Get referrer to redirect back
    referer = request.headers.get("referer", "/feed")
    return RedirectResponse(url=referer, status_code=303)


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
                post_avatar = post["avatar"] or "👤"
                post_name = post["display_name"] or post["name"]

                posts_html += f"""
                <div class="post" id="post-{post['id']}">
                    <div class="post-header">
                        <span><span style="font-size: 20px; margin-right: 6px;">{post_avatar}</span>{html.escape(post_name)}</span>
                        <span>{relative_time} · <a href="/bookmark/{post['id']}">🔖 Remove</a></span>
                    </div>
                    <div class="post-content">{post_content}</div>
                    <p class="small"><a href="/feed#post-{post['id']}">View on feed →</a></p>
                </div>
                """
        else:
            posts_html = "<p>No bookmarks yet. Bookmark posts from the feed to save them here!</p>"

        # Get unread notification count
        unread_count = get_unread_count(phone)
        notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

        user_avatar = member["avatar"] or "👤"
        user_display_name = member["display_name"] or member["name"]

        nav_html = '<div class="nav">'
        nav_html += f'<a href="/profile"><span style="font-size: 16px; margin-right: 4px;">{user_avatar}</span><strong>{html.escape(user_display_name)}</strong></a> | '
        nav_html += '<a href="/dashboard">Events</a> | '
        nav_html += '<a href="/feed">Feed</a> | '
        nav_html += '<a href="/members">Members</a> | '
        nav_html += f'<a href="/notifications">🔔 Notifications{notif_badge}</a> | '
        nav_html += '<a href="/bookmarks">🔖 Bookmarks</a> | '
        nav_html += '<a href="/bookmarks">🔖 Bookmarks</a> | '
        if member["is_admin"]:
            nav_html += '<a href="/admin">Admin</a> | '
        nav_html += '<a href="/logout">Sign out</a>'
        nav_html += '</div>'

    content = f"""
    {nav_html}

    <h1>🔖 Your Bookmarks</h1>
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

    return RedirectResponse(url="/feed", status_code=303)


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

    return RedirectResponse(url="/feed", status_code=303)


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

    return RedirectResponse(url="/feed", status_code=303)


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
            actor_avatar = n["avatar"] or "👤"
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
                <p><span style="font-size: 20px; margin-right: 6px;">{actor_avatar}</span><strong>{html.escape(n["message"])}</strong>{link}</p>
                <p class="small">{time_ago}</p>
            </div>
            """
    else:
        notifs_html = "<p>No notifications yet. You'll see updates here when someone interacts with your posts!</p>"

    # Get unread notification count
    unread_count = 0  # Just marked all as read
    notif_badge = ''

    user_avatar = member["avatar"] or "👤"
    user_display_name = member["display_name"] or member["name"]

    nav_html = '<div class="nav">'
    nav_html += f'<a href="/profile"><span style="font-size: 16px; margin-right: 4px;">{user_avatar}</span><strong>{html.escape(user_display_name)}</strong></a> | '
    nav_html += '<a href="/dashboard">Events</a> | '
    nav_html += '<a href="/feed">Feed</a> | '
    nav_html += '<a href="/members">Members</a> | '
    nav_html += f'<a href="/notifications">🔔 Notifications{notif_badge}</a> | '
    if member["is_admin"]:
        nav_html += '<a href="/admin">Admin</a> | '
    nav_html += '<a href="/logout">Sign out</a>'
    nav_html += '</div>'

    content = f"""
    {nav_html}

    <h1>🔔 Notifications</h1>

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
    avatar = member["avatar"] or "👤"
    birthday = member["birthday"] or ""

    # Popular emoji choices
    emoji_options = ["👤", "😀", "😎", "🤓", "🥳", "🤠", "👻", "🤖", "👽", "🦄", "🐱", "🐶", "🐼", "🦊", "🦁", "🐯", "🐻", "🐨", "🐸", "🦉", "🌟", "⭐", "✨", "🔥", "💎", "🎨", "🎭", "🎪", "🎯", "🎲"]

    emoji_picker = '<div style="display: grid; grid-template-columns: repeat(10, 1fr); gap: 5px; max-width: 400px;">'
    for emoji in emoji_options:
        emoji_picker += f'<button type="button" onclick="document.getElementById(\'avatar-input\').value=\'{emoji}\'; document.getElementById(\'current-avatar\').textContent=\'{emoji}\'" style="font-size: 24px; padding: 8px; cursor: pointer;">{emoji}</button>'
    emoji_picker += '</div>'

    # Get unread notification count
    unread_count = get_unread_count(phone)
    notif_badge = f' <span style="background: #e74c3c; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 10px;">{unread_count}</span>' if unread_count > 0 else ''

    nav_html = '<div class="nav">'
    nav_html += f'<a href="/profile"><strong>{member["name"]}</strong></a> | '
    nav_html += '<a href="/dashboard">Events</a> | '
    nav_html += '<a href="/feed">Feed</a> | '
    nav_html += '<a href="/members">Members</a> | '
    nav_html += f'<a href="/notifications">🔔 Notifications{notif_badge}</a> | '
    if member["is_admin"]:
        nav_html += '<a href="/admin">Admin</a> | '
    nav_html += '<a href="/logout">Sign out</a>'
    nav_html += '</div>'

    content = f"""
    {nav_html}

    <h1>👤 Profile</h1>

    <div class="event">
        <h3>Your Info</h3>
        <p><strong>Avatar:</strong> <span style="font-size: 48px;">{avatar}</span></p>
        <p><strong>Handle:</strong> @{html.escape(handle)}</p>
        <p><strong>Display Name:</strong> {html.escape(display_name)}</p>
        <p><strong>Original Name:</strong> {html.escape(member["name"])}</p>
        <p><strong>Phone:</strong> {format_phone(phone)}</p>
        <p><strong>Joined:</strong> {member["joined_date"][:10]}</p>
        <p><strong>Birthday:</strong> {birthday if birthday else "Not set"}</p>
    </div>

    <div class="event">
        <h3>📸 Pick Your Avatar</h3>
        <p>Choose an emoji to represent you!</p>
        <form method="POST" action="/update_profile">
            <p>Current: <span id="current-avatar" style="font-size: 48px;">{avatar}</span></p>
            {emoji_picker}
            <input type="hidden" id="avatar-input" name="avatar" value="{avatar}">
            <button type="submit" style="margin-top: 10px;">Save Avatar</button>
        </form>
    </div>

    <div class="event">
        <h3>✏️ Edit Display Name</h3>
        <p>This is the name others see. You can change it anytime!</p>
        <form method="POST" action="/update_display_name">
            <input type="text" name="display_name" value="{html.escape(display_name)}" placeholder="Display name" required maxlength="50">
            <button type="submit">Update Display Name</button>
        </form>
    </div>

    <div class="event">
        <h3>🎂 Birthday (Optional)</h3>
        <p>We'll wish you happy birthday and show a badge on your special day!</p>
        <form method="POST" action="/update_birthday">
            <input type="date" name="birthday" value="{birthday}">
            <button type="submit">Save Birthday</button>
        </form>
    </div>

    <p class="small">💡 Only admins can change handles. Contact an admin if you need your handle changed.</p>
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

        # Status indicator
        status = m["status"] or "available"
        status_emoji = {
            "available": "🟢",
            "away": "🟡",
            "busy": "🔴"
        }.get(status, "🟢")
        status_text = status.capitalize()

        # Member card
        join_date = datetime.strptime(m["joined_date"], "%Y-%m-%d %H:%M:%S").strftime("%B %d, %Y")
        member_avatar = m["avatar"] or "👤"
        member_name = m["display_name"] or m["name"]

        # Check if it's their birthday today
        birthday_badge = ""
        if m["birthday"]:
            try:
                # birthday is in format YYYY-MM-DD
                bday_month_day = m["birthday"][5:]  # Get MM-DD
                today_month_day = datetime.now().strftime("%m-%d")
                if bday_month_day == today_month_day:
                    birthday_badge = '<span style="font-size: 20px; margin-left: 8px;">🎂</span>'
            except:
                pass

        members_list += f"""
        <div class="event" style="padding: 12px;">
            <h3 style="margin: 0;"><span style="font-size: 24px; margin-right: 8px;">{member_avatar}</span>{status_emoji} {html.escape(member_name)}{badge}{birthday_badge}</h3>
            <p class="small" style="margin: 5px 0 0 0;">{status_text} • Joined {join_date}</p>
        </div>
        """

    user_avatar = member["avatar"] or "👤"
    user_display_name = member["display_name"] or member["name"]

    nav_html = '<div class="nav">'
    nav_html += f'<a href="/profile"><span style="font-size: 16px; margin-right: 4px;">{user_avatar}</span><strong>{html.escape(user_display_name)}</strong></a> | '
    nav_html += '<a href="/dashboard">Events</a> | '
    nav_html += '<a href="/feed">Feed</a> | '
    nav_html += '<a href="/members">Members</a> | '
    nav_html += '<a href="/bookmarks">🔖 Bookmarks</a> | '
    if member["is_admin"]:
        nav_html += '<a href="/admin">Admin</a> | '
    nav_html += '<a href="/logout">Sign out</a>'
    nav_html += '</div>'

    # Get current user status
    current_status = member["status"] or "available"

    content = f"""
    {nav_html}

    <h1>👥 Members ({len(members)})</h1>

    <div class="event" style="background: #f9f9f9; margin-bottom: 20px;">
        <h3>Your Status</h3>
        <form method="POST" action="/update_status" style="display: flex; gap: 10px; align-items: center;">
            <select name="status" style="width: auto;">
                <option value="available" {"selected" if current_status == "available" else ""}>🟢 Available</option>
                <option value="away" {"selected" if current_status == "away" else ""}>🟡 Away</option>
                <option value="busy" {"selected" if current_status == "busy" else ""}>🔴 Busy</option>
            </select>
            <button type="submit">Update Status</button>
        </form>
    </div>

    <h2>Who's Around?</h2>

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

    <h1>🔧 Admin Panel</h1>

    <div class="event">
        <h3>Stats</h3>
        <p>Total Members: {member_count} / {MAX_MEMBERS}</p>
        <p>Upcoming Events: {event_count}</p>
    </div>

    <h2>Create New Event</h2>
    <form method="POST" action="/admin/create_event">
        <input type="text" name="title" placeholder="Event title" required>
        <textarea name="description" placeholder="Description (optional)" rows="3"></textarea>
        <label style="display: block; margin-top: 10px;">Event Date:</label>
        <input type="date" name="event_date" required>
        <label style="display: block; margin-top: 10px;">Start Time (optional):</label>
        <input type="time" name="start_time">
        <label style="display: block; margin-top: 10px;">End Time (optional):</label>
        <input type="time" name="end_time">
        <input type="number" name="max_spots" placeholder="Max attendees (leave empty for unlimited)" min="1">
        <button type="submit">Create Event</button>
    </form>

    <h2>Manage Members & Moderators</h2>
    <p class="small">Moderators can pin/unpin posts and delete posts/comments.</p>
    {members_html}
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
            send_sms(member_phone, f"Hey {member['name']}! You've been promoted to Moderator in The Clubhouse. You can now pin posts and help manage the community. 🎉")

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
    <p>📅 {event_time_str}</p>
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


@app.get("/logout")
async def logout():
    """Sign out"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("clubhouse")
    return response


# Run with: uvicorn app:app --reload --host 0.0.0.0 --port 8000
