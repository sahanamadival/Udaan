import sqlite3
import os

db_path = "database.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("Checking tables...")
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [row[0] for row in cur.fetchall()]
print(f"Tables: {tables}")

if 'api_usage' in tables:
    print("SUCCESS: api_usage table found.")
    cur.execute("PRAGMA table_info(api_usage)")
    cols = cur.fetchall()
    print(f"Columns in api_usage: {cols}")
else:
    print("ERROR: api_usage table NOT found.")

conn.close()
