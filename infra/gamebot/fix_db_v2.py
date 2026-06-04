import sqlite3
import os

db_path = "bot_data.db"
if not os.path.exists(db_path):
    print(f"Database {db_path} not found.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

def add_column(table, column, type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type}")
        print(f"Added column {column} to {table}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            # Already exists
            pass
        else:
            print(f"Error adding column {column}: {e}")

# Fix users table
add_column("users", "created_at", "DATETIME")

# Fix preferences table
add_column("preferences", "language", "VARCHAR DEFAULT 'ar'")
add_column("preferences", "platform_pc", "BOOLEAN DEFAULT 1")
add_column("preferences", "platform_ps", "BOOLEAN DEFAULT 1")
add_column("preferences", "platform_xbox", "BOOLEAN DEFAULT 1")
add_column("preferences", "platform_switch", "BOOLEAN DEFAULT 1")
add_column("preferences", "platform_mobile", "BOOLEAN DEFAULT 1")
add_column("preferences", "notify_daily_releases", "BOOLEAN DEFAULT 1")
add_column("preferences", "notify_free_games", "BOOLEAN DEFAULT 1")
add_column("preferences", "notify_leaving_games", "BOOLEAN DEFAULT 1")
add_column("game_cache_v2", "thumbnail_url", "TEXT")
add_column("game_cache_v2", "hype_score", "INTEGER DEFAULT 0")
add_column("game_cache_v2", "cost_per_deal", "FLOAT DEFAULT 0.0")
add_column("game_cache_v2", "click_count", "INTEGER DEFAULT 0")
add_column("game_cache_v2", "platform_type", "TEXT DEFAULT 'PC'")
add_column("game_cache_v2", "monetization_tags", "TEXT")
add_column("game_cache_v2", "critic_score", "INTEGER")
add_column("game_cache_v2", "critic_tier", "TEXT")
add_column("game_cache_v2", "last_score_sync", "DATETIME")
add_column("game_cache_v2", "vibe_tag", "TEXT")

# Fix content_queue table
add_column("content_queue", "vibe_tag", "TEXT")
add_column("content_queue", "trend_priority", "INTEGER DEFAULT 5")

# Create content_queue table if not exists
cursor.execute('''
CREATE TABLE IF NOT EXISTS content_queue (
    id INTEGER PRIMARY KEY,
    game_id INTEGER REFERENCES game_cache_v2(id),
    title TEXT NOT NULL,
    vibe_tag TEXT,
    tiktok_script TEXT,
    telegram_caption TEXT,
    trend_priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Create notified_deals table if not exists
cursor.execute('''
CREATE TABLE IF NOT EXISTS notified_deals (
    id INTEGER PRIMARY KEY,
    deal_id TEXT UNIQUE NOT NULL,
    platform TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()
conn.close()
print("Migration check complete.")
