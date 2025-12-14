# The Clubhouse

A simple, local-first community platform for small groups (50-200 people). Phone numbers only. No passwords. Pure simplicity.

## Philosophy

- **Phone numbers as identity** - SMS verification, no passwords to remember
- **SQLite database** - Just a file on disk, easy to backup
- **Everything in one file** - The entire app is in `app.py`
- **No JavaScript required** - Pure HTML forms
- **Limited membership** - Maximum 200 members (it's a feature, not a bug)
- **Invite-only** - No public signups, community stays intentional

## Features

- **SMS Authentication** - Login with phone verification codes
- **Events** - Create events, RSVP, track attendance
- **Community Feed** - Posts with reactions and comments
- **Polls** - Community voting
- **Notifications** - Stay updated on activity
- **Member Profiles** - Avatars, status, birthdays
- **Admin Panel** - Manage community and events
- **Bookmarks** - Save posts for later

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/YOUR_USERNAME/clubhouse.git
cd clubhouse
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your settings

# 3. Seed test data (optional)
python seed_test_data.py

# 4. Run
uvicorn app:app --reload
```

Visit http://localhost:8000

**Test Accounts** (after seeding):
- Admin: `555-123-4567`
- Unused invite codes: `MOON-742`, `BIRD-156`

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description |
|----------|-------------|
| `ADMIN_PHONES` | Comma-separated admin phone numbers |
| `SECRET_SALT` | Random string for security (run `openssl rand -hex 32`) |
| `DATABASE_KEY` | Encryption key for database (run `openssl rand -hex 32`) |
| `TEXTBELT_KEY` | SMS API key (`textbelt` for 1 free/day) |
| `PRODUCTION_MODE` | Set to `true` for production |
| `SITE_NAME` | Your community name |

## Deployment

See [DEPLOY.md](DEPLOY.md) for step-by-step deployment instructions.

**Quick deploy options:**
- **Railway** - Free tier, automatic HTTPS
- **Render** - Free tier, automatic HTTPS
- **VPS** - $5/month, full control

**Estimated costs:** $0-17/month

## Project Structure

```
clubhouse/
├── app.py                     # The entire application
├── requirements.txt           # Python dependencies
├── .env.example               # Environment template
├── seed_test_data.py          # Test data seeder
├── backup.sh                  # Database backup script
├── migrate_to_encrypted.py    # Encryption migration tool
├── HOW-IT-WORKS.md            # Plain-language guide (no coding required)
├── TESTING.md                 # Manual testing checklist
├── DEPLOY.md                  # Deployment guide
├── railway.json               # Railway config
├── render.yaml                # Render config
└── Procfile                   # Process file for deployment
```

**New to all this?** Start with [HOW-IT-WORKS.md](HOW-IT-WORKS.md) - it explains everything in plain English.

## Testing

```bash
# Seed fresh test data
python seed_test_data.py

# Run the app
uvicorn app:app --reload

# Walk through TESTING.md checklist

# Check health
curl http://localhost:8000/health
```

## Backups

```bash
./backup.sh              # Create backup
./backup.sh list         # List backups
./backup.sh restore 1    # Restore most recent
```

## Customization

### Theming

The CSS uses variables for easy customization. Edit the `:root` section in `app.py`:

```css
:root {
    --color-bg: #fff;
    --color-text: #000;
    --color-accent: #000;
    /* ... */
}
```

### Adding Features

The codebase is intentionally simple. Each route is self-contained.
Read `app.py` top-to-bottom - it's designed to be understood in one sitting.

## Database

The database uses SQLCipher for encryption - all phone numbers and data are encrypted at rest.

**Important:** Keep your `DATABASE_KEY` safe! If you lose it, you lose your data.

```bash
# Migrate existing unencrypted database
python migrate_to_encrypted.py

# For encrypted databases, use Python:
python
>>> from sqlcipher3 import dbapi2 as sqlite3
>>> conn = sqlite3.connect("clubhouse.db")
>>> conn.execute("PRAGMA key = 'your-key-here'")
>>> conn.execute("SELECT * FROM members").fetchall()
```

## Security

- **Encrypted database** - SQLCipher encrypts all data at rest
- **SMS-based authentication** - No passwords to leak
- **HMAC-signed cookies** - Secure flags in production
- **CSRF protection** - On all forms
- **Rate limiting** - On SMS codes
- **HTML sanitization** - On user content

## License

MIT - Do whatever you want with this code.

## Contributing

This is meant to be simple and hackable. Fork it, modify it, make it yours.
The best contribution is building your own community with it.

---

Built with care for small, local communities who want to own their own space.
