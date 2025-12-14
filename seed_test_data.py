#!/usr/bin/env python3
"""
Seed test data for The Clubhouse
Creates sample members, events, posts, and interactions
"""

import sqlite3
from datetime import datetime, timedelta
import random

DATABASE_PATH = "clubhouse.db"

def seed_database():
    """Fill database with realistic test data"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("🌱 Seeding test data...")

    # Clear existing data (in order to avoid foreign key issues)
    cursor.execute("DELETE FROM poll_votes")
    cursor.execute("DELETE FROM poll_options")
    cursor.execute("DELETE FROM polls")
    cursor.execute("DELETE FROM bookmarks")
    cursor.execute("DELETE FROM notifications")
    cursor.execute("DELETE FROM comments")
    cursor.execute("DELETE FROM reactions")
    cursor.execute("DELETE FROM event_photos")
    cursor.execute("DELETE FROM posts")
    cursor.execute("DELETE FROM rsvps")
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM invite_codes")
    cursor.execute("DELETE FROM members")

    # Sample members (with realistic names and fake phone numbers)
    # Format: (phone, name, handle, display_name, avatar, birthday, is_admin, is_moderator, status)
    members = [
        ("5551234567", "Alex", "alex", "Alex Rivera", "🦁", "1995-03-15", 1, 0, "available"),  # Admin
        ("5551234568", "Jordan", "jordan", "Jordan K.", "🎨", "1998-07-22", 0, 1, "available"),  # Moderator
        ("5551234569", "Taylor", "taylor", "Tay ✨", "✨", "1997-11-08", 0, 1, "away"),  # Moderator
        ("5551234570", "Morgan", "morgan", "Morgan", "🐼", "1996-05-30", 0, 0, "available"),
        ("5551234571", "Casey", "casey", "Casey Chen", "🔥", "1999-01-14", 0, 0, "busy"),
        ("5551234572", "Riley", "riley", "Riley", "🌟", "1994-09-03", 0, 0, "available"),
        ("5551234573", "Jamie", "jamie", "Jamie Smith", "🐶", "1998-12-25", 0, 0, "away"),
        ("5551234574", "Avery", "avery", "Avery", "🤓", "1997-04-18", 0, 0, "available"),
        ("5551234575", "Drew", "drew", "Drew Martinez", "🎭", "1995-08-07", 0, 0, "available"),
        ("5551234576", "Sam", "sam", "Sam", "🦊", "1996-10-29", 0, 0, "busy"),
    ]

    # Insert members with staggered join dates
    base_date = datetime.now() - timedelta(days=60)
    for i, (phone, name, handle, display_name, avatar, birthday, is_admin, is_moderator, status) in enumerate(members):
        join_date = (base_date + timedelta(days=i*5)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO members (phone, name, handle, display_name, avatar, birthday, is_admin, is_moderator, status, joined_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (phone, name, handle, display_name, avatar, birthday, is_admin, is_moderator, status, join_date)
        )

    print(f"✅ Added {len(members)} members")

    # Sample events with times
    # Format: (title, description, date, start_time, end_time, max_spots)
    events_data = [
        (
            "Pizza Night",
            "Monthly pizza gathering at Mario's downtown. Bring friends!",
            (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "18:00",
            "21:00",
            12
        ),
        (
            "Weekend Hike",
            "Easy 3-mile trail with great views. Meet at the parking lot.",
            (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
            "09:00",
            "12:00",
            8
        ),
        (
            "Game Night",
            "Board games, card games, and snacks. BYOB.",
            (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d"),
            "19:00",
            "23:00",
            None  # Unlimited
        ),
        (
            "Book Club",
            "Discussing 'The Clubhouse Chronicles' this month.",
            (datetime.now() + timedelta(days=28)).strftime("%Y-%m-%d"),
            "18:30",
            "20:30",
            10
        ),
    ]

    for event in events_data:
        cursor.execute(
            "INSERT INTO events (title, description, event_date, start_time, end_time, max_spots) VALUES (?, ?, ?, ?, ?, ?)",
            event
        )

    event_ids = [row[0] for row in cursor.execute("SELECT id FROM events").fetchall()]
    print(f"✅ Added {len(events_data)} events")

    # Add some RSVPs
    phones = [m[0] for m in members]
    for event_id in event_ids[:2]:  # First two events get RSVPs
        num_rsvps = random.randint(3, 6)
        rsvp_phones = random.sample(phones, num_rsvps)
        for phone in rsvp_phones:
            cursor.execute(
                "INSERT INTO rsvps (event_id, phone) VALUES (?, ?)",
                (event_id, phone)
            )

    print("✅ Added RSVPs")

    # Sample posts (announcements)
    posts_data = [
        ("5551234567", "Welcome to The Clubhouse! 🏠 Excited to build this community together.", 1),
        ("5551234568", "Anyone want to grab coffee this Saturday morning?", 12),
        ("5551234570", "Just joined! Looking forward to meeting everyone at the next event.", 24),
        ("5551234571", "PSA: The coffee shop on Main St has amazing pastries. Highly recommend! 🥐", 36),
        ("5551234567", "Reminder: Pizza Night is next Friday! Don't forget to RSVP.", 48),
        ("5551234573", "Has anyone been to the new bookstore downtown? Worth checking out?", 60),
        ("5551234575", "Thanks to everyone who came to last week's meetup! Had a great time 🎉", 72),
        ("5551234569", "Looking for recommendations for a good mechanic in the area. Any suggestions?", 84),
        ("5551234572", "Happy Friday everyone! Hope you all have a great weekend ☀️", 96),
        ("5551234574", "Pro tip: The farmers market has incredible produce right now. Get there early!", 108),
    ]

    for phone, content, hours_ago in posts_data:
        posted_date = (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO posts (phone, content, posted_date) VALUES (?, ?, ?)",
            (phone, content, posted_date)
        )

    post_ids = [row[0] for row in cursor.execute("SELECT id FROM posts").fetchall()]
    print(f"✅ Added {len(posts_data)} posts")

    # Add reactions to posts
    emojis = ["👍", "❤️", "😂", "🎉", "🔥"]
    for post_id in post_ids:
        num_reactions = random.randint(1, 5)
        reactors = random.sample(phones, min(num_reactions, len(phones)))
        for phone in reactors:
            emoji = random.choice(emojis)
            cursor.execute(
                "INSERT OR IGNORE INTO reactions (post_id, phone, emoji) VALUES (?, ?, ?)",
                (post_id, phone, emoji)
            )

    print("✅ Added reactions")

    # Add some comments
    comments_data = [
        (1, "5551234568", "Thanks for setting this up! So glad to be here."),
        (1, "5551234570", "Awesome initiative! 🙌"),
        (2, "5551234569", "I'm down! DM me the details."),
        (2, "5551234571", "Count me in too!"),
        (5, "5551234572", "Already RSVP'd! Can't wait 🍕"),
        (6, "5551234574", "Yes! It's great. They have a nice selection of local authors."),
        (8, "5551234567", "I've heard good things about Tony's Auto on Oak Street."),
        (8, "5551234573", "Second that! Tony is honest and affordable."),
    ]

    for post_id, phone, content in comments_data:
        cursor.execute(
            "INSERT INTO comments (post_id, phone, content) VALUES (?, ?, ?)",
            (post_id, phone, content)
        )

    print(f"✅ Added {len(comments_data)} comments")

    # Add some invite codes
    invite_codes = [
        ("MOON-742", "5551234567", None),  # Unused
        ("STAR-381", "5551234567", "5551234568"),  # Used
        ("TREE-529", "5551234568", "5551234569"),  # Used
        ("BIRD-156", "5551234567", None),  # Unused
    ]

    for code, created_by, used_by in invite_codes:
        if used_by:
            cursor.execute(
                "INSERT INTO invite_codes (code, created_by_phone, used_by_phone, used_date) VALUES (?, ?, ?, ?)",
                (code, created_by, used_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        else:
            cursor.execute(
                "INSERT INTO invite_codes (code, created_by_phone) VALUES (?, ?)",
                (code, created_by)
            )

    print(f"✅ Added {len(invite_codes)} invite codes")

    # Add a poll
    cursor.execute("""
        INSERT INTO polls (question, created_by_phone, is_active)
        VALUES (?, ?, ?)
    """, ("What should we do for the next community event?", "5551234567", 1))

    poll_id = cursor.lastrowid

    poll_options = [
        "Outdoor movie night",
        "Potluck dinner",
        "Trivia competition",
        "Volunteer day"
    ]

    for option in poll_options:
        cursor.execute(
            "INSERT INTO poll_options (poll_id, option_text, vote_count) VALUES (?, ?, ?)",
            (poll_id, option, 0)
        )

    # Get option IDs and add some votes
    option_ids = [row[0] for row in cursor.execute("SELECT id FROM poll_options WHERE poll_id = ?", (poll_id,)).fetchall()]

    # Have some members vote
    voters = [("5551234568", 0), ("5551234569", 0), ("5551234570", 1), ("5551234571", 2), ("5551234572", 0)]
    for voter_phone, option_index in voters:
        cursor.execute(
            "INSERT INTO poll_votes (poll_id, phone, option_id) VALUES (?, ?, ?)",
            (poll_id, voter_phone, option_ids[option_index])
        )
        # Update vote count
        cursor.execute(
            "UPDATE poll_options SET vote_count = vote_count + 1 WHERE id = ?",
            (option_ids[option_index],)
        )

    print("✅ Added 1 poll with votes")

    # Add notifications
    notifications_data = [
        ("5551234567", "5551234568", "reaction", 1, "Jordan reacted to your post"),
        ("5551234567", "5551234570", "comment", 1, "Morgan commented on your post"),
        ("5551234568", "5551234567", "reaction", 2, "Alex reacted to your post"),
        ("5551234569", "5551234571", "reaction", 3, "Casey reacted to your post"),
    ]

    for recipient, actor, notif_type, related_id, message in notifications_data:
        cursor.execute("""
            INSERT INTO notifications (recipient_phone, actor_phone, type, related_id, message, is_read)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (recipient, actor, notif_type, related_id, message, 0))

    print(f"✅ Added {len(notifications_data)} notifications")

    # Add bookmarks
    bookmarks_data = [
        ("5551234567", 1),  # Alex bookmarked post 1
        ("5551234567", 5),  # Alex bookmarked post 5
        ("5551234568", 1),  # Jordan bookmarked post 1
        ("5551234570", 4),  # Morgan bookmarked post 4
    ]

    for phone, post_id in bookmarks_data:
        cursor.execute(
            "INSERT INTO bookmarks (phone, post_id) VALUES (?, ?)",
            (phone, post_id)
        )

    print(f"✅ Added {len(bookmarks_data)} bookmarks")

    conn.commit()
    conn.close()

    print("\n🎉 Test database seeded successfully!")
    print("\nTest accounts (use any phone to login):")
    print("  Admin:      555-123-4567 (Alex)")
    print("  Moderators: 555-123-4568 (Jordan), 555-123-4569 (Taylor)")
    print("  Users:      555-123-4570 through 555-123-4576")
    print("\nUnused invite codes:")
    print("  MOON-742")
    print("  BIRD-156")

if __name__ == "__main__":
    seed_database()
