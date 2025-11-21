"""
The Clubhouse - A simple, local-first community platform
Phone numbers only. No passwords. SQLite database. Pure simplicity.
"""

import sqlite3
import random
import os
import html
import re
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
                is_active BOOLEAN DEFAULT 1
            )
        """)

        # Events table
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                event_date TEXT NOT NULL,
                max_spots INTEGER,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                is_cancelled BOOLEAN DEFAULT 0
            )
        """)

        # RSVPs table
        db.execute("""
            CREATE TABLE IF NOT EXISTS rsvps (
                event_id INTEGER,
                phone TEXT,
                rsvp_date TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, phone)
            )
        """)

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
                posted_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

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
    if cookie and read_cookie(cookie):
        return RedirectResponse(url="/dashboard", status_code=303)

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

        is_admin_user = is_admin(phone)
        db.execute(
            "INSERT INTO members (phone, name, is_admin) VALUES (?, ?, ?)",
            (phone, name, 1 if is_admin_user else 0)
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
async def dashboard(request: Request):
    """Main page - events"""
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

        # Get upcoming events
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

            events_html += f"""
            <div class="event">
                <h3>{html.escape(event['title'])}</h3>
                <p>{html.escape(event['description']) if event['description'] else 'No description'}</p>
                <p>📅 {event['event_date']}</p>
                {spots_text}
                {button}
            </div>
            """

        if not events_html:
            events_html = "<p>No upcoming events. Check back soon!</p>"

        nav_html = '<div class="nav">'
        nav_html += f'<strong>{member["name"]}</strong> | '
        nav_html += '<a href="/dashboard">Events</a> | '
        nav_html += '<a href="/feed">Feed</a> | '
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
async def feed(request: Request):
    """Community feed"""
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

        # Get all posts
        posts = db.execute("""
            SELECT p.*, m.name
            FROM posts p
            JOIN members m ON p.phone = m.phone
            ORDER BY p.posted_date DESC
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
                    SELECT c.*, m.name
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

                        # Admin delete button
                        comment_delete = ""
                        if member["is_admin"]:
                            comment_delete = f'''
                            <form method="POST" action="/delete_comment/{comment['id']}" style="display: inline; margin-left: 5px;">
                                <button type="submit" onclick="return confirm('Delete?')" style="background: #d00; color: white; padding: 2px 6px; font-size: 11px;">🗑️</button>
                            </form>
                            '''

                        comments_html += f'''
                        <div style="margin: 8px 0; padding: 8px; background: rgba(0,0,0,0.02);">
                            <div style="font-size: 12px; color: #666; margin-bottom: 4px;">
                                <strong>{comment["name"]}</strong> · {comment_time}{comment_delete}
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

                # Admin delete post button
                delete_button = ""
                if member["is_admin"]:
                    delete_button = f'''
                    <form method="POST" action="/delete_post/{post['id']}" style="display: inline; margin-left: 10px;">
                        <button type="submit" onclick="return confirm('Delete post?')" style="background: #d00; color: white; padding: 4px 8px; font-size: 12px;">🗑️</button>
                    </form>
                    '''

                posts_html += f"""
                <div class="post">
                    <div class="post-header">
                        <span>{post["name"]}</span>
                        <span>{relative_time}{delete_button}</span>
                    </div>
                    <div class="post-content">{post_content}</div>
                    {reactions_html}
                    {comments_html}
                    {reply_form}
                </div>
                """
        else:
            posts_html = "<p>No posts yet. Be the first!</p>"

        nav_html = '<div class="nav">'
        nav_html += f'<strong>{member["name"]}</strong> | '
        nav_html += '<a href="/dashboard">Events</a> | '
        nav_html += '<a href="/feed">Feed</a> | '
        if member["is_admin"]:
            nav_html += '<a href="/admin">Admin</a> | '
        nav_html += '<a href="/logout">Sign out</a>'
        nav_html += '</div>'

        csrf_token = get_csrf_token(phone)

    content = f"""
    {nav_html}

    <h1>📝 Community Feed</h1>

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
            db.execute(
                "INSERT INTO reactions (post_id, phone, emoji) VALUES (?, ?, ?)",
                (post_id, phone, emoji)
            )

        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


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
        db.execute(
            "INSERT INTO comments (post_id, phone, content) VALUES (?, ?, ?)",
            (post_id, phone, content)
        )
        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


@app.post("/delete_post/{post_id}")
async def delete_post(post_id: int, request: Request):
    """Delete a post (admin only)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        db.execute("DELETE FROM reactions WHERE post_id = ?", (post_id,))
        db.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


@app.post("/delete_comment/{comment_id}")
async def delete_comment(comment_id: int, request: Request):
    """Delete a comment (admin only)"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/feed", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        db.commit()

    return RedirectResponse(url="/feed", status_code=303)


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

        recent_members = db.execute("""
            SELECT name, phone, joined_date
            FROM members
            ORDER BY joined_date DESC
            LIMIT 10
        """).fetchall()

        members_html = ""
        for m in recent_members:
            members_html += f"<li>{m['name']} - {format_phone(m['phone'])} - Joined {m['joined_date'][:10]}</li>"

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
        <input type="datetime-local" name="event_date" required>
        <input type="number" name="max_spots" placeholder="Max attendees (leave empty for unlimited)" min="1">
        <button type="submit">Create Event</button>
    </form>

    <h2>Recent Members</h2>
    <ul>{members_html}</ul>
    """

    return render_html(content)


@app.post("/admin/create_event")
async def create_event(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    event_date: str = Form(...),
    max_spots: Optional[int] = Form(None)
):
    """Create a new event"""
    cookie = request.cookies.get("clubhouse")
    if not cookie:
        return RedirectResponse(url="/admin", status_code=303)

    phone = read_cookie(cookie)
    if not phone or not is_admin(phone):
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as db:
        db.execute(
            "INSERT INTO events (title, description, event_date, max_spots) VALUES (?, ?, ?, ?)",
            (title, description, event_date, max_spots)
        )
        db.commit()

    return RedirectResponse(url="/admin", status_code=303)


@app.get("/logout")
async def logout():
    """Sign out"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("clubhouse")
    return response


# Run with: uvicorn app:app --reload --host 0.0.0.0 --port 8000
