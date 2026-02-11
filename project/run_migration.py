from app import migrate_database, init_db
import sqlite3

print("Running migrate_database()...")
try:
    migrate_database()
    print("Migration successful.")
except Exception as e:
    print(f"Migration failed: {e}")

print("Checking table again...")
conn = sqlite3.connect("database.db")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_usage';")
row = cur.fetchone()
if row:
    print("SUCCESS: api_usage table found.")
else:
    print("ERROR: api_usage table still missing.")
conn.close()
