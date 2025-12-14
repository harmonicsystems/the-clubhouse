# How The Clubhouse Works

A plain-language guide for non-programmers.

---

## What Is This?

The Clubhouse is a **private online space** for a small group of people (like 50-200 friends, neighbors, or community members).

Think of it like:
- A private Facebook group, but YOU own it
- A neighborhood bulletin board that lives on the internet
- A members-only club with a digital front door

**What people can do:**
- See upcoming events and say "I'm coming!"
- Post messages to the group
- React to posts with emoji (like 👍 or ❤️)
- Comment on each other's posts
- Vote in polls
- Invite new members

---

## The Big Picture

Imagine a physical clubhouse building:

```
┌─────────────────────────────────────────────────┐
│                 THE CLUBHOUSE                   │
│                                                 │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│   │  Front  │  │  Main   │  │ Manager │        │
│   │  Door   │  │  Room   │  │ Office  │        │
│   │         │  │         │  │         │        │
│   │ Sign in │  │ Events  │  │ Admin   │        │
│   │  here   │  │ & Posts │  │  tools  │        │
│   └─────────┘  └─────────┘  └─────────┘        │
│                                                 │
│   ┌─────────────────────────────────────┐      │
│   │     Filing Cabinet (Database)       │      │
│   │                                     │      │
│   │  - Member list                      │      │
│   │  - All the posts                    │      │
│   │  - Event RSVPs                      │      │
│   │  - Everything is LOCKED (encrypted) │      │
│   └─────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
```

**The "filing cabinet" is locked.** Even if someone broke into the building, they couldn't read any of the membership information without the key.

---

## How People Get In

### For New Members

1. Someone already in the club gives them a **guest pass** (invite code)
   - Looks like: `MOON-742` or `STAR-381`
   - Each pass works only once

2. New person goes to the website and enters the code

3. They type their name and phone number

4. They're in! They can now use the club

### For Existing Members

1. Go to the website
2. Type your phone number
3. You get a text message with a 6-digit code (like `482951`)
4. Type that code into the website
5. You're in!

**Why text messages?** It proves you are who you say you are. Only YOU have your phone. It's like the doorman recognizing your face.

---

## The Different Roles

### Regular Members
- Can see events and RSVP
- Can post messages
- Can react and comment
- Can invite new people (generate guest passes)

### Managers (Moderators)
- Everything regular members can do
- Can delete inappropriate posts
- Can manage events

### The Owner (Admin)
- Everything managers can do
- Can create events
- Can send announcements to everyone's phone
- Can see member statistics
- Has access to the "Manager's Office" (admin panel)

---

## The Important "Settings"

When you set up The Clubhouse, there are a few important pieces of information it needs. Think of these like the clubhouse's private configuration:

| Setting | What It Is | Analogy |
|---------|-----------|---------|
| Admin Phone | Your phone number | The owner's phone number on file |
| Secret Salt | A random password the system uses | The safe combination |
| Database Key | The key that locks all the data | The filing cabinet key |
| Textbelt Key | Permission to send text messages | The phone account |
| Site Name | What you call your community | The sign on the building |

**The two most important things to never lose:**
1. **Database Key** - If you lose this, all your member data is locked forever
2. **Secret Salt** - If you change this, everyone gets logged out

---

## What the "Database" Actually Is

The database is just a single file on the computer that stores everything:

- Every member's name and phone number
- Every event that's been created
- Every post and comment
- Who's coming to which event
- Who invited whom

Think of it as a really organized notebook that the computer keeps updated automatically.

**The notebook is encrypted** (scrambled) so that if someone stole the computer, they couldn't read it without the key.

---

## Backups: Your Safety Net

Backups are copies of your database file. If something goes wrong, you can restore from a backup.

**What can go wrong:**
- You accidentally delete something
- The computer breaks
- Something gets corrupted

**The backup system:**
- Makes a copy every day automatically
- Keeps the last 30 copies
- You can restore any of them

It's like photocopying your important documents and keeping them in a safe.

---

## Where Does This "Live"?

The clubhouse needs a computer that's always on and connected to the internet. You have options:

