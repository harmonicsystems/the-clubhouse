# Testing Checklist

Walk through this checklist before every deploy. Each section should take 2-3 minutes.

## Pre-Flight Setup

```bash
# 1. Start fresh (optional - skip if testing with existing data)
rm clubhouse.db

# 2. Seed test data
python seed_test_data.py

# 3. Start the server
uvicorn app:app --reload --port 8000

# 4. Open browser to http://localhost:8000
```

**Test Accounts:**
- Admin: `555-123-4567` (Alex)
- Moderator: `555-123-4568` (Jordan)
- Regular user: `555-123-4570` (Morgan)
- Unused invite codes: `MOON-742`, `BIRD-156`

---

## Authentication Flow

### Sign In (Existing Member)
- [ ] Go to homepage `/`
- [ ] Enter phone `5551234567`
- [ ] Click "Send me a code"
- [ ] Verify code appears on screen (dev mode)
- [ ] Enter code and click "Verify"
- [ ] Confirm redirect to dashboard

### Sign Up (New Member)
- [ ] Log out first (`/logout`)
- [ ] Enter invite code `MOON-742`
- [ ] Fill in name and phone
- [ ] Confirm registration completes
- [ ] Confirm redirect to dashboard

### Edge Cases
- [ ] Try invalid phone number → Should show "Not Found"
- [ ] Try used invite code `STAR-381` → Should show "Invalid Code"
- [ ] Try wrong verification code → Should show "Wrong Code"

---

## Dashboard & Events

### Calendar View
- [ ] Dashboard shows calendar for current month
- [ ] Events appear on correct dates
- [ ] Navigate to previous/next month
- [ ] Click an event → Goes to event details

### RSVP Flow
- [ ] Find an event with available spots
- [ ] Click "RSVP" → Button changes to "Cancel RSVP"
- [ ] Click "Cancel RSVP" → Button changes back
- [ ] Try to RSVP to a full event (if any) → Should show full message

---

## Feed & Posts

### Viewing Posts
- [ ] Go to `/feed`
- [ ] Posts display with author name, avatar, time
- [ ] Embedded links render (YouTube, Spotify, images)
- [ ] Comments show under posts

### Creating Posts
- [ ] Type a message and submit
- [ ] Post appears at top of feed
- [ ] Try posting a YouTube link → Embeds correctly

### Reactions
- [ ] Click a reaction emoji on a post
- [ ] Emoji count increases and highlights
- [ ] Click same emoji again → Removes reaction

### Comments
- [ ] Click to expand comments on a post
- [ ] Add a new comment
- [ ] Comment appears in thread

### Bookmarks
- [ ] Bookmark a post
- [ ] Go to `/bookmarks`
- [ ] Bookmarked post appears
- [ ] Remove bookmark → Disappears from list

---

## Polls

- [ ] View active poll on feed
- [ ] Vote for an option
- [ ] Results update to show your vote
- [ ] Try to vote again → Should show already voted
- [ ] Undo vote (if implemented)

---

## Profile & Members

### Your Profile
- [ ] Go to `/profile`
- [ ] Update display name → Saves correctly
- [ ] Change avatar emoji → Updates across site
- [ ] Set birthday → Shows on profile

### Member Directory
- [ ] Go to `/members`
- [ ] All members display with avatars
- [ ] Status indicators show (available/away/busy)

---

## Notifications

- [ ] Have another user react to your post (or simulate)
- [ ] Bell icon shows unread count
- [ ] Go to `/notifications`
- [ ] Notifications display correctly
- [ ] Mark as read → Count decreases

---

## Admin Panel (Admin Users Only)

Login as admin (`5551234567`) for these tests:

### Access Control
- [ ] Admin link appears in navigation
- [ ] Go to `/admin`
- [ ] Non-admin users cannot access

### Create Event
- [ ] Fill out event form
- [ ] Submit → Event appears on dashboard calendar
- [ ] Event shows in upcoming events

### Create Poll
- [ ] Create poll with 3-4 options
- [ ] Poll appears on feed

### Moderator Management
- [ ] Promote a user to moderator
- [ ] Demote a moderator

### Attendance
- [ ] Go to attendance for past event
- [ ] Mark members as attended

---

## Invite System

- [ ] Generate new invite code
- [ ] Code displays on screen
- [ ] Code format is `WORD-123`
- [ ] Use code to invite yourself (different browser/incognito)

---

## Error Handling

- [ ] Visit `/nonexistent` → Appropriate error
- [ ] Try to access `/admin` as non-admin → Redirect to home
- [ ] Delete cookies and visit `/dashboard` → Redirect to login

---

## Health Check

- [ ] Visit `/health` → Returns `{"status": "ok", ...}`
- [ ] Response includes database status
- [ ] Response includes member count

---

## Mobile Responsiveness

- [ ] Open site on phone (or use browser dev tools)
- [ ] Navigation is usable
- [ ] Forms are tap-friendly
- [ ] Calendar is readable
- [ ] Feed scrolls smoothly

---

## Final Checks

- [ ] Check server console for any errors
- [ ] No broken images or missing resources
- [ ] All forms have CSRF tokens (check HTML source)
- [ ] Logout works correctly

---

## Post-Deploy Verification

After deploying to staging or production:

- [ ] Site loads over HTTPS
- [ ] Health check returns OK: `curl https://your-domain.com/health`
- [ ] Can log in with test account
- [ ] SMS sends successfully (check Textbelt logs)
- [ ] Database is being created in correct location

---

## Notes

_Use this space to note any issues found:_

```
Date: ___________
Tester: ___________
Issues Found:
-
-
-
```
