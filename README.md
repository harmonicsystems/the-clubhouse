# The Clubhouse 🏠

A simple, local-first community platform for 50-200 people. Phone numbers only. No passwords. Pure simplicity.

## Philosophy

- **Phone numbers as identity** - SMS verification, no passwords
- **SQLite database** - Just a file on disk
- **Everything in one file** - The entire app is in `app.py` (1,169 lines)
- **No JavaScript needed** - Pure HTML forms
- **Limited membership** - Maximum 200 members
- **Invite codes required** - No public signups

## Features

✅ **SMS Authentication** - Login with phone number verification codes
✅ **Events** - Create events, RSVP, track attendees
✅ **Community Feed** - Post updates, see what's happening
✅ **Reactions** - React to posts with emojis (👍 ❤️ 😂 🎉 🔥)
✅ **Comments** - Reply to posts with threaded comments
✅ **Invite System** - Members generate one-time invite codes
✅ **Admin Panel** - Create events, manage community

## Quick Start

1. **Install dependencies**
```bash
pip install -r requirements.txt
```

2. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your admin phone number and settings
```

3. **Run the server**
```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

4. **Visit** http://localhost:8000

## Environment Variables

Edit `.env` with your settings:

- `ADMIN_PHONES` - Comma-separated admin phone numbers (e.g., `+15551234567`)
- `TEXTBELT_KEY` - Textbelt API key (`textbelt` for 1 free/day, or your paid key)
- `SECRET_SALT` - Random string for cookie signing (change from default!)
- `DATABASE_PATH` - SQLite database file path (default: `clubhouse.db`)

## Database Management

SQLite makes everything simple:

```bash
# Open database
sqlite3 clubhouse.db

# See all members
SELECT * FROM members;

# Make someone admin
UPDATE members SET is_admin = 1 WHERE phone = '5551234567';

# See all events
SELECT * FROM events;

# See all posts
SELECT * FROM posts;
```

## Deployment

### Quick Deploy (Ubuntu/Debian VPS)

1. Get a $5/month VPS (DigitalOcean, Linode, Hetzner, etc.)
2. Install Python 3.9+
3. Run the deploy script:

```bash
chmod +x deploy.sh
./deploy.sh
```

### Manual Deployment

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

# Create app directory
sudo mkdir -p /opt/clubhouse
cd /opt/clubhouse

# Copy files
sudo cp app.py requirements.txt .env ./

# Install packages
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run with systemd (see deploy.sh for full setup)
```

## Costs

Running your own social network is cheap:

- **Server**: $5/month (VPS)
- **SMS**: ~$10/month at 1¢ per text (100 texts)
- **Domain**: $12/year (optional)

**Total: ~$16/month** for your own private community platform

## Security

- SMS-based authentication (no passwords to leak)
- Cookie-based sessions with HMAC signing
- CSRF protection on all forms
- Rate limiting on SMS codes
- Admin-only features protected
- HTML sanitization on all user content

## Architecture

Everything is in `app.py`:
- **~100 lines**: Database setup
- **~200 lines**: Helper functions
- **~150 lines**: HTML template
- **~700 lines**: Routes (auth, events, feed, admin)

No frameworks. No complexity. Just FastAPI, SQLite, and HTML forms.

## Development

```bash
# Run with auto-reload
uvicorn app:app --reload

# Check database
sqlite3 clubhouse.db "SELECT COUNT(*) FROM members;"

# View logs
# Just watch the terminal - no fancy logging needed
```

## License

Do whatever you want with this code. It's meant to be simple and hackable.

## Support

This is a personal project. No support is provided, but the code is simple enough to understand and modify yourself. That's the point!

---

Built with ❤️ for small, local communities who want to own their own social space.
