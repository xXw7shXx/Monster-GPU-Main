import sqlite3
import os

db_path = r'C:\Users\Administrator\Desktop\Telegram GameBot\bot_data.db'
output_path = r'C:\Users\Administrator\Desktop\Telegram GameBot\db_check_results.txt'

with open(output_path, 'w') as f:
    f.write(f"Checking database at: {db_path}\n")

    if not os.path.exists(db_path):
        f.write("Database file does not exist!\n")
    else:
        f.write(f"File size: {os.path.getsize(db_path)} bytes\n")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            f.write(f"Tables: {tables}\n")
            
            for table in tables:
                name = table[0]
                cursor.execute(f"SELECT COUNT(*) FROM {name}")
                count = cursor.fetchone()[0]
                f.write(f"Table '{name}' has {count} rows.\n")
                
            conn.close()
        except Exception as e:
            f.write(f"Error: {e}\n")
