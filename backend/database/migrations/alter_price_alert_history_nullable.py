"""
Migration: Make price_alert_history FKs nullable with SET NULL on delete

Problem: Deleting a price alert or recipient fails with NOT NULL violation
because FK cascades try to SET NULL on columns with NOT NULL constraints.

Fix: Make price_alert_id and recipient_id nullable with ON DELETE SET NULL.
History is an immutable audit log — parent deletions must not destroy records.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.database.database_session import get_write_engine
from sqlalchemy import text, inspect


def _fix_column(conn, inspector, table, column, ref_table, ref_column, dialect):
    """Make a FK column nullable and set ON DELETE SET NULL."""
    columns = {c['name']: c for c in inspector.get_columns(table)}
    col = columns.get(column)

    if not col:
        print(f"  Column {table}.{column} not found, skipping.")
        return

    if dialect == 'postgresql':
        # Drop NOT NULL if present
        if col.get('nullable') is False:
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"))
            print(f"  Dropped NOT NULL on {table}.{column}")
        else:
            print(f"  {table}.{column} is already nullable")

        # Replace FK constraint with ON DELETE SET NULL
        fks = inspector.get_foreign_keys(table)
        for fk in fks:
            if column in fk.get('constrained_columns', []):
                fk_name = fk.get('name')
                if fk_name:
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {fk_name}"))
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD CONSTRAINT {fk_name} "
                        f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column}) ON DELETE SET NULL"
                    ))
                    print(f"  Updated FK {fk_name} with ON DELETE SET NULL")
                break
    else:
        print(f"  SQLite: NOT NULL not strictly enforced for {table}.{column}, skipping ALTER")


def run():
    engine = get_write_engine()
    dialect = engine.dialect.name
    inspector = inspect(engine)

    # Check if table exists
    if 'price_alert_history' not in inspector.get_table_names():
        print("Table price_alert_history does not exist. Nothing to do.")
        return

    with engine.begin() as conn:
        print("Fixing price_alert_history.price_alert_id...")
        _fix_column(conn, inspector, 'price_alert_history', 'price_alert_id', 'price_alerts', 'id', dialect)

        print("Fixing price_alert_history.recipient_id...")
        _fix_column(conn, inspector, 'price_alert_history', 'recipient_id', 'recipients', 'id', dialect)

    print("Migration complete.")


if __name__ == "__main__":
    run()
