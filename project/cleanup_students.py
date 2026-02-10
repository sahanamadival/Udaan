
import sqlite3
import os

def cleanup_students():
    db_path = os.path.join(os.getcwd(), 'database.db')
    print(f"Connecting to {db_path}...")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    try:
        # Delete students whose grade is NOT 1, 2, 3, 4, or 5
        cur.execute("DELETE FROM students WHERE grade NOT IN ('1', '2', '3', '4', '5')")
        deleted_count = cur.rowcount
        conn.commit()
        print(f"Successfully deleted {deleted_count} students with grades outside the 1-5 range.")
        
        # Verify remaining students
        cur.execute("SELECT name, grade FROM students")
        remaining = cur.fetchall()
        print(f"\nRemaining students ({len(remaining)}):")
        for s in remaining:
            print(f" - {s[0]} (Grade: {s[1]})")
            
    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    cleanup_students()
