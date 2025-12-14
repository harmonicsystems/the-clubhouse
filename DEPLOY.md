# Deployment Guide

Step-by-step guide to deploying The Clubhouse to production.

## Pre-Deployment Checklist

Before deploying, make sure you've:

- [ ] Run through `TESTING.md` checklist locally
- [ ] Changed `SECRET_SALT` to a secure random value
- [ ] Set up a Textbelt API key (or plan to use the free tier carefully)
- [ ] Decided on your domain name
- [ ] Created a backup of any existing data: `./backup.sh`

---

## Option 1: Railway (Recommended for Beginners)

Railway offers a generous free tier and automatic HTTPS.

### Step 1: Prepare Your Repository

```bash
# Make sure you're in the clubhouse-v2 directory
cd clubhouse-v2

# Initialize git if you haven't
git init
git add .
git commit -m "Initial commit"

# Create a GitHub repository and push
# Go to github.com/new, create repo, then:
git remote add origin https://github.com/YOUR_USERNAME/clubhouse.git
git push -u origin main
```

### Step 2: Deploy to Railway

1. Go to [railway.app](https://railway.app) and sign up with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your clubhouse repository
4. Railway will auto-detect Python and start deploying

### Step 3: Configure Environment Variables

In Railway dashboard → Your Project → Variables, add:

```
PRODUCTION_MODE=true
SECRET_SALT=your-secure-random-string-here
ADMIN_PHONES=+15551234567
TEXTBELT_KEY=your-textbelt-key
SITE_NAME=The Clubhouse
SITE_URL=https://your-app.railway.app
```

Generate a secure SECRET_SALT:
```bash
openssl rand -hex 32
```

### Step 4: Set Up Persistent Storage

Railway's filesystem is ephemeral. For SQLite to persist:

1. In Railway dashboard, go to your project
2. Add a new service → "Database" → "Add Volume"
3. Mount path: `/app/data`
4. Update your `DATABASE_PATH` env var: `DATABASE_PATH=/app/data/clubhouse.db`

### Step 5: Verify Deployment

```bash
# Check health endpoint
curl https://your-app.railway.app/health

# Should return: {"status": "ok", ...}
```

---

## Option 2: Render

Render also has a free tier with automatic HTTPS.

### Step 1: Create render.yaml

This file is already created in the repo. Just push to GitHub.

### Step 2: Deploy to Render

1. Go to [render.com](https://render.com) and sign up
2. Click "New" → "Web Service"
3. Connect your GitHub repository
4. Render will use the `render.yaml` configuration

### Step 3: Configure Environment Variables

In Render dashboard → Environment, add the same variables as Railway.

### Step 4: Persistent Disk

1. In your service settings, add a Disk
2. Mount path: `/app/data`
3. Update `DATABASE_PATH=/app/data/clubhouse.db`

---

## Option 3: VPS (DigitalOcean, Linode, etc.)

For more control, use a $5/month VPS.

### Step 1: Create Your Server

1. Create a Debian/Ubuntu server ($5/month tier is fine)
2. SSH into your server: `ssh root@your-server-ip`

### Step 2: Run the Deploy Script

```bash
# Clone your repo
git clone https://github.com/YOUR_USERNAME/clubhouse.git
cd clubhouse

# Create your .env file
cp .env.example .env
nano .env  # Edit with your values

# Run the deploy script
chmod +x deploy.sh
sudo ./deploy.sh
```

### Step 3: Point Your Domain

1. In your domain registrar, add an A record pointing to your server IP
2. The deploy script will set up Caddy for automatic HTTPS

---

## Post-Deployment Checklist

After deploying:

- [ ] Visit your site and verify it loads
- [ ] Check `/health` endpoint returns OK
- [ ] Create your admin account using an invite code
- [ ] Test SMS sending (login flow)
- [ ] Set up database backups (see below)
- [ ] Monitor the first few days for any issues

---

## Database Backups (Production)

### Option A: Manual Backups

SSH into your server and run:
```bash
cd /path/to/clubhouse
./backup.sh
```

### Option B: Automated Daily Backups

Add a cron job:
```bash
crontab -e

# Add this line (runs at 3am daily):
0 3 * * * cd /path/to/clubhouse && ./backup.sh >> /var/log/clubhouse-backup.log 2>&1
```

### Option C: Cloud Backup

For Railway/Render, periodically download your database:
```bash
# From your local machine
scp your-server:/app/data/clubhouse.db ./backups/
```

---

## Monitoring

### Health Check Monitoring

Set up a free uptime monitor at [uptimerobot.com](https://uptimerobot.com):
1. Create account
2. Add new monitor → HTTP(s)
3. URL: `https://your-domain.com/health`
4. Interval: 5 minutes

### Log Viewing

**Railway:**
```bash
railway logs
```

**Render:**
View logs in the Render dashboard

**VPS:**
```bash
journalctl -u clubhouse -f
```

---

## Troubleshooting

### App won't start
- Check logs for Python errors
- Verify all environment variables are set
- Make sure `requirements.txt` is present

### SMS not sending
- Verify `TEXTBELT_KEY` is correct
- Check Textbelt quota at textbelt.com
- Look for SMS errors in logs

### Database errors
- Ensure the database directory exists and is writable
- Check disk space
- Try running migrations: restart the app to re-run `init_database()`

### HTTPS not working
- Wait a few minutes for certificate provisioning
- Check that your domain DNS is pointing to the right IP
- Verify Caddy is running: `systemctl status caddy`

---

## Rollback Plan

If something goes wrong:

1. **Restore from backup:**
   ```bash
   ./backup.sh restore 1
   ```

2. **Revert code changes:**
   ```bash
   git log --oneline  # Find the last good commit
   git checkout <commit-hash>
   ```

3. **Restart the service:**
   ```bash
   # Railway/Render: Redeploy from dashboard
   # VPS:
   sudo systemctl restart clubhouse
   ```

---

## Cost Summary

| Service | Monthly Cost |
|---------|-------------|
| Railway (free tier) | $0 |
| Render (free tier) | $0 |
| VPS (DigitalOcean/Linode) | $5-6 |
| Textbelt SMS | ~$10 (1000 texts) |
| Domain (optional) | ~$1 |

**Total: $0-17/month** depending on your choices.
