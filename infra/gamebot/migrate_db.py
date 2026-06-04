import sqlite3
import os

db_path = "bot_data.db"
print(f"Checking database at {os.path.abspath(db_path)}")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"Current columns: {columns}")
        if 'created_at' not in columns:
            print("Adding created_at column...")
            cursor.execute("ALTER TABLE users ADD COLUMN created_at DATETIME")
            conn.commit()
            print("Successfully added created_at column.")
        else:
            print("Column created_at already exists.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
else:
    print("Database file not found.")
