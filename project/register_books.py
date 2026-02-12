
import sqlite3
import os
from datetime import datetime

DB_PATH = 'database.db'
BOOKS_DIR = 'static/books'
TARGET_GRADE = '4' # Defaulting to Grade 4 as per user context

def register_books():
    if not os.path.exists(BOOKS_DIR):
        print(f"❌ Directory {BOOKS_DIR} does not exist!")
        return

    files = [f for f in os.listdir(BOOKS_DIR) if f.lower().endswith('.pdf')]
    if not files:
        print("❌ No PDF files found in static/books.")
        return

    print(f"Found {len(files)} PDF files: {files}")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. Get a valid student ID to assign as uploader
        cursor.execute("SELECT id FROM students LIMIT 1")
        student = cursor.fetchone()
        
        if not student:
            print("❌ No students found in database. Cannot assign uploader.")
            # Optional: Create dummy student? For now, just exit.
            conn.close()
            return

        student_id = student[0]
        print(f"Assigning books to Student ID: {student_id} for Grade {TARGET_GRADE}")

        # 2. Register books
        count = 0
        for filename in files:
            # Check if already exists to avoid duplicates
            cursor.execute("SELECT id FROM uploads WHERE filename = ?", (filename,))
            if cursor.fetchone():
                print(f"  - Skipped (already exists): {filename}")
                continue
                
            uploaded_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO uploads (student_id, filename, grade, uploaded_at)
                VALUES (?, ?, ?, ?)
            """, (student_id, filename, TARGET_GRADE, uploaded_at))
            print(f"  - Registered: {filename}")
            count += 1
            
        conn.commit()
        conn.close()
        print(f"\n✅ Successfully registered {count} books to Grade {TARGET_GRADE}.")
        
    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    register_books()
