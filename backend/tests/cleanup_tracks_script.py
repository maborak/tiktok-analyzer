
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# Database connection
if os.getenv("PHOVEU_BACKEND_DATABASE_URL"):
    DATABASE_URL = os.getenv("PHOVEU_BACKEND_DATABASE_URL")
elif os.getenv("DATABASE_URL"):
    DATABASE_URL = os.getenv("DATABASE_URL")
else:
    DB_USER = os.getenv("POSTGRES_USER", "postgres")
    DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
    DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
    DB_PORT = os.getenv("POSTGRES_PORT", "5432")
    DB_NAME = os.getenv("POSTGRES_DB", "maborak")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def cleanup_tracks():
    print(f"Connecting to {DATABASE_URL}")
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            # Get user ID
            result = conn.execute(text("SELECT id FROM users WHERE email = 'test_user_credits@example.com'"))
            user = result.fetchone()
            if not user:
                print("Test user not found.")
                return

            user_id = user[0]
            print(f"Found user_id: {user_id}")

            # Count tracks
            result = conn.execute(text(f"SELECT count(*) FROM product_tracks WHERE user_id = {user_id}"))
            count = result.fetchone()[0]
            print(f"Found {count} tracks.")

            if count > 0:
                print("Deleting tracks...")
                conn.execute(text(f"DELETE FROM product_tracks WHERE user_id = {user_id}"))
                conn.commit()
                print("Tracks deleted.")
            else:
                print("No tracks to delete.")

            # Verify
            result = conn.execute(text(f"SELECT count(*) FROM product_tracks WHERE user_id = {user_id}"))
            count = result.fetchone()[0]
            print(f"Final track count: {count}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    cleanup_tracks()