### Option A: Someone Else's Computer (Recommended for beginners)
- Services like Railway or Render host it for you
- They handle all the technical stuff
- Usually free for small communities
- Like renting an office space

### Option B: Your Own Computer (More control)
- Rent a small computer in the cloud ($5/month)
- You're responsible for keeping it running
- Like owning your own building

---

## Monthly Costs

| What | Cost |
|------|------|
| Hosting (the computer) | $0-6/month |
| Text messages | ~$0.01 each |
| Domain name (optional) | ~$1/month |
| **Total** | **$0-17/month** |

For comparison, most online services charge $10-50/month for similar features - and they own your data.

---

## Safety & Privacy

### What's Protected

✅ All data is encrypted (scrambled) so only you can read it
✅ Phone numbers are never shown publicly on the site
✅ Only members can see the content
✅ No outside company has access to your members' information

### What You're Responsible For

⚠️ Keeping your Database Key safe (write it down somewhere secure!)
⚠️ Choosing trustworthy moderators
⚠️ Making backups (the system does this automatically, but check occasionally)

---

## Common Tasks (The Control Panel)

Here's what you can do as the owner:

### "I want to create an event"
1. Log in with your phone
2. Click "Admin Panel"
3. Fill in the event details
4. Click "Create Event"

### "I want to send a message to everyone"
1. Log in → Admin Panel
2. Type your message in "Broadcast"
3. Click Send
4. Everyone gets a text message

### "I want to make someone a manager"
This requires editing the database directly (see below)

### "Someone's being a problem and I need to remove them"
This requires editing the database directly (see below)

---

## When You Need Help

Some things require "editing the database" - this means changing information directly in the notebook file. You'll need someone technical to help, or you can learn a few simple commands.

**Things that need database editing:**
- Removing a member completely
- Making someone a manager/admin
- Changing someone's phone number
- Looking up information that's not in the admin panel

If you have a technical friend, these are all simple 1-minute tasks for them.

---

## Glossary

| Word | Plain English |
|------|---------------|
| **Server** | A computer that's always on, connected to the internet |
| **Database** | The file that stores all your community's information |
| **Encrypted** | Scrambled so only someone with the key can read it |
| **Admin** | The owner/manager of the community |
| **Environment Variables** | The clubhouse's private settings |
| **Backup** | A safety copy of all your data |
| **Deploy** | Setting up the clubhouse on a computer so people can use it |
| **Domain** | Your website's name (like "ourclub.com") |
| **HTTPS** | The secure version of a website (has a padlock icon) |
| **API** | How the app talks to the text message service |

---

## The Philosophy

This project exists because:

1. **You should own your community's data** - Not Facebook, not Google, not anyone else

2. **Small is beautiful** - 200 people maximum keeps it intimate

3. **Simple is sustainable** - No complex features that break

4. **Phone numbers are enough** - No passwords to forget, no emails to manage

5. **Transparency** - The entire app is readable by anyone who wants to understand it

---

## Questions You Might Have

**"What if the text message doesn't arrive?"**
Wait a minute and try again. Sometimes phone networks are slow. If it keeps failing, check that the phone number is typed correctly.

**"What if I lose my phone?"**
Get a new phone with the same number, and you can log in again. Your membership is tied to your phone number, not your physical device.

**"What if someone leaves the community?"**
Their account stays in the database but they simply won't log in anymore. An admin can fully delete them if needed.

**"Can people see my phone number?"**
Other members see your name and avatar, but not your phone number. Only admins can see phone numbers.

**"What happens if the hosting computer goes down?"**
The site will be temporarily unavailable. When it comes back, everything will be exactly as it was (nothing is lost).

**"Is this legal?"**
Yes. You're simply running a private membership website. Just have a basic privacy policy that explains what data you collect (the app has one built in at /privacy).

---

## Getting Help

If you're stuck:

1. **Check the other guides** - TESTING.md walks through every feature
2. **Ask a technical friend** - Most issues take 5 minutes to fix
3. **Check the project's GitHub** - Other people might have had the same question

---

*This guide was written for humans, not programmers. You don't need to understand code to run a community.*
