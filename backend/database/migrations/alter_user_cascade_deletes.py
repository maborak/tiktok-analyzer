"""
Migration: Fix ON DELETE cascade for all foreign keys referencing users.id

Problem: Many FK constraints were created without ON DELETE CASCADE/SET NULL,
causing NotNullViolation when deleting users via ORM because SQLAlchemy tries
to SET user_id=NULL before the DB constraint fires.

Fix: Drop and re-create each FK with the correct ON DELETE action.
"""

import os
import sys
from sqlalchemy import text, inspect

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# (table, column, referenced_table, referenced_column, on_delete_action)
FK_FIXES = [
    # Non-nullable FKs → CASCADE (delete child rows when user is deleted)
    ("recipients", "user_id", "users", "id", "CASCADE"),
    ("user_sessions", "user_id", "users", "id", "CASCADE"),
    ("api_keys", "user_id", "users", "id", "CASCADE"),
    ("email_verifications", "user_id", "users", "id", "CASCADE"),
    ("password_resets", "user_id", "users", "id", "CASCADE"),
    ("oauth_accounts", "user_id", "users", "id", "CASCADE"),  # Already correct, but idempotent
    ("credit_ledgers", "user_id", "users", "id", "CASCADE"),
    ("payment_transactions", "user_id", "users", "id", "CASCADE"),
    ("invoices", "user_id", "users", "id", "CASCADE"),

    # Nullable FKs → SET NULL (preserve tickets/chat history, just null the user ref)
    ("tickets", "user_id", "users", "id", "SET NULL"),
    ("tickets", "assigned_agent_id", "users", "id", "SET NULL"),
    ("ticket_messages", "sender_id", "users", "id", "SET NULL"),
    ("livechat_sessions", "user_id", "users", "id", "SET NULL"),
    ("livechat_sessions", "agent_id", "users", "id", "SET NULL"),
    ("livechat_messages", "sender_id", "users", "id", "SET NULL"),

    # === Secondary chains (non-user FKs that break during cascade) ===

    ("recipient_verifications", "recipient_id", "recipients", "id", "CASCADE"),

    # tickets chain
    ("ticket_messages", "ticket_id", "tickets", "id", "CASCADE"),
    ("ticket_tag_associations", "ticket_id", "tickets", "id", "CASCADE"),
    ("ticket_tag_associations", "tag_id", "ticket_tags", "id", "CASCADE"),
    ("ticket_attachments", "ticket_id", "tickets", "id", "CASCADE"),
    ("ticket_attachments", "message_id", "ticket_messages", "id", "SET NULL"),

    # livechat chain
    ("livechat_sessions", "ticket_id", "tickets", "id", "SET NULL"),
    ("livechat_messages", "session_id", "livechat_sessions", "id", "CASCADE"),
    ("livechat_attachments", "session_id", "livechat_sessions", "id", "CASCADE"),
    ("livechat_attachments", "message_id", "livechat_messages", "id", "SET NULL"),
]


def migrate():
    from utils.database.database_session import get_write_engine

    engine = get_write_engine()
    dialect = engine.dialect.name

    if dialect == "sqlite":
        print("SQLite does not enforce ON DELETE actions on existing tables. "
              "The SQLAlchemy model declarations are sufficient. Skipping.")
        return

    print(f"Running migration: fix ON DELETE cascade for user FKs ({dialect})...")

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    with engine.begin() as conn:
        for table, column, ref_table, ref_column, action in FK_FIXES:
            if table not in existing_tables:
                print(f"  SKIP {table}.{column} — table does not exist")
                continue

            # Find the existing FK constraint name
            fks = inspector.get_foreign_keys(table)
            constraint_name = None
            for fk in fks:
                if (fk["constrained_columns"] == [column]
                        and fk["referred_table"] == ref_table
                        and fk["referred_columns"] == [ref_column]):
                    constraint_name = fk["name"]
                    break

            if not constraint_name:
                print(f"  SKIP {table}.{column} — no FK constraint found (may not exist yet)")
                continue

            # Check if already has the correct ON DELETE action
            # PostgreSQL: inspector doesn't expose ON DELETE, so we always re-create
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name}"
                ))
                conn.execute(text(
                    f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
                    f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column}) "
                    f"ON DELETE {action}"
                ))
                print(f"  FIXED {table}.{column} → ON DELETE {action}")
            except Exception as e:
                print(f"  ERROR {table}.{column}: {e}")


if __name__ == "__main__":
    migrate()
