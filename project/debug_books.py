
import sqlite3
import os

DB_PATH = 'database.db'
BOOKS_DIR = 'static/books'

print("--- 1. Checking Physical Files in static/books ---")
if os.path.exists(BOOKS_DIR):
    files = os.listdir(BOOKS_DIR)
    if not files:
        print("Folder is empty.")
    else:
        for f in files:
            print(f"  - {f}")
else:
    print(f"Directory {BOOKS_DIR} does not exist!")

print("\n--- 2. Checking Database Records (uploads table) ---")
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT filename, grade, student_id FROM uploads")
    rows = cursor.fetchall()
    
    if not rows:
        print(" 'uploads' table is EMPTY. No books are registered in the database.")
        print("   This is why you don't see them in the library.")
    else:
        for r in rows:
            print(f"  - File: {r[0]} | Grade: {r[1]} | Uploaded By Student ID: {r[2]}")
            
    conn.close()
except Exception as e:
    print(f"Database error: {e}")
