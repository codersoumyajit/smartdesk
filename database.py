import sqlite3
import os
from datetime import datetime

# Use DATA_DIR so the DB lives on a persistent disk in production
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(DATA_DIR, "smartdesk.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_activity(ticket_id, action):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO activity_log(ticket_id, action, timestamp) VALUES (?, ?, ?)",
        (ticket_id, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            department    TEXT NOT NULL,
            title         TEXT NOT NULL,
            description   TEXT NOT NULL,
            category      TEXT DEFAULT 'General',
            priority      TEXT DEFAULT 'Medium',
            ai_summary    TEXT,
            status        TEXT DEFAULT 'Open',
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            assigned_team TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            action    TEXT,
            timestamp TEXT
        )
    ''')

    # Add assigned_team column if upgrading from an older schema
    try:
        cursor.execute("ALTER TABLE tickets ADD COLUMN assigned_team TEXT")
    except sqlite3.OperationalError:
        # Column already exists — safe to ignore
        pass

    # Performance indexes
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_tickets_name     ON tickets(name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_tickets_status   ON tickets(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_ticket  ON activity_log(ticket_id)"
    )

    conn.commit()
    conn.close()
    print("Database ready.")


if __name__ == '__main__':
    init_db()