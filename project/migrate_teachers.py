
import sqlite3
import os
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

def run_manual_migration():
    db_path = os.path.join(os.getcwd(), 'database.db')
    print(f"Connecting to {db_path}...")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    try:
        # 1. Update Teachers table schema
        cur.execute("PRAGMA table_info(teachers)")
        columns = [row[1] for row in cur.fetchall()]
        if 'grade' not in columns:
            cur.execute("ALTER TABLE teachers ADD COLUMN grade TEXT")
            print("Successfully added 'grade' column to 'teachers' table.")
        else:
            print("'grade' column already exists in 'teachers' table.")
            
        # 2. Add default teacher accounts
        for grade in range(1, 6):
            grade_str = str(grade)
            name = f'Teacher_Grade{grade_str}'
            # Check if this grade already has a teacher
            cur.execute("SELECT id FROM teachers WHERE grade = ?", (grade_str,))
            if not cur.fetchone():
                pwd = generate_password_hash('udaan123')
                email = f'teacher{grade_str}@udaan.com'
                cur.execute("""
                    INSERT INTO teachers (name, email, password_hash, grade, created_at) 
                    VALUES (?, ?, ?, ?, ?)
                """, (name, email, pwd, grade_str, datetime.now(timezone.utc).isoformat()))
                print(f"Created account: {name}")
            else:
                print(f"Teacher for Grade {grade_str} already exists.")
                
        # 3. Delete legacy accounts
        cur.execute("DELETE FROM teachers WHERE name = 'Shweta'")
        if cur.rowcount > 0:
            print("Deleted legacy account 'Shweta'.")
            
        conn.commit()
        print("\nDatabase update complete.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_manual_migration()
