"""
Migration: Add reopen_count column to tickets table.

Tracks how many times a ticket has been reopened by the client.
Default 0 for existing tickets.

Usage:
    cd backend && conda activate amazon && python database/migrations/add_ticket_reopen_count.py
"""

from sqlalchemy import text
from utils.database.database_session import get_write_engine


def migrate():
    engine = get_write_engine()
    with engine.connect() as conn:
        # Check if column already exists
        try:
            conn.execute(text("SELECT reopen_count FROM tickets LIMIT 1"))
            print("Column 'reopen_count' already exists — skipping.")
            return
        except Exception:
            pass

        conn.execute(text(
            "ALTER TABLE tickets ADD COLUMN reopen_count INTEGER NOT NULL DEFAULT 0"
        ))
        conn.commit()
        print("Added 'reopen_count' column to tickets table.")


if __name__ == "__main__":
    migrate()
