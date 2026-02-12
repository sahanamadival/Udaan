from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
import xml.sax.saxutils as saxutils
import asyncio
import edge_tts
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timezone, timedelta
from functools import wraps
import PyPDF2
import time
from openai import OpenAI
from deep_translator import GoogleTranslator
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from PyPDF2 import PdfReader
import fitz 
import pytesseract
from PIL import Image
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import json
import re
from pdf2image import convert_from_path
import zipfile
import xml.etree.ElementTree as ET

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))  # Load environment variables from .env file

# AI Quota Config
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 500))
DAILY_REQUEST_LIMIT = int(os.getenv("DAILY_REQUEST_LIMIT", 20))

def check_and_update_quota(student_id):
    """
    Logs AI usage to terminal and database.
    Does NOT block the user (monitoring mode).
    """
    today = datetime.now(timezone.utc).date().isoformat()
    conn = get_db()
    cur = conn.cursor()
    
    # Check current usage
    cur.execute("SELECT request_count FROM api_usage WHERE student_id = ? AND usage_date = ?", (student_id, today))
    row = cur.fetchone()
    
    count = 0
    if row:
        count = row[0]
        # Log to terminal if over soft limit
        if count >= DAILY_REQUEST_LIMIT:
            print(f"!!! [MONITORING] Student {student_id} exceeded soft daily limit ({count + 1}/{DAILY_REQUEST_LIMIT}) !!!")
        
        # Increment usage
        cur.execute("UPDATE api_usage SET request_count = request_count + 1 WHERE student_id = ? AND usage_date = ?", (student_id, today))
    else:
        # First request of the day
        cur.execute("INSERT INTO api_usage (student_id, usage_date, request_count) VALUES (?, ?, ?)", (student_id, today, 1))
    
    conn.commit()
    conn.close()
    return True, ""

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("Error: OPENAI_API_KEY not found. Please create a .env file with your API key.")
    # You might want to handle this gracefully depending on app requirements
    # For now, we'll let it fail but with a clearer message
    pass 

client = OpenAI(api_key=api_key)

# Configure Tesseract Path
tesseract_cmd = os.getenv("TESSERACT_CMD")
if not tesseract_cmd:
    # Common default paths for Windows
    possible_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"/usr/bin/tesseract",  # Linux
        r"/usr/local/bin/tesseract"  # Mac
    ]
    for path in possible_paths:
        if os.path.exists(path):
            tesseract_cmd = path
            break

if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
else:
    print("⚠️ Warning: Tesseract not found in standard paths. OCR may fail.")


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")  
# Database configuration
DB = os.path.join(os.path.dirname(__file__), 'database.db')
books=[]

# Google OAuth setup
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_DISCOVERY_URL = os.getenv("GOOGLE_DISCOVERY_URL", "https://accounts.google.com/.well-known/openid_configuration")

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    from requests_oauthlib import OAuth2Session
    import requests
    
    # Allow OAuth2 over HTTP for local development
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Define Google OAuth URLs
    AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    # Scopes for Google OAuth
    GOOGLE_SCOPES = ["openid", "email", "profile"]
    
    def get_google_auth_state_token():
        """Generate a state parameter to prevent CSRF attacks"""
        import secrets
        return secrets.token_urlsafe(32)
    
    # Google OAuth routes will create OAuth2Session directly

# Check if Google OAuth is properly configured
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    print("Google OAuth configured successfully")
else:
    print("Warning: Google OAuth is not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file.")

BOOKS_FOLDER = os.path.join("static", "books")
os.makedirs(BOOKS_FOLDER, exist_ok=True)

UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "static/audio"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Hybrid Text Extraction
def run_edge_tts(text, output_file, voice="en-US-ChristopherNeural"):
    """
    Synchronous wrapper for Edge TTS.
    """
    async def _generate():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
             # If strictly single-threaded/event loop already running, we might need nesting
             # But for Flask (threaded), new loop usually works better or run_coroutine_threadsafe
            asyncio.run(_generate()) 
        else:
            loop.run_until_complete(_generate())
    except RuntimeError:
        # Fallback for when loop is already running (e.g. some envs)
        asyncio.run(_generate())

def extract_text_hybrid(filepath):
    """
    Robust text extraction supporting PDF, DOCX, and TXT.
    Handles scanned PDFs via OCR (if dependencies exist).
    """
    text = ""
    ext = os.path.splitext(filepath)[1].lower()

    print(f"Extracting text from: {filepath} ({ext})")

    try:
        # --- TXT File ---
        if ext == ".txt":
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        # --- DOCX File (XML Parsing) ---
        if ext == ".docx":
            try:
                with zipfile.ZipFile(filepath) as z:
                    xml_content = z.read("word/document.xml")
                    root = ET.fromstring(xml_content)
                    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    text_parts = []
                    for node in root.findall(".//w:t", namespace):
                        if node.text:
                            text_parts.append(node.text)
                    return "\n".join(text_parts)
            except Exception as e:
                print(f"DOCX extraction failed: {e}")
                return ""

        # --- PDF File ---
        if ext == ".pdf":
            # 1. Try PyPDF2 (Text-based PDF)
            try:
                pdf_reader = PyPDF2.PdfReader(open(filepath, "rb"))
                for page in pdf_reader.pages:
                    text += page.extract_text() or ""
            except Exception as e:
                print("⚠️ PyPDF2 error:", e)

            if text.strip():
                return text

            # 2. Fallback: OCR (Scanned PDF)
            print("⚠️ No text found in PDF, attempting OCR...")
            
            try:
                # Check for Poppler (required for convert_from_path to work)
                try:
                    from pdf2image import convert_from_path
                    pages = convert_from_path(filepath) 
                    for page in pages:
                        text += pytesseract.image_to_string(page)
                except Exception as e:
                     print(f"⚠️ OCR (pdf2image) failed: {e}")
                     # Fallback: Try fitz (PyMuPDF) -> Image -> Tesseract which doesn't need Poppler
                     try:
                        import fitz
                        doc = fitz.open(file_path)
                        for page in doc:
                            pix = page.get_pixmap()
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            text += pytesseract.image_to_string(img)
                     except Exception as e2:
                        print(f"⚠️ OCR (PyMuPDF) failed: {e2}")

            except Exception as e:
                print("⚠️ OCR failed completely:", e)

            return text if text.strip() else "ERROR_NO_TEXT: Could not read text. Please check the file."
    except Exception as e:
        print(f"General extraction error: {e}")
        return ""

    return text


def text_to_pdf(text, output_pdf, font_path, font_size=16):
    """
    Enhanced PDF generation for dyslexic learners:
    - Automatic word wrapping using ReportLab Platypus.
    - Increased font size and line spacing (leading).
    - Generous margins.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.units import inch

    print("Registering font:", font_path)
    font_name = "CustomFont"
    pdfmetrics.registerFont(TTFont(font_name, font_path))

    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )

    styles = getSampleStyleSheet()
    # Create a custom style for dyslexic readability
    custom_style = ParagraphStyle(
        'DyslexicStyle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=font_size,
        textColor='#333333',  # Dark gray for better readability than pure black
        leading=font_size * 1.8,  # Force 1.8 line spacing
        spaceAfter=12,
        alignment=0, # Left aligned
    )

    story = []
    
    # Clean text: Remove control characters that might break ReportLab
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\r\t")
    
    # Process text into paragraphs
    for p in text.split("\n"):
        p_clean = p.strip()
        if p_clean:
            # Escape HTML-like characters (e.g., <, >, &) that break ReportLab Paragraph
            escaped_text = saxutils.escape(p_clean)
            story.append(Paragraph(escaped_text, custom_style))
        else:
            story.append(Spacer(1, 12))

    doc.build(story)
    print(f"PDF saved to: {output_pdf}")

# Translation 
def translate_pdf_to_pdf(input_pdf, output_pdf, target_lang, font_path):
    font_name = f"Font_{target_lang}"
    pdfmetrics.registerFont(TTFont(font_name, font_path))
    
    with open(input_pdf, "rb") as book:
        reader = PyPDF2.PdfReader(book)
        c = canvas.Canvas(output_pdf, pagesize=A4)
        width, height = A4

        for num in range(len(reader.pages)):
            text = reader.pages[num].extract_text()
            if text:
                # Translate text using deep-translator
                try:
                    translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
                except Exception as e:
                    print(f"Translation error: {e}")
                    # Fallback to original text if translation fails
                    translated = text
                    
                textobject = c.beginText(50, height - 50)
                textobject.setFont(font_name, 12)

                for line in translated.split("\n"):
                    textobject.textLine(line)

                c.drawText(textobject)
                c.showPage()

        c.save()

# DB Setup 
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def extract_labels_for_dragdrop(text):
    # Use OpenAI model to generate diagram data
    try:
        # Ask OpenAI to generate diagram data
        prompt = f"""
        From the following chapter text, generate a simple educational diagram model with exactly 4–6 components.  
        Return JSON with:  
        {{
          'diagram_title': '...',
          'diagram_description': '...',
          'components': [
              {{ 'label': '...', 'x': number(0–800), 'y': number(0–400) }}
          ]
        }}  
        IMPORTANT: coordinates must be reasonable and non-overlapping.
        
        Chapter text: {text}
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )
        
        response_text = response.choices[0].message.content
        
        # Parse the JSON response
        import json
        import re
        
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            return {"error": "Invalid response format from AI"}
        
        diagram_data = json.loads(json_match.group())
        
        return diagram_data
    
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return {"error": "Invalid JSON response from AI"}
    except Exception as e:
        print(f"Error in extract_labels_for_dragdrop: {e}")
        return {"error": str(e)}



def update_progress(student_id, field):
    # First, run migration to ensure columns exist
    migrate_student_progress_table()
    
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    try:
        # Legacy update
        cur.execute(f"""
            UPDATE student_progress
            SET {field} = {field} + 1,
                last_updated = CURRENT_TIMESTAMP
            WHERE student_id=? AND grade=4
        """, (student_id,))
        
        # New unified system update (record in quiz_attempts)
        # Map fields to unified prefixes
        quiz_id = f"g4_{field.replace('_solved', '').replace('_done', '').replace('_analyzed', 'read')}"
        if 'math' in field: quiz_id = "g4_math_practice"
        elif 'science' in field: quiz_id = "g4_science_activity"
        elif 'creative' in field: quiz_id = "g4_logic_writing"
        elif 'books' in field: quiz_id = "g4_reading_master"
        
        cur.execute("""
            INSERT INTO quiz_attempts (student_id, quiz_id, score, total, attempted_at)
            VALUES (?, ?, ?, ?, ?)
        """, (student_id, quiz_id, 1, 1, datetime.now(timezone.utc).isoformat()))

        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        # Handle case where columns still don't exist after migration
        if "no such column" in str(e):
            # Ensure columns exist by running migration again
            conn.close()
            migrate_student_progress_table()
            # Retry the operation
            update_progress(student_id, field)
        else:
            raise e

def migrate_student_progress_table():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # Get existing columns
    cur.execute("PRAGMA table_info(student_progress)")
    columns = [row[1] for row in cur.fetchall()]
    column_names = [col.lower() for col in columns]  # Convert to lowercase for comparison

    # Check if the table has the old schema (with activity_type and data_json)
    if "activity_type" in column_names and "data_json" in column_names:
        # This is the old table schema, we need to recreate it properly
        # First, backup any important data if needed
        # Then drop the old table and create the new one
        cur.execute("DROP TABLE student_progress")
        
        # Create the new table with the correct schema for grade-specific progress
        cur.execute('''CREATE TABLE IF NOT EXISTS student_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            grade INTEGER,
            books_analyzed INTEGER DEFAULT 0,
            math_solved INTEGER DEFAULT 0,
            science_done INTEGER DEFAULT 0,
            creative_done INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    else:
        # Add missing columns to the new schema if they don't exist
        if "books_analyzed" not in column_names:
            cur.execute("ALTER TABLE student_progress ADD COLUMN books_analyzed INTEGER DEFAULT 0")

        if "math_solved" not in column_names:
            cur.execute("ALTER TABLE student_progress ADD COLUMN math_solved INTEGER DEFAULT 0")

        if "science_done" not in column_names:
            cur.execute("ALTER TABLE student_progress ADD COLUMN science_done INTEGER DEFAULT 0")

        if "creative_done" not in column_names:
            cur.execute("ALTER TABLE student_progress ADD COLUMN creative_done INTEGER DEFAULT 0")
            
        if "grade" not in column_names:
            cur.execute("ALTER TABLE student_progress ADD COLUMN grade INTEGER DEFAULT 4")

    conn.commit()
    conn.close()

def migrate_database():
    """Safely migrate database to match production schema without losing data."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    try:
        # Check student_progress table for missing columns
        cur.execute("PRAGMA table_info(student_progress)")
        columns = [row[1] for row in cur.fetchall()]
        
        # Add missing columns to student_progress table
        if "reading_done" not in columns:
            cur.execute("ALTER TABLE student_progress ADD COLUMN reading_done INTEGER DEFAULT 0")
            print("Added reading_done column to student_progress table")
        
        if "writing_done" not in columns:
            cur.execute("ALTER TABLE student_progress ADD COLUMN writing_done INTEGER DEFAULT 0")
            print("Added writing_done column to student_progress table")
        
        if "last_activity_date" not in columns:
            cur.execute("ALTER TABLE student_progress ADD COLUMN last_activity_date DATE")
            print("Added last_activity_date column to student_progress table")

        # Ensure students table exists before checking columns
        cur.execute("""CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            grade TEXT,
            accessibility TEXT,
            email TEXT,
            phone TEXT,
            password_hash TEXT,
            created_at TEXT,
            reset_token TEXT,
            reset_token_expires TEXT,
            google_id TEXT,
            reset_otp TEXT,
            reset_otp_expires TEXT
        )""")

        # Add OTP columns to students table if they don't exist
        cur.execute("PRAGMA table_info(students)")
        student_columns = [row[1] for row in cur.fetchall()]
        if "reset_otp" not in student_columns:
            cur.execute("ALTER TABLE students ADD COLUMN reset_otp TEXT")
            print("Added reset_otp column to students table")
        if "reset_otp_expires" not in student_columns:
            cur.execute("ALTER TABLE students ADD COLUMN reset_otp_expires TEXT")
            print("Added reset_otp_expires column to students table")
            
        # Add grade column to uploads table if it doesn't exist
        cur.execute("PRAGMA table_info(uploads)")
        uploads_columns = [row[1] for row in cur.fetchall()]
        if "grade" not in uploads_columns:
            cur.execute("ALTER TABLE uploads ADD COLUMN grade TEXT")
            print("Added grade column to uploads table")
        
        if "streak_count" not in columns:
            cur.execute("ALTER TABLE student_progress ADD COLUMN streak_count INTEGER DEFAULT 0")
            print("Added streak_count column to student_progress table")
        
        # Ensure teachers table exists before checking columns
        cur.execute("""CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            password_hash TEXT,
            grade TEXT,
            created_at TEXT,
            google_id TEXT
        )""")

        # Check teachers table for missing columns
        cur.execute("PRAGMA table_info(teachers)")
        teacher_columns = [row[1] for row in cur.fetchall()]
        if "grade" not in teacher_columns:
            cur.execute("ALTER TABLE teachers ADD COLUMN grade TEXT")
            print("Added grade column to teachers table")

        # Create grade_activities table if it doesn't exist
        cur.execute("""CREATE TABLE IF NOT EXISTS grade_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            grade INTEGER,
            activity_type TEXT,
            activity_count INTEGER DEFAULT 0,
            last_completed DATE,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )""")
        print("Ensured grade_activities table exists")
        
        # Add reset_token columns to students table only (teacher functionality removed)
        try:
            cur.execute("ALTER TABLE students ADD COLUMN reset_token TEXT")
            print("Added reset_token column to students table")
        except sqlite3.OperationalError:
            # Column might already exist, ignore error
            pass
        
        try:
            cur.execute("ALTER TABLE students ADD COLUMN reset_token_expires TEXT")
            print("Added reset_token_expires column to students table")
        except sqlite3.OperationalError:
            # Column might already exist, ignore error
            pass
        
        # Add google_id column for Google OAuth support
        try:
            cur.execute("ALTER TABLE students ADD COLUMN google_id TEXT")
            print("Added google_id column to students table")
        except sqlite3.OperationalError:
            # Column might already exist, ignore error
            pass
        
        # Add api_usage table for quota tracking
        cur.execute("""CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            usage_date DATE,
            request_count INTEGER DEFAULT 0,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )""")
        print("Ensured api_usage table exists")
        
        conn.commit()
        print("Database migration completed successfully")
        
    except Exception as e:
        print(f"Error during database migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
def create_default_teachers():
    """Ensure 5 default teacher accounts exist, one for each grade."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    
    try:
        # Check if we already have the standard teachers
        cur.execute("SELECT COUNT(*) FROM teachers")
        count = cur.fetchone()[0]
        
        # We only auto-create if there are fewer than 5 teachers (assuming fresh setup or migration)
        # Or more robustly, we check for each grade.
        for grade in range(1, 6):
            grade_str = str(grade)
            teacher_name = f"Teacher_Grade{grade_str}"
            cur.execute("SELECT id FROM teachers WHERE grade = ?", (grade_str,))
            if not cur.fetchone():
                # Create default account
                # Password is "udaan123" for all by default, can be changed later
                password_hash = generate_password_hash("udaan123")
                email = f"teacher{grade_str}@udaan.com"
                cur.execute("""
                    INSERT INTO teachers (name, email, password_hash, grade, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (teacher_name, email, password_hash, grade_str, datetime.now(timezone.utc).isoformat()))
                print(f"Created default teacher account for Grade {grade_str}")
                
        # Ensure Admin account exists
        cur.execute("SELECT id FROM teachers WHERE grade = 'Admin'")
        if not cur.fetchone():
            password_hash = generate_password_hash("Admin@123")
            email = "admin@udaan.com"
            cur.execute("""
                INSERT INTO teachers (name, email, password_hash, grade, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, ("Admin", email, password_hash, "Admin", datetime.now(timezone.utc).isoformat()))
            print("Created default Admin account")

        conn.commit()
    except Exception as e:
        print(f"Error creating default teachers: {e}")
    finally:
        conn.close()

def init_db():
    """Initialize database from schema.sql if database.db doesn't exist."""
    db_path = os.path.join(os.path.dirname(__file__), "database.db")
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    
    # Check if database exists
    if not os.path.exists(db_path):
        print("Database not found. Creating from schema...")
        try:
            # Read and execute schema
            with open(schema_path, 'r') as f:
                schema_sql = f.read()
            
            # Create database and execute schema
            conn = sqlite3.connect(db_path)
            conn.executescript(schema_sql)
            conn.commit()
            conn.close()
            print("Database initialized from schema.sql")
        except FileNotFoundError:
            print(f"Error: {schema_path} not found. Creating database with basic tables...")
            # Fallback to basic table creation
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            create_basic_tables(c)
            conn.commit()
            conn.close()
            print("Database initialized with basic tables")
        except Exception as e:
            print(f"Error initializing database: {e}")
            raise
    else:
        print("Database already exists. Skipping initialization.")


def create_basic_tables(c):
    """Create basic tables if schema.sql is not available."""
    # This is a fallback - the full schema should be in schema.sql
    c.execute("""CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        age INTEGER,
        grade TEXT,
        accessibility TEXT,
        email TEXT,
        phone TEXT,
        password_hash TEXT,
        created_at TEXT,
        reset_token TEXT,
        reset_token_expires TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        password_hash TEXT,
        grade TEXT,
        created_at TEXT,
        google_id TEXT
    )""")
    # Add other essential tables as needed





def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user:
                flash("Please log in first.")
                return redirect(url_for("index"))
            # Check role restrictions
            if role:
                if user.get("role") != role:
                    flash(f"Access restricted to {role}s only.")
                    return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def redirect_to_dashboard(user):
    if not user:
        flash("Please log in first.")
        return redirect(url_for("index"))
    grade = user.get("grade")
    if grade in ["1", "2", "3", "4", "5"]:
        return redirect(url_for(f"grade_{grade}_dashboard"))
    flash("Grade dashboard not found. Redirecting to home.")
    return redirect(url_for("index"))

def get_student_progress(student_id):
    """Calculate dynamic progress stats for a student."""
    conn = get_db()
    cur = conn.cursor()
    
    # Count uploaded books
    cur.execute("SELECT COUNT(*) FROM uploads WHERE student_id = ?", (student_id,))
    books_read = cur.fetchone()[0]
    
    # Count general quizzes taken (from textbooks)
    # Most general quizzes don't have a specific grade prefix g1_, g2_, etc.
    cur.execute("SELECT COUNT(*) FROM quiz_attempts WHERE student_id = ? AND quiz_id NOT LIKE 'g%_%'", (student_id,))
    quizzes_taken = cur.fetchone()[0]
    
    # Count flashcards sets created
    cur.execute("SELECT COUNT(*) FROM flashcards WHERE student_id = ?", (student_id,))
    flashcards_created = cur.fetchone()[0]

    # Dynamic Subject Points (Captured across all grades g1-g5)
    # Math Points
    cur.execute("SELECT SUM(score) FROM quiz_attempts WHERE student_id = ? AND quiz_id LIKE 'g%_math_%'", (student_id,))
    math_points = cur.fetchone()[0] or 0

    # Science/World Explorer Points
    cur.execute("SELECT SUM(score) FROM quiz_attempts WHERE student_id = ? AND (quiz_id LIKE 'g%_science_%' OR quiz_id LIKE 'g%_transport%' OR quiz_id LIKE 'g%_food%')", (student_id,))
    science_points = cur.fetchone()[0] or 0

    # Grammar/English Hub Points
    cur.execute("SELECT SUM(score) FROM quiz_attempts WHERE student_id = ? AND (quiz_id LIKE 'g%_grammar_%' OR quiz_id LIKE 'g%_sentences%' OR quiz_id LIKE 'g%_alphabets%' OR quiz_id LIKE 'g%_reading%')", (student_id,))
    grammar_points = cur.fetchone()[0] or 0

    # Logic/Brain Gym Points
    cur.execute("SELECT SUM(score) FROM quiz_attempts WHERE student_id = ? AND quiz_id LIKE 'g%_logic_%'", (student_id,))
    logic_points = cur.fetchone()[0] or 0

    # Creative/Art Points
    cur.execute("SELECT SUM(score) FROM quiz_attempts WHERE student_id = ? AND quiz_id LIKE 'g%_art%'", (student_id,))
    creative_points = cur.fetchone()[0] or 0
    
    conn.close()
    
    return {
        "books_read": books_read,
        "quizzes_taken": quizzes_taken,
        "flashcards_created": flashcards_created,
        "math_solved": math_points,
        "science_done": science_points,
        "grammar_done": grammar_points,
        "logic_done": logic_points,
        "creative_done": creative_points
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/student")
def student_portal():
    return render_template("student_portal.html")

@app.route("/teacher")
def teacher_portal():
    return render_template("teacher_portal.html")

@app.route("/role/<role>")
def role_page(role):
    role = role.lower()
    if role not in ["student", "teacher"]:
        flash("Invalid role selected.")
        return redirect(url_for("index"))
    if role == "teacher":
        return redirect(url_for("login_teacher"))
    return render_template("auth_options.html", role=role)

# Student signup/login 
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            age = request.form.get("age") or None
            grade = request.form.get("grade") or None
            accessibility = request.form.get("accessibility") or None
            email = request.form.get("email") or None
            phone = request.form.get("phone") or None
            password = request.form.get("password") or None

            if not name:
                flash("Name is required.")
                return redirect(request.url)

            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM students WHERE name = ?", (name,))
            if cur.fetchone():
                flash("A student with that name already exists.")
                conn.close()
                return redirect(url_for("index"))

            if not password:
                flash("Password is required.")
                conn.close()
                return redirect(request.url)

            password_hash = generate_password_hash(password)
            cur.execute("""
                INSERT INTO students (name, age, grade, accessibility, email, phone, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, age, grade, accessibility, email, phone, password_hash, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            flash("Student signed up successfully. Please login.")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"An error occurred during signup: {str(e)}")
            return redirect(request.url)
    return render_template("signup_student.html")

@app.route("/login/student", methods=["GET", "POST"])
def login_student():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            password = request.form.get("password", "")
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM students WHERE name = ?", (name,))
            user = cur.fetchone()
            conn.close()

            if not user:
                flash("Student not found. Please sign up.")
                return redirect(request.url)

            if user["password_hash"] and check_password_hash(user["password_hash"], password):
                session.clear()  # Clear any previous session data
                session["user"] = {"role": "student", "id": user["id"], "name": user["name"], "grade": user["grade"]}
                # Redirect to grade-specific dashboard for all grades
                if user["grade"] and user["grade"] in ["1", "2", "3", "4", "5"]:
                    return redirect(url_for(f"grade_{user['grade']}_dashboard"))
                else:
                    # For grades outside 1-5, redirect to general dashboard if needed
                    # Since we removed the general dashboard, redirect to grade 1 as default
                    return redirect_to_dashboard(session.get("user"))
            else:
                flash("Incorrect password.")
                return redirect(request.url)
        except Exception as e:
            flash(f"An error occurred during login: {str(e)}")
            return redirect(request.url)
    return render_template("login_student.html")


@app.route('/google/login/student')
def google_login_student():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        flash("Google login is not configured by the administrator.")
        return redirect(url_for('login_student'))
    
    # Create OAuth2 session
    google = OAuth2Session(
        client_id=GOOGLE_CLIENT_ID,
        scope=GOOGLE_SCOPES,
        redirect_uri=url_for('google_callback_student', _external=True)
    )
    
    # Generate authorization URL
    authorization_url, state = google.authorization_url(
        AUTHORIZATION_BASE_URL,
        access_type="offline",
        prompt="select_account"
    )
    
    # Store state in session for security
    session['oauth_state'] = state
    
    return redirect(authorization_url)


@app.route('/google/callback/student')
def google_callback_student():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        flash("Google login is not configured by the administrator.")
        return redirect(url_for('login_student'))
    
    try:
        # Create OAuth2 session with state for security
        google = OAuth2Session(
            client_id=GOOGLE_CLIENT_ID,
            state=session.get('oauth_state'),
            redirect_uri=url_for('google_callback_student', _external=True)
        )
        
        # Fetch token
        token = google.fetch_token(
            TOKEN_URL,
            authorization_response=request.url,
            client_secret=GOOGLE_CLIENT_SECRET
        )
        
        # Get user info
        user_info = google.get(USER_INFO_URL).json()
        
        # Extract user details
        email = user_info.get('email', '')
        name = user_info.get('name', user_info.get('given_name', 'Unknown'))
        google_id = user_info.get('id')
        picture_url = user_info.get('picture')
        
        conn = get_db()
        c = conn.cursor()
        
        # Check if user exists by google_id first, then by email
        # This handles cases where a user might have changed their email 
        # but already linked their Google account.
        c.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in c.fetchall()]
        
        user = None
        if 'google_id' in columns:
            c.execute("SELECT * FROM students WHERE google_id = ?", (google_id,))
            user = c.fetchone()
            
        if not user:
            c.execute("SELECT * FROM students WHERE email = ?", (email,))
            user = c.fetchone()
        
        if user:
            # Update Google ID if not already set or if it's different (link existing account)
            if 'google_id' in columns and (not user['google_id'] or user['google_id'] != google_id):
                c.execute("UPDATE students SET google_id = ? WHERE id = ?", (google_id, user['id']))
                conn.commit()
            
            # Also update email if it was found by google_id but the email is different
            if user['email'] != email:
                c.execute("UPDATE students SET email = ? WHERE id = ?", (email, user['id']))
                conn.commit()
            
            # Clear any existing session data to prevent conflicts
            session.clear()
            
            # Set new user session
            session['user'] = {
                'role': 'student', 
                'id': user['id'], 
                'name': user['name'], 
                'grade': user['grade']
            }
            conn.close()
            
            # Redirect to appropriate grade dashboard
            if user['grade'] and user['grade'] in ["1", "2", "3", "4", "5"]:
                return redirect(url_for(f"grade_{user['grade']}_dashboard"))
            else:
                return redirect_to_dashboard(session.get('user'))
        else:
            # Clear any existing session data to prevent conflicts
            session.clear()
            
            # User doesn't exist, redirect to complete profile
            session['pending_google_signup'] = {
                'email': email,
                'name': name,
                'google_id': google_id,
                'picture_url': picture_url
            }
            conn.close()
            return redirect(url_for('complete_profile_student'))
    
    except Exception as e:
        print(f"Google OAuth error: {str(e)}")
        flash("Google login failed. Please try again.")
        return redirect(url_for('login_student'))



# Teacher signup/login
@app.route("/signup/teacher", methods=["GET", "POST"])
def signup_teacher():
    # Disabled to prevent unauthorized access. Using pre-defined accounts instead.
    flash("Teacher signup is currently disabled. Please use your assigned credentials.")
    return redirect(url_for("index"))
    
    
    # Disabled to prevent unauthorized access. Using pre-defined accounts instead.
    # Note: master branch had a functional signup but we are keeping it disabled per recent cleanup.

@app.route("/login/teacher", methods=["GET", "POST"])
def login_teacher():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            password = request.form.get("password", "")
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM teachers WHERE name = ?", (name,))
            user = cur.fetchone()
            conn.close()

            if not user:
                flash("Teacher/Parent not found. Please sign up.")
                return redirect(request.url)

            if user["password_hash"] and check_password_hash(user["password_hash"], password):
                session.clear()  # Clear any previous session data
                session["user"] = {
                    "role": "teacher", 
                    "id": user["id"], 
                    "name": user["name"],
                    "grade": user["grade"] # Store teacher's grade
                }
                return redirect(url_for("teacher_dashboard"))
            else:
                flash("Incorrect password.")
                return redirect(request.url)
        except Exception as e:
            flash(f"An error occurred during login: {str(e)}")
            return redirect(request.url)
    return render_template("login_teacher.html")

@app.route("/complete-profile/student", methods=["GET","POST"])
def complete_profile_student():
    """Handle student profile completion after Google signup"""
    print(f"DEBUG: Profile completion route accessed. Session: {dict(session)}")
    print(f"DEBUG: Session user: {session.get('user')}")
    
    if request.method == "POST":
        # Read form data
        username = request.form.get("username")
        age = request.form.get("age")
        grade = request.form.get("grade")
        
        # Check if this is a Google signup (new user)
        pending_signup = session.get("pending_google_signup")
        
        if pending_signup:
            # This is a new user completing profile after Google signup
            conn = get_db()
            cur = conn.cursor()
            
            # Check if google_id column exists
            cur.execute("PRAGMA table_info(students)")
            columns = [col[1] for col in cur.fetchall()]
            
            if 'google_id' in columns:
                # Insert new student with google_id
                cur.execute(
                    "INSERT INTO students (name, age, grade, email, google_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (username, age, grade, pending_signup['email'], pending_signup['google_id'], datetime.now(timezone.utc).isoformat())
                )
            else:
                # Insert new student without google_id (for backward compatibility)
                cur.execute(
                    "INSERT INTO students (name, age, grade, email, created_at) VALUES (?, ?, ?, ?, ?)",
                    (username, age, grade, pending_signup['email'], datetime.now(timezone.utc).isoformat())
                )
            new_user_id = cur.lastrowid
            conn.commit()
            conn.close()
            
            # Clear the pending signup and set user session
            session.pop('pending_google_signup', None)
            session['user'] = {
                'role': 'student',
                'id': new_user_id,
                'name': username,
                'grade': grade
            }
            
            # Redirect to correct grade dashboard
            return redirect(url_for(f"grade_{grade}_dashboard"))
        else:
            # Existing user updating profile
            user_id = session.get("user", {}).get("id")
            if not user_id:
                flash("Session expired. Please login again.")
                return redirect(url_for("login_student"))
            
            # UPDATE students table
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE students SET name = ?, age = ?, grade = ? WHERE id = ?",
                (username, age, grade, user_id)
            )
            conn.commit()
            conn.close()
            
            # Update session with grade info
            session["user"]["grade"] = grade
            
            # Redirect to correct grade dashboard dynamically
            return redirect(url_for(f"grade_{grade}_dashboard"))
    
    # GET request - render template
    print("DEBUG: Rendering profile completion template")
    return render_template("complete_profile_student.html")

# Student Dashboard 
# Old general student dashboard removed - using grade-specific dashboards instead

# Grade-specific Dashboard Routes
# Grade-specific Dashboard Routes
@app.route("/dashboard/grade/1")
@login_required(role="student")
def grade_1_dashboard():
    user = session.get("user")
    if not user:
        flash("Please log in first.")
        return redirect(url_for("index"))
    
    ai_summary = session.get("summary")
    audio_file = session.get("audio_file")
    progress = get_student_progress(user["id"])
    return render_template(
        "grade_1_dashboard.html",
        user=user,
        ai_summary=ai_summary,
        audio_file=audio_file,
        hindi_file=session.get("hindi_file"),
        progress=progress
    )


@app.route("/static/alphabet_images/<filename>")
def serve_alphabet_image(filename):
    """Serve alphabet images, with fallback to SVG if PNG not found"""
    import os
    from flask import send_file, abort
    
    # Try PNG first
    png_path = os.path.join(app.root_path, "static", "alphabet_images", filename)
    if os.path.exists(png_path):
        return send_file(png_path)
    
    # Try SVG fallback
    svg_filename = filename.replace(".png", ".svg")
    svg_path = os.path.join(app.root_path, "static", "alphabet_images", svg_filename)
    if os.path.exists(svg_path):
        return send_file(svg_path, mimetype="image/svg+xml")
    
    # Default fallback image
    default_path = os.path.join(app.root_path, "static", "alphabet_images", "default.svg")
    return send_file(default_path, mimetype="image/svg+xml")


@app.route("/grade/1/creative_corner")
@login_required(role="student")
def creative_corner():
    return render_template("creative_corner.html")


@app.route("/grade/1/alphabets")
@login_required(role="student")
def grade_1_alphabets():
    try:
        user = session.get("user")
        return render_template("grade_1_alphabets_new.html", user=user)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for("index"))


@app.route("/grade/1/math")
@login_required(role="student")
def grade_1_math():
    try:
        user = session.get("user")
        return render_template("grade_1_math_new.html", user=user)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for("index"))


@app.route("/grade/1/flashcards")
@login_required(role="student")
def grade_1_flashcards():
    try:
        user = session.get("user")
        return render_template("grade_1_flashcards.html", user=user)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for("index"))


@app.route("/grade/1/shapes")
@login_required(role="student")
def grade_1_shapes():
    try:
        user = session.get("user")
        return render_template("grade_1_shapes.html", user=user)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for("index"))


@app.route("/grade/1/quiz")
@login_required(role="student")
def grade_1_quiz():
    try:
        user = session.get("user")
        return render_template("grade_1_quiz.html", user=user)
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for("index"))

# Grade-2 Subject Routes
@app.route("/grade/2/math")
@login_required(role="student")
def grade_2_math():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_math.html", user=user)

@app.route("/grade/2/sentences")
@login_required(role="student")
def grade_2_sentences():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_sentences.html", user=user)

@app.route("/grade/2/numbers")
@login_required(role="student")
def grade_2_numbers():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_numbers.html", user=user)

@app.route("/grade/2/plants")
@login_required(role="student")
def grade_2_plants():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_nature.html", user=user)

@app.route("/grade/2/reading")
@login_required(role="student")
def grade_2_reading():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_reading.html", user=user)

@app.route("/grade/2/reading_comprehension")
@login_required(role="student")
def grade_2_reading_comprehension():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_reading_comprehension.html", user=user)

@app.route("/grade/2/vocabulary_builder")
@login_required(role="student")
def grade_2_vocabulary_builder():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_vocabulary_builder.html", user=user)

@app.route("/grade/2/phonics_practice")
@login_required(role="student")
def grade_2_phonics_practice():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_phonics_practice.html", user=user)

@app.route("/grade/2/story_time")
@login_required(role="student")
def grade_2_story_time():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_story_time.html", user=user)

@app.route("/grade/2/science")
@login_required(role="student")
def grade_2_science():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_science.html", user=user)

# Grade 2 Science Topic Routes
@app.route("/grade/2/science/living_things")
@login_required(role="student")
def grade_2_living_things():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_living_things.html", user=user)

@app.route("/grade/2/science/weather")
@login_required(role="student")
def grade_2_weather():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_weather.html", user=user)

@app.route("/grade/2/science/matter")
@login_required(role="student")
def grade_2_matter():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_matter.html", user=user)

@app.route("/grade/2/science/simple_machines")
@login_required(role="student")
def grade_2_simple_machines():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_simple_machines.html", user=user)

@app.route("/grade/2/science/experiments")
@login_required(role="student")
def grade_2_science_experiments():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This content is for Grade 2 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_2_science_experiments.html", user=user)

# Grade-4 Subject Routes
@app.route("/grade/4/literature")
@login_required(role="student")
def grade_4_literature():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This content is for Grade 4 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_4_literature.html", user=user)

@app.route("/grade/4/math")
@login_required(role="student")
def grade_4_math():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This content is for Grade 4 students only.")
        return redirect_to_dashboard(session.get("user"))
    
    # Increment math progress
    student_id = user["id"] if user else None
    if student_id:
        update_progress(student_id, "math_solved")
    
    return render_template("grade_4_math.html", user=user)

@app.route("/grade/4/science")
@login_required(role="student")
def grade_4_science():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This content is for Grade 4 students only.")
        return redirect_to_dashboard(session.get("user"))
    
    # Increment science progress
    student_id = user["id"] if user else None
    if student_id:
        update_progress(student_id, "science_done")
    
    return render_template("grade_4_science.html", user=user)

@app.route("/grade/4/writing")
@login_required(role="student")
def grade_4_writing():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This content is for Grade 4 students only.")
        return redirect_to_dashboard(session.get("user"))
    
    # Increment creative writing progress
    student_id = user["id"] if user else None
    if student_id:
        update_progress(student_id, "creative_done")
    
    return render_template("grade_4_writing.html", user=user)

@app.route('/ai-correct', methods=['POST'])
@login_required(role='student')
def ai_correct():
    data = request.get_json()
    text = data.get('text', '')
    
    if not text.strip():
        return {'error': 'No text provided'}, 400
    
    try:
        # Call OpenAI API for grammar correction
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Correct grammar, improve clarity for a Grade-4 student. Return: 1. Corrected sentence 2. One short encouraging feedback line.\n\nOriginal text: {text}"
            }],
            temperature=0.3,
            max_tokens=200
        )
        
        result = response.choices[0].message.content
        # Parse the AI response to extract corrected text and feedback
        lines = result.split('\n')
        corrected = lines[0] if lines else text
        feedback = lines[1] if len(lines) > 1 else "Great job writing!"
        
        # Clean up the corrected text
        if corrected.startswith('1.'):
            corrected = corrected[2:].strip()
        
        if feedback.startswith('2.'):
            feedback = feedback[2:].strip()
        elif feedback.startswith('Feedback:'):
            feedback = feedback[9:].strip()
        
        return {'corrected': corrected, 'feedback': feedback}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/ai-tts', methods=['POST'])
@login_required(role='student')
def ai_tts():
    data = request.get_json()
    text = data.get('text', '')
    
    if not text.strip():
        return {'error': 'No text provided'}, 400
    
    try:
        # Call OpenAI TTS API
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # Use a friendly voice for kids
            input=text
        )
        
        # Save audio to temporary file and return path
        import tempfile
        import uuid
        temp_filename = f"temp_audio_{uuid.uuid4().hex}.mp3"
        temp_path = os.path.join('static', 'audio', temp_filename)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        
        response.stream_to_file(temp_path)
        
        return {'audio_url': f'/static/audio/{temp_filename}'}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/progress-summary')
@login_required(role='student')
def progress_summary():
    user = session.get('user')
    student_id = user['id'] if user else None
    
    if not student_id:
        return {'error': 'User not authenticated'}, 401
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Get total entries
        c.execute("SELECT COUNT(*) FROM writing_progress WHERE student_id = ?", (str(student_id),))
        total_entries = c.fetchone()[0]
        
        # Get average word count
        c.execute("SELECT AVG(word_count) FROM writing_progress WHERE student_id = ?", (str(student_id),))
        avg_word_count = c.fetchone()[0] or 0
        
        # Get longest entry
        c.execute("SELECT MAX(word_count) FROM writing_progress WHERE student_id = ?", (str(student_id),))
        longest_entry_words = c.fetchone()[0] or 0
        
        # Get current streak
        c.execute("SELECT streak_count FROM writing_streak WHERE student_id = ?", (str(student_id),))
        streak_row = c.fetchone()
        streak_count = streak_row[0] if streak_row else 0
        
        conn.close()
        
        return {
            'total_entries': total_entries,
            'average_word_count': round(avg_word_count),
            'longest_entry_words': longest_entry_words,
            'streak_count': streak_count
        }
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/save-writing-progress', methods=['POST'])
@login_required(role='student')
def save_writing_progress():
    user = session.get('user')
    student_id = user['id'] if user else None
    
    if not student_id:
        return {'error': 'User not authenticated'}, 401
    
    data = request.get_json()
    text = data.get('text', '')
    word_count = len(text.split()) if text.strip() else 0
    
    if not text.strip():
        return {'error': 'No text provided'}, 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Insert writing progress
        c.execute("INSERT INTO writing_progress (student_id, text, word_count) VALUES (?, ?, ?)",
                 (str(student_id), text, word_count))
        
        # Update streak
        from datetime import date
        today = date.today().isoformat()
        
        # Check if user has streak record
        c.execute("SELECT last_date, streak_count FROM writing_streak WHERE student_id = ?", (str(student_id),))
        streak_row = c.fetchone()
        
        if streak_row:
            last_date_str, current_streak = streak_row
            last_date = date.fromisoformat(last_date_str) if last_date_str else None
            today_date = date.today()
            
            if last_date:
                # Calculate difference in days
                day_diff = (today_date - last_date).days
                
                if day_diff == 1:
                    # Consecutive day, increment streak
                    new_streak = current_streak + 1
                elif day_diff == 0:
                    # Same day, keep same streak
                    new_streak = current_streak
                else:
                    # More than one day gap, reset to 1
                    new_streak = 1
            else:
                new_streak = 1
            
            # Update streak
            c.execute("UPDATE writing_streak SET last_date = ?, streak_count = ? WHERE student_id = ?",
                     (today, new_streak, str(student_id)))
        else:
            # Create new streak record
            c.execute("INSERT INTO writing_streak (student_id, last_date, streak_count) VALUES (?, ?, ?)",
                     (str(student_id), today, 1))
        
        conn.commit()
        conn.close()
        
        return {'success': True, 'streak_count': new_streak if 'new_streak' in locals() else 1}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route("/grade/4/phonics")
@login_required(role="student")
def grade_4_phonics():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This content is for Grade 4 students only.")
        return redirect(url_for("grade_4_dashboard"))
    return render_template("grade_4_phonics.html", user=user)

@app.route("/grade/4/reading")
@login_required(role="student")
def grade_4_reading():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This content is for Grade 4 students only.")
        return redirect_to_dashboard(session.get("user"))
    
    # Increment reading progress
    student_id = user["id"] if user else None
    if student_id:
        update_progress(student_id, "books_analyzed")
    
    return render_template("grade_4_reading.html", user=user)


@app.route("/api/alphabet_info", methods=["POST"])
@login_required(role="student")
def get_alphabet_info():
    """Get detailed alphabet information using OpenAI"""
    try:
        data = request.get_json()
        letter = data.get("letter", "").upper()
        
        if not letter or len(letter) != 1 or not letter.isalpha():
            return {"error": "Invalid letter"}, 400
        
        # Use OpenAI to generate educational content for the letter
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful educational assistant for teaching Grade 1 children. Provide simple, engaging content for alphabet learning. Always suggest age-appropriate words that children know."
                },
                {
                    "role": "user",
                    "content": f"Create educational content for the letter '{letter}' in the following JSON format: {{'word_example': 'a simple Grade 1 appropriate word starting with {letter} (like Apple, Ball, Cat, etc.)', 'description': 'a short description of the letter sound', 'fun_fact': 'an interesting fact about this letter for children'}}"
                }
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        content = response.choices[0].message.content.strip()
        
        # Try to parse as JSON, fallback to manual parsing if needed
        try:
            import json
            alphabet_info = json.loads(content)
        except:
            # Manual parsing fallback - ensure proper word for each letter
            word_examples = {
                "A": "Apple", "B": "Ball", "C": "Cat", "D": "Dog", "E": "Elephant",
                "F": "Fish", "G": "Giraffe", "H": "House", "I": "Ice Cream", "J": "Jump",
                "K": "Kite", "L": "Lion", "M": "Monkey", "N": "Nest", "O": "Orange",
                "P": "Pig", "Q": "Queen", "R": "Rabbit", "S": "Sun", "T": "Tiger",
                "U": "Umbrella", "V": "Van", "W": "Window", "X": "Xylophone", "Y": "Yellow", "Z": "Zebra"
            }
            alphabet_info = {
                "word_example": word_examples.get(letter, f"{letter}pple"),
                "description": f"The letter {letter} makes a '{letter.lower()}uh' sound",
                "fun_fact": f"The letter {letter} is number {ord(letter) - ord('A') + 1} in the alphabet!"
            }
        
        return alphabet_info
        
    except Exception as e:
        print(f"Error getting alphabet info: {e}")
        # Return fallback content with proper word mapping
        word_examples = {
            "A": "Apple", "B": "Ball", "C": "Cat", "D": "Dog", "E": "Elephant",
            "F": "Fish", "G": "Giraffe", "H": "House", "I": "Ice Cream", "J": "Jump",
            "K": "Kite", "L": "Lion", "M": "Monkey", "N": "Nest", "O": "Orange",
            "P": "Pig", "Q": "Queen", "R": "Rabbit", "S": "Sun", "T": "Tiger",
            "U": "Umbrella", "V": "Van", "W": "Window", "X": "Xylophone", "Y": "Yellow", "Z": "Zebra"
        }
        return {
            "word_example": word_examples.get(letter, f"{letter}pple"),
            "description": f"The letter {letter} makes a '{letter.lower()}uh' sound",
            "fun_fact": f"The letter {letter} is number {ord(letter) - ord('A') + 1} in the alphabet!"
        }


@app.route("/api/check_pronunciation", methods=["POST"])
@login_required(role="student")
def check_pronunciation():
    """API endpoint to check pronunciation of letters/words using OpenAI"""
    try:
        data = request.get_json()
        target_word = data.get("word", "").lower().strip()
        recorded_audio = data.get("audio", "")  # In a real implementation, this would be the audio data
        
        # Use OpenAI to evaluate pronunciation
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a pronunciation expert for children's education. Evaluate how well a student pronounced a letter or word and provide encouraging feedback."
                },
                {
                    "role": "user",
                    "content": f"A student tried to pronounce '{target_word}'. Provide feedback in this JSON format: {{'accuracy': a number between 60-100, 'is_correct': true/false, 'feedback': 'encouraging feedback message'}}"
                }
            ],
            temperature=0.7,
            max_tokens=150
        )
        
        feedback_content = response.choices[0].message.content.strip()
        
        # Parse the response
        try:
            import json
            import re
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', feedback_content, re.DOTALL)
            if json_match:
                feedback_data = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found")
        except:
            # Fallback response
            feedback_data = {
                "accuracy": 85,
                "is_correct": True,
                "feedback": f"Great job! Your pronunciation of '{target_word}' was excellent!"
            }
        
        return {
            "success": True,
            "accuracy": feedback_data.get("accuracy", 80),
            "is_correct": feedback_data.get("is_correct", True),
            "feedback": feedback_data.get("feedback", f"Good effort! Keep practicing '{target_word}'.")
        }
    except Exception as e:
        print(f"Error in pronunciation check: {e}")
        return {"success": False, "error": str(e)}, 500

@app.route("/dashboard/grade/2")
@login_required(role="student")
def grade_2_dashboard():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This dashboard is for Grade 2 students only.")
        # Redirect user to their actual grade dashboard
        if user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
            return redirect(url_for(f"grade_{user['grade']}_dashboard"))
        else:
            return redirect_to_dashboard(session.get("user"))
    
    ai_summary = session.get("summary")
    audio_file = session.get("audio_file")
    progress = get_student_progress(user["id"])
    return render_template(
        "grade_2_dashboard.html",
        user=user,
        ai_summary=ai_summary,
        audio_file=audio_file,
        hindi_file=session.get("hindi_file"),
        progress=progress
    )



@app.route("/dashboard/grade/3")
@login_required(role="student")
def grade_3_dashboard():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied. This dashboard is for Grade 3 students only.")
        # Redirect user to their actual grade dashboard
        if user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
            return redirect(url_for(f"grade_{user['grade']}_dashboard"))
        else:
            return redirect_to_dashboard(session.get("user"))
    
    ai_summary = session.get("summary")
    audio_file = session.get("audio_file")
    
    progress = get_student_progress(user["id"])
    
    return render_template(
        "grade_3_dashboard.html",
        user=user,
        ai_summary=ai_summary,
        audio_file=audio_file,
        hindi_file=session.get("hindi_file"),
        progress=progress
    )


@app.route("/grade/3/grammar")
@login_required(role="student")
def grade_3_grammar():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied. This content is for Grade 3 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_3_grammar.html", user=user)

@app.route("/api/grade3/generate_grammar", methods=["GET"])
@login_required(role="student")
def generate_grade3_grammar():
    try:
        prompt = """
        Generate 5 'Fill in the Blanks' questions and 5 'Sentence Builder' puzzles for a 3rd-grade grammar practice.
        
        Return strictly JSON with this structure:
        {
            "blanks": [
                { "text": "The ______ cat sleeps.", "answers": ["big"], "options": [["big", "small"]] }
            ],
            "sentences": [
                { "words": ["The", "cat", "sleeps"], "correct": "The cat sleeps" }
            ]
        }
        
        Constraints:
        - Blanks: Use simple adjectives/verbs. 'options' must contain the correct answer and 1 distractor.
        - Sentences: 4-6 words max. simple sentences.
        - Randomize the content every time.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=1000
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"error": "Failed to generate questions"}
            
    except Exception as e:
        print(f"Grammar generation error: {e}")
        return {"error": str(e)}, 500



def get_math_questions_logic():
    try:
        # Improved for higher variety and specific Grade 3 constraints
        prompt = """
        Generate 5 unique, fun questions FOR EACH category for Grade 3 Math.
        IMPORTANT: Randomize all numbers and items (names, objects). 
        Return ONLY valid JSON.
        
        Categories:
        1. "time": Matching daily activities to AM/PM hours.
           JSON: {"activity": "string", "icon": "emoji", "correct": "H:00 AM/PM", "options": ["H:00 AM/PM", "H:00 AM/PM"]}
           Example: {"activity": "Breakfast Time", "icon": "🥣", "correct": "8:00 AM", "options": ["8:00 AM", "8:00 PM"]}
        2. "shapes": Identifying basic 2D shapes (Circle, Square, Triangle, Star).
           JSON: {"clue": "Which one is a [Shape]?", "correct": "ShapeName", "options": ["Shape1", "Shape2", "Shape3"]}
        3. "fractions": Basic recognition (Half 1/2, Third 1/3, Quarter 1/4).
           JSON: {"clue": "Which fraction means half?", "correct": "1/2", "options": ["1/2", "1/4", "1/3"]}
        4. "word_problems": Very simple addition/subtraction under 20.
           JSON: {"text": "I have 5 apples and get 3 more. How many?", "correct": "8", "options": ["7", "8", "9"]}
        
        Return JSON structure:
        {
            "time": [...],
            "shapes": [...],
            "fractions": [...],
            "word_problems": [...]
        }
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0, # Higher temperature for more variety
            max_tokens=2000
        )
        
        content = response.choices[0].message.content
        import json, re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"error": "Failed to generate math questions"}
            
    except Exception as e:
        print(f"Math generation error: {e}")
        return {"error": str(e)}

def get_food_questions_logic():
    try:
        # Optimized for speed: requesting 3 questions each
        prompt = """
        Generate 3 Grade 3 Food questions for a dyslexic student.
        IMPORTANT: Randomize the items and questions every time.
        
        Return STRICT JSON:
        {
            "sorting": [
                {"item": "Apple", "category": "Fruits", "options": ["Fruits", "Vegetables", "Grains"]}
            ],
            "healthy": [
                {"text": "Which is good?", "correct": "Apple", "options": ["Apple", "Candy"]}
            ]
        }
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=1000  # Increased for safety
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"error": "Failed to generate food questions"}
            
    except Exception as e:
        print(f"Food generation error: {e}")
        return {"error": str(e)}

@app.route("/api/grade3/generate_math", methods=["GET"])
@login_required(role="student")
def generate_grade3_math():
    return get_math_questions_logic()

@app.route("/api/grade3/generate_food", methods=["GET"])
@login_required(role="student")
def generate_grade3_food():
    return get_food_questions_logic()

@app.route("/grade/3/math")
@login_required(role="student")
def grade_3_math():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied. This content is for Grade 3 students only.")
        return redirect_to_dashboard(session.get("user"))
    
    # SSR: Fetch initial questions
    initial_data = get_math_questions_logic()
    return render_template("grade_3_math.html", user=user, initial_data=initial_data)

@app.route("/grade/3/food")
@login_required(role="student")
def grade_3_food():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied. This content is for Grade 3 students only.")
        return redirect_to_dashboard(session.get("user"))
        
    # SSR: Fetch initial questions
    initial_data = get_food_questions_logic()
    return render_template("grade_3_food.html", user=user, initial_data=initial_data)

# --- New Grade 3 Logic ---

def get_shelter_questions_logic():
    try:
        prompt = """
        Generate 5 unique questions FOR EACH category for Grade 3 Shelter/Homes.
        IMPORTANT: Use a wide variety of household items and home types. Randomize every time.
        
        Categories:
        1. "rooms": Identify the room for a specific object (e.g., Mirror, Toaster, Sofa, Shower, Lawn mower).
           JSON: {"clue": "string", "correct": "string", "options": ["string", "string", "string"]}
        2. "homes": Identify if a home is for an Animal or a Human (e.g., Igloo, Kennel, Caravan, Burrow, Lighthouse).
           JSON: {"clue": "string", "correct": "string", "options": ["string", "string", "string"]}
        
        Return JSON:
        {
            "rooms": [...],
            "homes": [...]
        }
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0, # High variety
            max_tokens=1500
        )
        content = response.choices[0].message.content
        import json, re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(json_match.group()) if json_match else {"error": "Failed"}
    except Exception as e:
        print(f"Shelter error: {e}")
        return {"error": str(e)}

def get_logic_questions_logic():
    try:
        prompt = """
        Generate Grade 3 Logic Puzzles in JSON format.
        1. Patterns: sequence of 3 items, user guesses 4th. (e.g., "🔴", "🔵", "🔴", "?").
        2. Odd One Out: 4 items, 1 doesn't belong.
        3. Analogies: "A is to B as C is to ?".
        
        Return JSON:
        {
            "patterns": [ {"sequence": ["🔺", "🟦", "🔺"], "correct": "🟦", "options": ["🟦", "🟢"]} ],
            "odd_one_out": [ {"correct": "Car", "options": ["Apple", "Banana", "Car", "Grape"]} ],
            "analogies": [ {"pair1": "Bird", "pair2": "Fly", "target": "Fish", "correct": "Swim", "options": ["Swim", "Walk"]} ]
        }
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=1000
        )
        content = response.choices[0].message.content
        import json, re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(json_match.group()) if json_match else {"error": "Failed"}
    except Exception as e:
        print(f"Logic error: {e}")
        return {"error": str(e)}

def get_transport_questions_logic():
    try:
        prompt = """
        Generate a list of 5 unique, fun transport items for a Drag-and-Drop sorting game for Grade 3.
        IMPORTANT: Use a mix of common and interesting vehicles. 
        Categories: "Land", "Water", "Air".
        
        Return JSON:
        {
            "items": [
                {"name": "Kayak", "category": "Water", "emoji": "🛶"},
                {"name": "Scooter", "category": "Land", "emoji": "🛴"},
                {"name": "Glider", "category": "Air", "emoji": "🛩️"}
            ]
        }
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=1500
        )
        content = response.choices[0].message.content
        import json, re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(json_match.group()) if json_match else {"error": "Failed"}
    except Exception as e:
        print(f"Transport error: {e}")
        return {"error": str(e)}

def get_science_questions_logic():
    try:
        prompt = """
        Generate 5 unique questions FOR EACH category for Grade 3 Science/Nature.
        IMPORTANT: Use interesting and diverse objects. Randomize every time.
        
        Categories:
        1. "sink_float": Sink or Float? (e.g., Pinecone, Lego brick, Silver spoon, Cork, Watermelon).
           JSON: {"clue": "string", "correct": "string", "options": ["Sink", "Float", "Both?"]}
        2. "senses": Which sense do you use to detect this property? (e.g., Heat of a fire, Roughness of sandpaper, Scent of vanilla).
           JSON: {"clue": "string", "correct": "string", "options": ["Eyes", "Ears", "Nose", "Tongue", "Skin/Touch"]}
        
        Return JSON:
        {
            "sink_float": [...],
            "senses": [...]
        }
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=1500
        )
        content = response.choices[0].message.content
        import json, re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(json_match.group()) if json_match else {"error": "Failed"}
    except Exception as e:
        print(f"Science error: {e}")
        return {"error": str(e)}

def get_art_idea_logic():
    try:
        prompt = "Generate a fun, simple, and creative drawing idea for a Grade 3 student. Return JSON: {'idea': '...'}"
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=100
        )
        content = response.choices[0].message.content
        import json, re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(json_match.group()) if json_match else {"idea": "Draw a futuristic city!"}
    except Exception as e:
        print(f"Art error: {e}")
        return {"idea": "Draw your favorite animal superhero!"}

# --- API Endpoints ---

@app.route("/api/grade3/generate_shelter")
@login_required(role="student")
def generate_grade3_shelter(): return get_shelter_questions_logic()

@app.route("/api/grade3/generate_logic")
@login_required(role="student")
def generate_grade3_logic(): return get_logic_questions_logic()

@app.route("/api/grade3/generate_transport")
@login_required(role="student")
def generate_grade3_transport(): return get_transport_questions_logic()

@app.route("/api/grade3/generate_science")
@login_required(role="student")
def generate_grade3_science(): return get_science_questions_logic()

@app.route("/api/grade3/generate_art_idea")
@login_required(role="student")
def generate_grade3_art_idea(): return get_art_idea_logic()

# --- Routes with SSR ---

@app.route("/grade/3/logic")
@login_required(role="student")
def grade_3_logic():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied.")
        return redirect_to_dashboard(session.get("user"))
    initial_data = get_logic_questions_logic()
    return render_template("grade_3_logic.html", user=user, initial_data=initial_data)

@app.route("/grade/3/science")
@login_required(role="student")
def grade_3_science():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied.")
        return redirect_to_dashboard(session.get("user"))
    # Fetch initial data for the default tab (Science/Nature)
    initial_data = get_science_questions_logic()
    return render_template("grade_3_science.html", user=user, initial_data=initial_data)

@app.route("/grade/3/art")
@login_required(role="student")
def grade_3_art():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied. This content is for Grade 3 students only.")
        return redirect_to_dashboard(session.get("user"))
    return render_template("grade_3_art.html", user=user)

@app.route("/dashboard/grade/4")
@login_required(role="student")
def grade_4_dashboard():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This dashboard is for Grade 4 students only.")
        # Redirect user to their actual grade dashboard
        if user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
            return redirect(url_for(f"grade_{user['grade']}_dashboard"))
        else:
            return redirect_to_dashboard(session.get("user"))
    
    # Get real progress data for the student
    progress = get_student_progress(user["id"])
    
    ai_summary = session.get("summary")
    audio_file = session.get("audio_file")
    return render_template(
        "grade_4_dashboard.html",
        user=user,
        progress=progress,
        ai_summary=ai_summary,
        audio_file=audio_file,
        hindi_file=session.get("hindi_file")
    )


@app.route("/dashboard/grade/5")
@login_required(role="student")
def grade_5_dashboard():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This dashboard is for Grade 5 students only.")
        # Redirect user to their actual grade dashboard
        if user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
            return redirect(url_for(f"grade_{user['grade']}_dashboard"))
        else:
            return redirect_to_dashboard(session.get("user"))
    
    ai_summary = session.pop("summary", None)
    audio_file = session.pop("audio_file", None)

    # Fetch Progress Data
    progress = get_student_progress(user["id"])
    
    return render_template(
        "grade_5_dashboard.html",
        user=user,
        ai_summary=ai_summary,
        audio_file=audio_file,
        hindi_file=session.pop("hindi_file", None),
        progress=progress
    )


# Helper function for Grade 5 progress
def update_grade5_progress(student_id, activity_type):
    # First ensure the migration has run
    migrate_student_progress_table()
    
    # Unified recording for dynamic dashboard
    q_map = {
        "grade_5_math": "g5_math_problems",
        "grade_5_location": "g5_science_innovation", 
        "grade_5_paragraph": "g5_logic_leadership"
    }
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Unified system record
        quiz_id = q_map.get(activity_type, f"g5_{activity_type}")
        c.execute("""
            INSERT INTO quiz_attempts (student_id, quiz_id, score, total, attempted_at)
            VALUES (?, ?, ?, ?, ?)
        """, (student_id, quiz_id, 1, 1, datetime.now(timezone.utc).isoformat()))

        # Legacy update
        field_mapping = {
            "grade_5_math": "math_solved",
            "grade_5_location": "science_done", 
            "grade_5_paragraph": "creative_done"
        }
        
        subject_field = field_mapping.get(activity_type, "creative_done")
        
        c.execute(f"SELECT {subject_field} FROM student_progress WHERE student_id = ? AND grade = 5", (student_id,))
        row = c.fetchone()
        
        if row:
            c.execute(f"UPDATE student_progress SET {subject_field} = {subject_field} + 1, last_updated = CURRENT_TIMESTAMP WHERE student_id = ? AND grade = 5", (student_id,))
        else:
            c.execute(f"INSERT INTO student_progress (student_id, grade, {subject_field}) VALUES (?, 5, 1)", (student_id,))
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating grade 5 progress: {e}")


# Grade 5 Feature Routes

@app.route("/grade/5/paragraph_writing")
@login_required(role="student")
def grade_5_paragraph_writing():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This content is for Grade 5 students only.")
        return redirect(url_for("grade_5_dashboard"))
    return render_template("grade_5_paragraph.html", user=user)

@app.route("/grade/5/vocab_builder")
@login_required(role="student")
def grade_5_vocab_builder():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This content is for Grade 5 students only.")
        return redirect(url_for("grade_5_dashboard"))
    return render_template("grade_5_vocab.html", user=user)

@app.route("/grade/5/math_problems")
@login_required(role="student")
def grade_5_math_problems():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This content is for Grade 5 students only.")
        return redirect(url_for("grade_5_dashboard"))
    return render_template("grade_5_math.html", user=user)

@app.route("/grade/5/location_learning")
@login_required(role="student")
def grade_5_location_learning():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This content is for Grade 5 students only.")
        return redirect(url_for("grade_5_dashboard"))
    
    # diverse locations with approximate coordinates on a standard world map
    all_locations = [
        {"name": "North America", "top": 30, "left": 20, "color": "bg-red-500", "icon": "fas fa-star"},
        {"name": "Amazon Rainforest", "top": 65, "left": 28, "color": "bg-green-600", "icon": "fas fa-tree"},
        {"name": "Sahara Desert", "top": 50, "left": 53, "color": "bg-yellow-500", "icon": "fas fa-sun"},
        {"name": "Paris, France", "top": 28, "left": 49, "color": "bg-purple-500", "icon": "fas fa-landmark"}, # Adjusted
        {"name": "Great Wall of China", "top": 35, "left": 70, "color": "bg-orange-500", "icon": "fas fa-dragon"},
        {"name": "Great Barrier Reef", "top": 70, "left": 85, "color": "bg-cyan-500", "icon": "fas fa-fish"},
        {"name": "Pyramids of Giza", "top": 42, "left": 55, "color": "bg-yellow-600", "icon": "fas fa-gopuram"},
        {"name": "Taj Mahal, India", "top": 45, "left": 68, "color": "bg-pink-500", "icon": "fas fa-monument"},
        {"name": "Statue of Liberty, USA", "top": 32, "left": 22, "color": "bg-blue-500", "icon": "fas fa-flag-usa"},
        {"name": "Sydney Opera House", "top": 78, "left": 88, "color": "bg-indigo-500", "icon": "fas fa-music"},
        {"name": "Mount Everest", "top": 38, "left": 72, "color": "bg-gray-500", "icon": "fas fa-mountain"},
        {"name": "Machu Picchu, Peru", "top": 68, "left": 26, "color": "bg-emerald-600", "icon": "fas fa-ruins"},
        {"name": "Colosseum, Rome", "top": 31, "left": 51, "color": "bg-rose-500", "icon": "fas fa-archway"},
        {"name": "Christ the Redeemer, Brazil", "top": 72, "left": 32, "color": "bg-teal-500", "icon": "fas fa-praying-hands"},
        {"name": "Madagascar", "top": 65, "left": 60, "color": "bg-lime-500", "icon": "fas fa-paw"},
        {"name": "Greenland", "top": 10, "left": 35, "color": "bg-white border-gray-300", "icon": "fas fa-snowflake"},
        {"name": "Tokyo, Japan", "top": 36, "left": 82, "color": "bg-red-600", "icon": "fas fa-torii-gate"},
        {"name": "London, UK", "top": 24, "left": 48, "color": "bg-blue-700", "icon": "fas fa-crown"},
        {"name": "Moscow, Russia", "top": 20, "left": 60, "color": "bg-red-700", "icon": "fas fa-church"},
        {"name": "Cape Town, South Africa", "top": 80, "left": 55, "color": "bg-orange-400", "icon": "fas fa-umbrella-beach"}
    ]
    
    import random
    # Select 5 random locations
    selected_locations = random.sample(all_locations, 5)
    
    return render_template("grade_5_location.html", user=user, locations=selected_locations)

# API Endpoints for Grade 5 Features

@app.route("/api/grade5/check_paragraph", methods=["POST"])
@login_required(role="student")
def check_paragraph():
    # Quota log
    check_and_update_quota(session["user"]["id"])
    try:
        data = request.get_json()
        paragraph = data.get("paragraph", "")
        topic = data.get("topic", "General")
        
        if not paragraph:
            return {"error": "No paragraph provided"}, 400

        prompt = f"""
        Analyze the following paragraph written by a 5th-grade student about '{topic}'.
        Paragraph: "{paragraph}"
        
        Provide feedback in JSON format:
        {{
            "score": number (1-10),
            "grammar_feedback": "string",
            "creativity_feedback": "string",
            "improvement_tips": ["tip1", "tip2"]
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        # Extract JSON
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            # Update Progress
            update_grade5_progress(session["user"]["id"], "grade_5_paragraph")
            return json.loads(json_match.group())
        else:
            return {"error": "Failed to parse AI response"}
            
    except Exception as e:
        print(f"Error checking paragraph: {e}")
        return {"error": str(e)}, 500

@app.route("/grade/5/history_learning")
@login_required(role="student")
def grade_5_history_learning():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This content is for Grade 5 students only.")
        return redirect(url_for("grade_5_dashboard"))
    
    selected_era = request.args.get("era")
    
    if not selected_era:
        # Show selection screen if no era is chosen
        return render_template("grade_5_history_select.html", user=user)
    
    try:
        prompt = f"""
        You are a time-travel guide for a 5th-grade student (10-11 years old).
        Generate engaging, age-appropriate historical content about the era: '{selected_era}'.
        
        Guidelines:
        - Use simple, exciting storytelling language.
        - Avoid complex political or economic details.
        - Focus on daily life, famous inventions, or cool facts.
        - Keep the 'fun_fact' short and surprising.
        
        Return JSON:
        {{
            "title": "Creative Title for the Era",
            "icon": "font-awesome-icon-class (e.g., fas fa-crown)",
            "description": "2-3 sentences description of what life was like, easy to read.",
            "timeline": [
                {{"year": "Year", "event": "Simple event description"}},
                {{"year": "Year", "event": "Another simple event"}}
            ],
            "fun_fact": "Did you know? [Interesting fact]"
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            history_data = json.loads(json_match.group())
        else:
            # Fallback
            history_data = {
                "title": selected_era,
                "icon": "fas fa-history",
                "description": "Explore the wonders of history!",
                "timeline": [{"year": "Long ago", "event": "Something amazing happened."}],
                "fun_fact": "History is full of surprises!"
            }
            
    except Exception as e:
        print(f"History Gen Error: {e}")
        history_data = {
            "title": "Time Travel Error",
            "icon": "fas fa-exclamation-triangle",
            "description": "The time machine hit a bump! Try again.",
            "timeline": [],
            "fun_fact": "Sometimes even time machines need a break."
        }

    return render_template("grade_5_history.html", user=user, data=history_data)

@app.route("/grade/5/multiplication")
@login_required(role="student")
def grade_5_multiplication():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This content is for Grade 5 students only.")
        return redirect(url_for("grade_5_dashboard"))
    return render_template("grade_5_multiplication.html", user=user)

@app.route("/api/grade5/get_vocab_word", methods=["GET"])
@login_required(role="student")
def get_vocab_word():
    try:
        subject = request.args.get("subject", "General")
        
        prompt = f"""
        Generate a challenging but age-appropriate vocabulary word for a 5th grader related to the subject: '{subject}'.
        
        Examples:
        - History: Civilization, Empire, Artifact
        - Science: Photosynthesis, Gravity, Ecosystem
        - Geography: Continent, Equator, Climate
        - English: Metaphor, Narrative, Synonym
        
        Return JSON: {{'word': '...', 'definition': '...', 'example_sentence': '...', 'synonyms': ['...'], 'antonyms': ['...']}}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            # Update Progress
            update_grade5_progress(session["user"]["id"], "grade_5_vocab")
            return json.loads(json_match.group())
        else:
            return {"error": "Failed to generate word"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/api/grade5/check_math", methods=["POST"])
@login_required(role="student")
def check_math():
    try:
        data = request.get_json()
        problem = data.get("problem", "")
        student_answer = data.get("answer", "")
        
        prompt = f"""
        You are a helpful and encouraging math tutor for a 5th-grade student.
        
        Math Problem: "{problem}"
        Student's Answer: "{student_answer}"
        
        Instructions:
        1. Solve the problem yourself first to determine the correct numerical answer.
        2. Check if the student's answer matches the correct answer.
        3. ACCEPT answers that show the full equation (e.g., "50 - 45 = 5") as long as the final result is correct.
        4. IGNORE standard formatting differences (e.g., "$5" vs "5" vs "5.00").
        5. If the student provides the correct logical steps but makes a minor typo, provide a helpful hint in the explanation but you may mark it incorrect if the final number is wrong.
        6. If the answer is correct, "is_correct" MUST be true.
        
        Return JSON:
        {{
            "is_correct": boolean,
            "correct_answer": "string",
            "explanation": "string (brief, helpful explanation)",
            "encouragement": "string"
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            # Update Progress if correct
            if result.get("is_correct"):
                 update_grade5_progress(session["user"]["id"], "grade_5_math")
            return result
        else:
            return {"error": "Failed to check answer"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/api/grade5/location_info", methods=["POST"])
@login_required(role="student")
def location_info():
    try:
        data = request.get_json()
        location_name = data.get("location", "")
        
        prompt = f"""
        Provide 3 fun, educational facts about {location_name} suitable for a 5th-grade student with dyslexia. 
        Use simple language, short sentences, and bullet points.
        Return JSON:
        {{
            "location": "{location_name}",
            "facts": ["fact1", "fact2", "fact3"],
            "climate": "short description",
            "famous_for": "short description"
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            # Update Progress
            update_grade5_progress(session["user"]["id"], "grade_5_location")
            return json.loads(json_match.group())
        else:
            return {"error": "Failed to get location info"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/api/grade5/get_math_problem", methods=["GET"])
@login_required(role="student")
def get_math_problem():
    try:
        prompt = """
        Generate a strictly age-appropriate math word problem for a standard 5th grader (approx. 10-11 years old).
        
        Use one of these specific 5th-grade topics:
        1. Multi-digit multiplication or division (e.g., 345 x 12 or 120 / 4).
        2. Adding/Subtracting fractions with unlike denominators (e.g., 1/2 + 1/3).
        3. Decimals (adding, subtracting, or multiplying simple decimals like money).
        4. Volume of rectangular prisms.
        5. Real-world scenarios involving Time or Money.
        
        Avoid overly complex logic. Ensure the numbers are clean and the answer is a whole number or simple decimal/fraction.
        Keep the text clear, encouraging, and concise (1-3 sentences).
        
        Return JSON:
        {
            "problem": "The text of the word problem."
        }
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9
        )
        
        content = response.choices[0].message.content
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"problem": "A baker has 24 cookies and wants to share them equally among 4 friends. How many cookies does each friend get?"} # Fallback
            
    except Exception as e:
        print(f"Error generating problem: {e}")
        return {"problem": "Tom has 15 apples. He gives 5 to Jerry. How many apples does Tom have left?"} # Fallback

@app.route("/upload_textbook", methods=["POST"])
@login_required(role="student")
def upload_textbook():
    if "textbook" not in request.files:
        flash("No file selected.")
        user = session.get("user")
        if user and user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
            return redirect(url_for(f"grade_{user['grade']}_dashboard"))
        else:
            return redirect_to_dashboard(session.get("user"))
    file = request.files["textbook"]
    if file.filename == "":
        flash("No file selected.")
        user = session.get("user")
        if user and user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
            return redirect(url_for(f"grade_{user['grade']}_dashboard"))
        else:
            return redirect_to_dashboard(session.get("user"))

    filename = file.filename
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    session["uploaded_file"] = filename
    user = session.get("user")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO uploads (student_id, filename, uploaded_at) VALUES (?, ?, ?)",
                (user["id"], filename, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    flash(f"Uploaded {filename} successfully ✅")
    user = session.get("user")
    if user and user.get("grade") and user["grade"] in ["1", "2", "3", "4", "5"]:
        return redirect(url_for(f"grade_{user['grade']}_dashboard"))
    else:
        return redirect_to_dashboard(session.get("user"))

@app.route("/library")
@login_required(role="student")
def library():
    user = session.get("user")
    student_grade = user.get("grade")
    
    # Fetch books assigned to this student's grade
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT filename FROM uploads WHERE grade = ? ORDER BY uploaded_at DESC", (str(student_grade),))
    db_books = [row['filename'] for row in c.fetchall()]
    conn.close()

    books_folder = os.path.join(app.static_folder, "books")
    if not os.path.exists(books_folder):
        os.makedirs(books_folder)

    # Only show books that are registered for this student's grade
    books = sorted(
        [f for f in os.listdir(books_folder) if f in db_books],
        key=lambda x: os.path.getmtime(os.path.join(books_folder, x)),
        reverse=True
    )

    return render_template("library.html", books=books, user=user)


@app.route("/audio_narration", methods=["POST"])
@login_required(role="student")
def audio_narration():

    print("=== AUDIO ROUTE HIT ===")

    user = session.get("user")
    
    filename = session.get("uploaded_file")
    if not filename:
        flash("No textbook uploaded.")
        return redirect_to_dashboard(user)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    if not os.path.exists(filepath):
        flash("File not found.")
        return redirect_to_dashboard(user)

    # Quota log
    check_and_update_quota(user["id"])

    # Extract text
    text = extract_text_hybrid(filepath)

    if text.startswith("ERROR_"):
        if "OCR_MISSING" in text:
            flash("⚠️ This looks like a scanned PDF (image). We need a text-based PDF or Word doc because OCR is not installed.")
        else:
            flash("⚠️ Could not read text from this file. Please try a different file.")
        return redirect_to_dashboard(user)

    if not text.strip():
        flash("⚠️ File appears empty. Please check the content.")
        return redirect_to_dashboard(user)

    print("=== TEXT EXTRACTED ===")

    # Use OpenAI client
    from openai import OpenAI
    client = OpenAI()

    print("=== GENERATING AUDIO WITH OPENAI ===")

    try:
        student_id = session["user"]["id"]
        timestamp = int(time.time())
        audio_filename = f"{student_id}_{timestamp}.mp3"
        audio_path = os.path.join("static", "narrations", audio_filename)

        os.makedirs("static/narrations", exist_ok=True)

        try:
            speech = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="alloy",
                input=text[:4000]
            )
            with open(audio_path, "wb") as f:
                f.write(speech.content)
        except Exception as e:
            print(f"OpenAI TTS failed: {e}. Trying Edge TTS fallback...")
            try:
                run_edge_tts(text[:4000], audio_path)
            except Exception as e2:
                print(f"Edge TTS also failed: {e2}")
                flash("Audio generation failed.")
                return redirect_to_dashboard(user)

        if not os.path.exists(audio_path):
            flash("Audio generation failed.")
            return redirect_to_dashboard(user)

        session["audio_file"] = audio_filename
        session.modified = True

        print("=== AUDIO STORED IN SESSION ===")
        flash("Audio narration generated successfully!")

    except Exception as e:
        print("=== AUDIO ERROR ===")
        print(str(e))
        flash("Audio generation failed. Check terminal.")
        return redirect_to_dashboard(user)

    return redirect_to_dashboard(user)


@app.route("/generate_summary", methods=["POST"])
@login_required(role="student")
def generate_summary():
    print("=== GENERATE SUMMARY ROUTE HIT ===")

    user = session.get("user")

    # Get latest uploaded file
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT filename FROM uploads
        WHERE student_id = ?
        ORDER BY uploaded_at DESC
        LIMIT 1
    """, (user["id"],))
    result = cur.fetchone()
    conn.close()

    if not result:
        flash("⚠️ No textbook uploaded yet.")
        return redirect_to_dashboard(session.get("user"))

    # Quota log
    check_and_update_quota(user["id"])

    filename = result["filename"]
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    # Extract text
    text = extract_text_hybrid(filepath)
    
    if text.startswith("ERROR_"):
        if "OCR_MISSING" in text:
            flash("⚠️ This looks like a scanned PDF. We need a text-based PDF or Word doc because OCR is not installed.")
        else:
            flash("⚠️ Could not read text from this file.")
        return redirect_to_dashboard(session.get("user"))

    if not text.strip():
        flash("Could not extract text. If this is a scanned PDF, please use a selectable PDF or DOCX.")
        return redirect_to_dashboard(session.get("user"))

    print("=== TEXT EXTRACTED SUCCESSFULLY ===")

    # Use OpenAI client
    from openai import OpenAI
    client = OpenAI()

    print("=== GENERATING SUMMARY WITH OPENAI ===")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": "Explain clearly for school students."},
                {"role": "user", "content": text[:6000]}
            ]
        )

        summary = response.choices[0].message.content.strip()

        if not summary:
            flash("Failed to generate summary.")
            return redirect_to_dashboard(user)

        session["summary"] = summary
        session.modified = True

        print("=== SUMMARY STORED IN SESSION ===")
        flash("AI Summary generated successfully!")

    except Exception as e:
        print("=== OPENAI ERROR ===")
        print(str(e))
        # Fallback: Simple Extractive Summary
        sentences = re.split(r'(?<=[.!?]) +', text)
        # Take up to 5 sentences and format as a bulleted list
        top_sentences = sentences[:5]
        summary = "<ul class='list-disc pl-5 space-y-2'>" + "".join([f"<li>{s}</li>" for s in top_sentences]) + "</ul><p class='mt-2 text-sm text-gray-500 italic'>(Preview due to AI quota limit)</p>"
        
        session["summary"] = summary
        session.modified = True
        flash("AI Summary generated successfully! (Fallback Mode)")
        return redirect_to_dashboard(user)

    return redirect_to_dashboard(user)

@app.route("/translate_text", methods=["POST"])
@login_required(role="student")
def translate_text():
    print("=== TRANSLATE ROUTE HIT ===")

    user = session.get("user")
    filename = session.get("uploaded_file")

    # Quota log
    check_and_update_quota(user["id"])

    if not filename:
        flash("No textbook uploaded yet.")
        return redirect_to_dashboard(user)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    if not os.path.exists(filepath):
        flash("File not found on server.")
        return redirect_to_dashboard(user)

    # ---------- Extract text ----------
    print(f"--- Starting text extraction for {filename} ---")
    try:
        text = extract_text_hybrid(filepath)
        
        if text.startswith("ERROR_"):
            if "OCR_MISSING" in text:
                flash("⚠️ This looks like a scanned PDF. Please upload a text-based PDF or Word doc.")
            else:
                flash("⚠️ Could not read text from this file.")
            return redirect_to_dashboard(user)
            
    except Exception as e:
        print("TEXT EXTRACTION ERROR:", e)
        flash("Unable to read PDF.")
        return redirect_to_dashboard(user)

    if not text.strip():
        flash("No readable text found. If this is a scanned PDF, please use a selectable PDF or DOCX.")
        return redirect_to_dashboard(user)

    print("=== TEXT EXTRACTED ===")

    # ---------- Translate with OpenAI ----------
    try:
        from openai import OpenAI
        client = OpenAI()

        prompt = f"""
Translate the following educational text into **simple Hindi**. 

Rules:
- Keep ALL content from the provided snippet
- Do NOT summarize
- Keep paragraph structure same

Text:
{text[:5000]}
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=2000, # Increased for translation specifically
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        translated_text = response.choices[0].message.content.strip()
        print("=== HINDI GENERATED ===")

    except Exception as e:
        print("OPENAI TRANSLATION ERROR:", e)
        # Fallback: Google Translate (Free)
        try:
            print("Trying Google Translate fallback...")
            from deep_translator import GoogleTranslator
            
            # Use a smaller chunk size to be safe (800 chars) to avoid URL length errors
            fallback_text = text[:800]
            
            # Perform translation
            translator = GoogleTranslator(source='auto', target='hi')
            translated_text = translator.translate(fallback_text)
            
            if not translated_text:
                raise Exception("Empty translation result")

            translated_text += "\n\n(Translated slightly less text due to free tool limits)"
            flash("Translation successful! (Fallback Mode)")
            
        except Exception as e2:
             print("Fallback Translation failed:", e2)
             flash(f"Translation failed: {str(e2)}")
             return redirect_to_dashboard(user)

    # ---------- FONT HANDLING (ROBUST) ----------
    hindi_font_path = os.path.join(
        os.path.dirname(__file__),
        "NotoSansDevanagari-Regular.ttf"
    )

    font_to_use = None

    if os.path.exists(hindi_font_path):
        print("Hindi font found:", hindi_font_path)
        font_to_use = hindi_font_path
    else:
        print("Hindi font NOT found → using default Helvetica")
        font_to_use = None  # fallback

    # ---------- CREATE PDF SAFELY ----------
    try:
        os.makedirs("static/translations", exist_ok=True)

        base = os.path.splitext(filename)[0]
        hindi_file = f"{base}_hindi.pdf"
        hindi_path = os.path.join("static", "translations", hindi_file)

        print("Saving Hindi PDF to:", hindi_path)

        if not translated_text or not translated_text.strip():
            flash("Translation returned empty text.")
            return redirect_to_dashboard(user)

        # If font exists → use custom font
        if font_to_use:
            text_to_pdf(translated_text, hindi_path, font_to_use)
        else:
            # Fallback using improved wrapper even without custom font (though Hindi won't show)
            # Actually, without custom font, we use Helvetica but still want wrapping
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            
            doc = SimpleDocTemplate(hindi_path, pagesize=A4)
            styles = getSampleStyleSheet()
            custom_style = ParagraphStyle(
                'DyslexicStyle', 
                parent=styles['Normal'], 
                fontSize=16, 
                textColor='#333333',
                leading=16 * 1.8
            )
            
            story = []
            for p in translated_text.split("\n"):
                if p.strip():
                    story.append(Paragraph(saxutils.escape(p), custom_style))
            doc.build(story)

        if not os.path.exists(hindi_path):
            flash("Failed to generate Hindi PDF.")
            return redirect_to_dashboard(user)

        print("=== HINDI PDF CREATED SUCCESSFULLY ===")

    except Exception as e:
        print("PDF SAVE ERROR:", e)
        flash(f"Failed to create Hindi PDF: {str(e)}")
        return redirect_to_dashboard(user)

    # ---------- STORE IN SESSION ----------
    session["hindi_file"] = hindi_file
    session.modified = True

    flash("Hindi translation ready for download!")

    return redirect_to_dashboard(user)

@app.route("/dyslexic_friendly", methods=["GET", "POST"])
@login_required(role="student")
def dyslexic_friendly():
    """
    Show a dyslexic-friendly reader for the currently uploaded PDF.

    - Do NOT store the extracted text in the Flask session
      (it makes the cookie too large).
    - Always re-read from the uploaded PDF whenever this view is hit.
    """
    user = session.get("user")
    
    # Check if there's a PDF uploaded
    filename = session.get("uploaded_file")
    if not filename:
        flash("📖 Please upload a textbook first to use the Dyslexic Reader.")
        return redirect_to_dashboard(user)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(filepath):
        flash("⚠️ The uploaded file could not be found. Please upload it again.")
        return redirect_to_dashboard(user)

    # Use the existing hybrid extractor (PyPDF2 + OCR fallback)
    raw_text = extract_text_hybrid(filepath)

    if not raw_text or not raw_text.strip():
        flash("⚠️ Still no readable text found, even after OCR. Please try uploading a different file.")
        return redirect_to_dashboard(user)

    # Keep the text as plain text with newlines.
    # We will handle formatting and word-wrapping on the client.
    clean_text = raw_text

    print("DEBUG dyslexic_friendly: text length sent to template =", len(clean_text))

    return render_template("dyslexic_reader.html", text=clean_text, user=user)



@app.route("/generate_flashcards", methods=["POST"])
@login_required(role="student")
def generate_flashcards():
    import json, re
    user = session.get("user")
    
    # Quota log
    check_and_update_quota(user["id"])
    
    filename = session.get("uploaded_file")

    # Validate filename BEFORE any DB operation
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect_to_dashboard(user)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    # Ensure table column exists
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(flashcards)")
    cols = [c[1] for c in cur.fetchall()]
    if "data" not in cols:
        cur.execute("ALTER TABLE flashcards ADD COLUMN data TEXT")
        conn.commit()
    conn.close()

    # Safely delete previous flashcards for this file + user
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM flashcards WHERE student_id = ? AND filename = ?",
        (user["id"], filename)
    )
    conn.commit()
    conn.close()

    # ------------------------
    # Extract text from File
    # ------------------------
    text = extract_text_hybrid(filepath)
    
    if text.startswith("ERROR_"):
        flash("⚠️ Could not read text for flashcards. Please upload a clear text-based PDF or DOCX.")
        return redirect_to_dashboard(user)
    
    if not text or not text.strip():
        flash("⚠️ Unable to extract text. If this is a scanned PDF, please use a selectable PDF or DOCX.")
        return redirect_to_dashboard(user)

    # ------------------------
    # Generate flashcards (10) using OpenAI
    # ------------------------
    success_ui = True
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=MAX_TOKENS + 1000, # Allow more for JSON flashcards
            messages=[
                {
                    "role": "system",
                    "content": "You are an educational assistant. Generate between 10 and 20 flashcards from the text, depending on its depth. Be concise to save tokens. Return ONLY a JSON array: [{\"question\":\"...\", \"answer\":\"...\"}]"
                },
                {
                    "role": "user",
                    "content": f"Create flashcards from this text: {text[:4000]}"
                }
            ],
            temperature=0.7
        )
        
        raw = response.choices[0].message.content.strip()
        # Remove markdown code blocks if present
        raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        
        # Find JSON array in response
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError("No JSON array found in response")
            
        json_array = match.group()
        flashcards = json.loads(json_array)
        
        if not isinstance(flashcards, list) or len(flashcards) == 0:
            raise ValueError("Invalid flashcard format received")
            
    except Exception as e:
        success_ui = False
        print(f"OpenAI flashcard generation error: {str(e)}")
        flash("⚠️ AI flashcard generation failed. Using fallback method.")
        # Fallback flashcards
        flashcards = [
            {"question": "What is the main topic?", "answer": "Review your material"},
            {"question": "Key concept 1", "answer": "Important information"},
            {"question": "Key concept 2", "answer": "Essential details"},
            {"question": "Key concept 3", "answer": "Core principles"},
            {"question": "Key concept 4", "answer": "Fundamental ideas"},
            {"question": "Key concept 5", "answer": "Basic concepts"},
            {"question": "Key concept 6", "answer": "Main points"},
            {"question": "Key concept 7", "answer": "Important facts"},
            {"question": "Key concept 8", "answer": "Essential knowledge"},
            {"question": "Key concept 9", "answer": "Core information"}
        ]

    # ------------------------
    # Save to SQLite
    # ------------------------
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO flashcards (student_id, filename, num_flashcards, created_at, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user["id"],
            filename,
            len(flashcards),
            datetime.now(timezone.utc).isoformat(),
            json.dumps(flashcards)
        )
    )
    
    # Generate and save puzzle data for drag-and-drop game
    try:
        puzzle_data = extract_labels_for_dragdrop(text[:2000])
        if "error" not in puzzle_data:
            cur.execute(
                """
                INSERT INTO puzzle_data (student_id, filename, puzzle_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user["id"],
                    filename,
                    json.dumps(puzzle_data),
                    datetime.now(timezone.utc).isoformat()
                )
            )
    except Exception as e:
        print(f"Error generating puzzle data: {e}")
    
    conn.commit()
    conn.close()

    return render_template("flashcard.html", flashcards=flashcards, user=user, success=success_ui)

@app.route("/generate_quiz", methods=["POST"])
@login_required(role="student")
def generate_quiz():
    user = session.get("user")
    
    # Quota log
    check_and_update_quota(user["id"])
    
    filename = session.get("uploaded_file")
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect_to_dashboard(user)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    # Extract text
    text = extract_text_hybrid(filepath)

    if text.startswith("ERROR_"):
        flash("⚠️ Could not read text for quiz. Please upload a clear text-based PDF or DOCX.")
        return redirect_to_dashboard(user)

    if not text or not text.strip():
        flash("⚠️ No text found. If this is a scanned PDF, please use a selectable PDF or DOCX.")
        return redirect_to_dashboard(user)

    # Generate quiz with OpenAI
    success_ui = True
    try:
        # Increase variety by taking a random slice of text if it's long
        max_chars = 6000
        text_content = text.strip()
        if len(text_content) > max_chars:
            import random
            # Pick a random starting point, ensuring we have enough text left
            start_idx = random.randint(0, len(text_content) - max_chars)
            text_slice = text_content[start_idx : start_idx + max_chars]
        else:
            text_slice = text_content

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=MAX_TOKENS + 1500, # Quizzes need more tokens for JSON
            messages=[
                {
                    "role": "system",
                    "content": "You are an educational assistant that creates multiple-choice quizzes. Generate exactly 10 MCQ questions based on the provided text. Ensure the questions cover various topics found in the excerpt to provide a diverse learning experience. Return ONLY a JSON array in this exact format: [{\"question\":\"...\", \"options\":[\"A. ...\", \"B. ...\", \"C. ...\", \"D. ...\"], \"answer\":\"B\"}] where answer is A, B, C, or D. Each option must start with a letter and dot."
                },
                {
                    "role": "user",
                    "content": f"Create a diverse 10-question multiple-choice quiz from this section of the textbook: {text_slice}"
                }
            ],
            temperature=0.8
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        
        # Find JSON array in response
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError("No JSON array found in response")
            
        json_array = match.group()
        quiz = json.loads(json_array)
        
        # Validate structure
        for q in quiz:
            if not all(key in q for key in ["question", "options", "answer"]):
                raise ValueError("Invalid quiz structure")
            if len(q["options"]) != 4:
                raise ValueError("Each question must have 4 options")

    except Exception as e:
        success_ui = False
        print(f"OpenAI quiz generation error: {str(e)}")
        flash("⚠️ AI quiz generation failed. Using fallback method.")
        # Fallback quiz
        quiz = [
            {
                "question": "What is the main topic of your textbook?",
                "options": ["A. Topic A", "B. Topic B", "C. Topic C", "D. Topic D"],
                "answer": "A"
            }
        ]

    session["quiz"] = quiz
    session["quiz_file"] = filename  

    return render_template("quiz.html", quiz=quiz, user=user, success=success_ui)

@app.route("/submit_quiz", methods=["POST"])
@login_required(role="student")
def submit_quiz():
    quiz = session.get("quiz")
    if not quiz:
        flash("No quiz found.")
        return redirect_to_dashboard(session.get("user"))

    score = 0
    results = []

    for i, q in enumerate(quiz, start=1):
        user_answer = (request.form.get(f"q{i}") or "").strip()
        user_letter = user_answer[0].upper() if user_answer else ""
        correct_letter = q["answer"].strip().upper()

        is_correct = (user_letter == correct_letter)

    # Find the full correct option text by matching the letter
        correct_full = next(
        (opt for opt in q["options"] if opt.strip().upper().startswith(correct_letter)),
        correct_letter  # fallback in case nothing matches
        )

        if is_correct:
            score += 1

        results.append({
        "question": q["question"],
        "your_answer": user_answer,    # full text user selected
        "correct_answer": correct_full, # full text correct option
        "is_correct": is_correct
        })


    quiz_id = f"{session.get('quiz_file')}_{int(time.time())}"  
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO quiz_attempts (student_id, quiz_id, score, total, attempted_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user"]["id"],
        quiz_id,
        score,             
        len(quiz),        
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

    session.pop("quiz", None)
    session.pop("quiz_file", None)

    user = session.get("user")
    return render_template("quiz_results.html", score=score, total=len(quiz), results=results, user=user)

# ---------- Teacher Dashboard ----------
@app.route("/dashboard/teacher")
@login_required(role="teacher")
def teacher_dashboard():
    user = session.get("user")
    teacher_grade = user.get("grade")
    conn = get_db()
    cur = conn.cursor()

    if teacher_grade == "Admin":
        cur.execute("SELECT * FROM students ORDER BY datetime(created_at) DESC")
    elif teacher_grade:
        cur.execute("SELECT * FROM students WHERE grade = ? ORDER BY datetime(created_at) DESC", (teacher_grade,))
    else:
        # Fallback for old teachers without a grade assigned
        cur.execute("SELECT * FROM students ORDER BY datetime(created_at) DESC")
        
    students = cur.fetchall()

    recent_students = []
    total_uploads = 0
    total_flashcards = 0
    total_quizzes = 0
    total_scores = 0

    for student in students:
        sid = student["id"]
        cur.execute("SELECT COUNT(*) FROM uploads WHERE student_id = ?", (sid,))
        uploads_count = cur.fetchone()[0]
        total_uploads += uploads_count

        cur.execute("SELECT COALESCE(SUM(num_flashcards), 0) FROM flashcards WHERE student_id = ?", (sid,))
        fc_sum = cur.fetchone()[0] or 0
        total_flashcards += fc_sum

        cur.execute("SELECT score, total FROM quiz_attempts WHERE student_id = ?", (sid,))
        quizzes = cur.fetchall()
        q_count = len(quizzes)
        total_quizzes += q_count
        if q_count:
            total_scores += sum(q["score"] for q in quizzes) / sum(q["total"] for q in quizzes) if sum(q["total"] for q in quizzes) else 0

        avg_score_pct = 0
        if q_count and sum(q["total"] for q in quizzes):
            avg_score_pct = round((sum(q["score"] for q in quizzes) / sum(q["total"] for q in quizzes)) * 100, 1)

        activity_score = uploads_count + fc_sum + q_count
        recent_students.append({
            "id": sid,
            "name": student["name"],
            "grade": student["grade"] or "-",
            "uploads": uploads_count,
            "flashcards": fc_sum,
            "avg_score_pct": avg_score_pct,
            "activity": activity_score,
        })

    # Sort by activity descending and keep all students for the dashboard list
    recent_students.sort(key=lambda s: s["activity"], reverse=True)
    
    num_students = len(students)
    class_avg_pct = 0
    if num_students and total_quizzes:
        class_avg_pct = round((total_scores / num_students) * 100, 1)

    # Calculate real class performance data over time
    class_performance_data = []
    if teacher_grade:
        cur.execute("""
            SELECT qa.score, qa.total, qa.attempted_at 
            FROM quiz_attempts qa
            JOIN students s ON qa.student_id = s.id
            WHERE s.grade = ?
            ORDER BY qa.attempted_at ASC
        """, (teacher_grade,))
        all_quizzes = cur.fetchall()
        
        # Group by date and calculate daily average
        daily_scores = {}
        for q in all_quizzes:
            try:
                date_str = q["attempted_at"].split("T")[0]
                if date_str not in daily_scores:
                    daily_scores[date_str] = []
                # Individual quiz percentage
                pct = (q["score"] / q["total"]) * 100 if q["total"] > 0 else 0
                daily_scores[date_str].append(pct)
            except (ValueError, KeyError, IndexError):
                continue
        
        # Sort dates and get last 10 points
        sorted_dates = sorted(daily_scores.keys())
        for d in sorted_dates:
            avg_daily = sum(daily_scores[d]) / len(daily_scores[d])
            class_performance_data.append(round(avg_daily, 1))
        
        # Limit to last 10 data points for the trend
        class_performance_data = class_performance_data[-10:]

    conn.close()

    return render_template(
        "teacher_dashboard.html",
        name=user.get("name"),
        recent_students=recent_students,
        num_students=num_students,
        total_uploads=total_uploads,
        total_flashcards=total_flashcards,
        total_quizzes=total_quizzes,
        class_avg_pct=class_avg_pct,
        class_performance_data=class_performance_data,
    )


@app.route("/upload_books", methods=["GET", "POST"])
@login_required(role="teacher")
def upload_books():
    user = session.get("user")
    teacher_grade = user.get("grade")
    
    if request.method == "POST":
        if "book" not in request.files:
            flash("No file selected")
            return redirect(request.url)
        file = request.files["book"]
        if file.filename.endswith(".pdf"):
            filename = file.filename
            filepath = os.path.join(BOOKS_FOLDER, filename)
            file.save(filepath)
            
            # Register in database with grade
            try:
                conn = get_db()
                c = conn.cursor()
                # Check if file already recorded for this grade to avoid duplicates
                c.execute("SELECT id FROM uploads WHERE filename = ? AND grade = ?", (filename, teacher_grade))
                if not c.fetchone():
                    from datetime import datetime
                    c.execute("INSERT INTO uploads (filename, grade, uploaded_at) VALUES (?, ?, ?)",
                             (filename, teacher_grade, datetime.now().isoformat()))
                    conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error registering upload in DB: {e}")
                
            flash("Book uploaded successfully!")
            return redirect(url_for("upload_books"))
        else:
            flash("Only PDF files allowed!")
            return redirect(request.url)

    # Fetch books assigned to this teacher's grade
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT filename FROM uploads WHERE grade = ? ORDER BY uploaded_at DESC", (teacher_grade,))
    db_books = [row['filename'] for row in c.fetchall()]
    conn.close()
    
    # Filter physical files to only those registered for this grade
    all_books = sorted(
        [f for f in os.listdir(BOOKS_FOLDER) if f.lower().endswith(".pdf") and f in db_books],
        key=lambda x: os.path.getmtime(os.path.join(BOOKS_FOLDER, x)),
        reverse=True
    )
    return render_template("upload_books.html", books=all_books)


@app.route("/student_progress")
@login_required(role="teacher")
def student_progress():
    user = session.get("user")
    teacher_grade = user.get("grade")
    conn = get_db()
    cur = conn.cursor()
    
    filter_id = request.args.get("student_id")
    if filter_id:
        cur.execute("SELECT * FROM students WHERE id = ?", (filter_id,))
    elif teacher_grade == "Admin":
        cur.execute("SELECT * FROM students")
    elif teacher_grade:
        cur.execute("SELECT * FROM students WHERE grade = ?", (teacher_grade,))
    else:
        cur.execute("SELECT * FROM students")
    students = cur.fetchall()

    progress_data = []
    for student in students:
        student_id = student["id"]

        cur.execute("SELECT * FROM uploads WHERE student_id = ?", (student_id,))
        uploads = cur.fetchall()
        total_uploads = len(uploads)

        cur.execute("SELECT * FROM flashcards WHERE student_id = ?", (student_id,))
        flashcards = cur.fetchall()
        total_flashcards = sum(f['num_flashcards'] for f in flashcards)

        cur.execute("SELECT * FROM quiz_attempts WHERE student_id = ?", (student_id,))
        quizzes = cur.fetchall()
        total_quizzes = len(quizzes)
        avg_score = round(sum(q['score'] for q in quizzes) / total_quizzes, 2) if total_quizzes else 0
        completion_rate = f"{total_quizzes}/{total_uploads}" if total_uploads else "0/0"

        num_audiobooks = len([u for u in uploads if u['filename'].endswith('.mp3')])

        progress_data.append({
            "student": student,
            "uploads": uploads,
            "total_uploads": total_uploads,
            "flashcards": flashcards,
            "total_flashcards": total_flashcards,
            "quizzes": quizzes,
            "total_quizzes": total_quizzes,
            "avg_score": avg_score,
            "completion_rate": completion_rate,
            "num_audiobooks": num_audiobooks
        })

    conn.close()

    return render_template("student_progress.html", progress_data=progress_data, filter_id=filter_id)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/api/read-selected-text", methods=["POST"])
@login_required(role="student")
def api_read_selected_text():
    try:
        data = request.get_json(silent=True) or {}
        raw_text = (data.get("text") or "").strip()
        if not raw_text:
            return {"error": "No text provided"}, 400

        # Generate audio file path
        student_id = session["user"]["id"]
        timestamp = int(time.time())
        os.makedirs("static/narrations", exist_ok=True)
        audio_filename = f"tts_{student_id}_{timestamp}.mp3"
        audio_path = os.path.join("static/narrations", audio_filename)

        # Length-weighted timings with punctuation pause bonuses
        def word_weight(w: str) -> float:
            core = re.sub(r"^[^\w]+|[^\w]+$", "", w)
            base = max(1, len(core))
            bonus = 0.0
            if re.search(r"[\.!?]$", w):
                bonus += 3.0  # sentence end pause
            elif re.search(r"[,;:]$", w):
                bonus += 1.5  # clause pause
            return base + bonus

        words = re.findall(r"\S+|\n", raw_text)
        # Filter out standalone newline tokens for audio timing, but we keep them
        # for paragraph gaps on the client.
        words = [w for w in words if w.strip()]
        if not words:
            return {"error": "No readable words found"}, 400
            
        weights = [word_weight(w) for w in words]
        total_weight = sum(weights) or len(words)
        # Approximate duration scales with total weight; client rescales to true duration
        approx_seconds = max(1.8, total_weight / 9.0)
        timings = [
        ]
        cursor = 0.0
        for w, wt in zip(words, weights):
            dur = (wt / total_weight) * approx_seconds
            start = round(cursor, 3)
            end = round(cursor + dur, 3)
            timings.append({"word": w, "start": start, "end": end})
            cursor += dur

        # Generate audio using OpenAI TTS
        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            with client.audio.speech.with_streaming_response.create(
                model="tts-1",
                voice="alloy",
                input=raw_text[:4000]  # Limit text to 4000 characters
            ) as response:
                response.stream_to_file(audio_path)
        except Exception as e:
            print(f"OpenAI TTS failed: {e}. Trying Edge TTS fallback...")
            try:
                run_edge_tts(raw_text[:4000], audio_path)
            except Exception as e2:
                return {"error": f"TTS failed: {str(e)} | Fallback failed: {str(e2)}"}, 500

        # Verify the file was created
        if not os.path.exists(audio_path):
            return {"error": "Audio file was not created properly."}, 500

        # Audio file is already saved by pyttsx3 above
        # timings array is already built above

        return {
            "audio_url": url_for("static", filename=f"narrations/{audio_filename}"),
            "timings": timings,
        }, 200

    except Exception as e:
        return {"error": str(e)}, 500

# Game Dashboard Route
@app.route("/games")
@login_required(role="student")
def games_dashboard():
    user = session.get("user")
    
    return render_template("games_dashboard.html", name=user.get("name"), user=user)

# Game Routes
@app.route("/game/memory")
@login_required(role="student")
def game_memory():
    user_id = session["user"]["id"]

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT data FROM flashcards WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    if not row or not row["data"]:
        return render_template("game_memory_no_flashcards.html")

    import json
    flashcards = json.loads(row["data"])

    if not flashcards:
        return render_template("game_memory_no_flashcards.html")

    return render_template("game_memory.html", flashcards=flashcards)

@app.route("/game/dragdrop")
@login_required(role="student")
def game_dragdrop():
    user_id = session["user"]["id"]
    
    # Get the last uploaded PDF for this student
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM uploads WHERE student_id = ? ORDER BY uploaded_at DESC LIMIT 1", (user_id,))
    result = cur.fetchone()
    
    puzzle_data = None
    if result:
        filename = result["filename"]
        # Try to get puzzle data from puzzle_data table
        cur.execute("SELECT puzzle_json FROM puzzle_data WHERE student_id = ? AND filename = ? ORDER BY created_at DESC LIMIT 1", (user_id, filename))
        puzzle_result = cur.fetchone()
        
        if puzzle_result and puzzle_result["puzzle_json"]:
            import json
            puzzle_data = json.loads(puzzle_result["puzzle_json"])
    
    conn.close()
    
    return render_template("game_dragdrop.html", puzzle=puzzle_data)

@app.route("/game/story")
@login_required(role="student")
def game_story():
    user = session.get("user")
    return render_template("game_story.html", name=user.get("name"), user=user)

# Word Highlight Speed Game Routes
@app.route("/game/wordspeed")
@login_required(role="student")
def game_wordspeed():
    user = session.get("user")
    return render_template("game_word_speed.html", name=user.get("name"))

@app.route("/api/get_sentence")
@login_required(role="student")
def api_get_sentence():
    user_id = session["user"]["id"]
    
    # Get the last uploaded PDF for this student
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM uploads WHERE student_id = ? ORDER BY uploaded_at DESC LIMIT 1", (user_id,))
    result = cur.fetchone()
    
    if not result:
        conn.close()
        return {"error": "No uploaded files found"}, 404
    
    filename = result["filename"]
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    
    if not os.path.exists(filepath):
        conn.close()
        return {"error": "File not found"}, 404
    
    try:
        # Extract text from PDF
        pdf_text = extract_text_hybrid(filepath)
        
        if not pdf_text.strip():
            conn.close()
            return {"error": "No text found in the uploaded file"}, 404
        
        # Split text into sentences
        import re
        sentences = re.split(r'[.!?]+', pdf_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            conn.close()
            return {"error": "No valid sentences found"}, 404
        
        # Find a sentence with a repeated word
        import random
        max_attempts = min(50, len(sentences))
        selected_sentence = None
        target_word = None
        
        for _ in range(max_attempts):
            sentence = random.choice(sentences)
            words = sentence.lower().split()
            
            # Find words that appear at least twice
            word_count = {}
            for word in words:
                # Clean word (remove punctuation)
                clean_word = re.sub(r'[^\w]', '', word)
                if clean_word:
                    word_count[clean_word] = word_count.get(clean_word, 0) + 1
            
            # Check if any word appears at least twice
            repeated_words = [word for word, count in word_count.items() if count >= 2]
            
            if repeated_words:
                selected_sentence = sentence
                target_word = random.choice(repeated_words)
                break
        
        conn.close()
        
        if not selected_sentence or not target_word:
            return {"error": "Could not find a sentence with repeated words"}, 404
        
        return {
            "sentence": selected_sentence,
            "target": target_word
        }
    
    except Exception as e:
        conn.close()
        print(f"Error in get_sentence: {e}")
        return {"error": str(e)}, 500

# Drag & Drop Labels Game Routes
@app.route("/api/dragdrop/generate")
@login_required(role="student")
def api_dragdrop_generate():
    user_id = session["user"]["id"]
    
    # Get the last uploaded PDF for this student
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM uploads WHERE student_id = ? ORDER BY uploaded_at DESC LIMIT 1", (user_id,))
    result = cur.fetchone()
    
    if not result:
        conn.close()
        return {"error": "No uploaded files found"}, 404
    
    filename = result["filename"]
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    
    if not os.path.exists(filepath):
        conn.close()
        return {"error": "File not found"}, 404
    
    try:
        # Extract text from PDF
        pdf_text = extract_text_hybrid(filepath)
        
        if not pdf_text.strip():
            conn.close()
            return {"error": "No text found in the uploaded file"}, 404
        
        # Limit text to first 2000 characters to avoid token limits
        pdf_text = pdf_text[:2000]
        
        # Use OpenAI model to generate diagram data
        prompt = f"""
        Based on this textbook content, generate a simple educational diagram with labels.
        
        Textbook content: {pdf_text}
        
        Respond ONLY with valid JSON in this exact format:
        {{
          "title": "Diagram Title",
          "svg": "<svg>...</svg>",
          "labels": ["Label 1", "Label 2", "Label 3", "Label 4"],
          "positions": [
            {{"label": "Label 1", "x": 100, "y": 150}},
            {{"label": "Label 2", "x": 200, "y": 250}},
            {{"label": "Label 3", "x": 300, "y": 100}},
            {{"label": "Label 4", "x": 400, "y": 200}}
          ]
        }}
        
        Requirements:
        - Choose a concept relevant to the textbook content
        - Create a simple SVG diagram with basic shapes (circles, rectangles, lines)
        - Include 4-8 labels
        - Provide exact coordinates for label positions
        - Make the SVG approximately 500x400 pixels
        - Return ONLY valid JSON, no extra text
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000,
            response_format={ "type": "json_object" }
        )
        
        response_text = response.choices[0].message.content
        
        # Parse the JSON response
        import json
        import re
        
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            conn.close()
            return {"error": "Invalid response format from AI"}, 500
        
        diagram_data = json.loads(json_match.group())
        
        conn.close()
        
        return diagram_data
    
    except json.JSONDecodeError as e:
        conn.close()
        print(f"JSON decode error: {e}")
        return {"error": "Invalid JSON response from AI"}, 500
    except Exception as e:
        conn.close()
        print(f"Error in dragdrop generate: {e}")
        return {"error": str(e)}, 500


# AI Story Adventure Game Routes
@app.route("/story/start", methods=["POST"])
@login_required(role="student")
def story_start():
    # Quota log
    check_and_update_quota(session["user"]["id"])
    try:
        print("Story start endpoint called")
        data = request.get_json()
        chapter_text = data.get("chapter_text", "")
        print(f"Chapter text received: {chapter_text[:100]}...")
        
        # Store chapter_text in session for reuse
        session["story_chapter_text"] = chapter_text
        print("Chapter text stored in session")
        
        # Get story introduction
        story_data = get_story_chunk(chapter_text)
        print(f"Story data generated: {story_data}")
        return story_data
    except Exception as e:
        print(f"Story Start Error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500


@app.route("/story/continue", methods=["POST"])
@login_required(role="student")
def story_continue():
    # Quota log
    check_and_update_quota(session["user"]["id"])
    try:
        print("Story continue endpoint called")
        data = request.get_json()
        user_choice = data.get("choice", "")
        print(f"User choice received: {user_choice}")
        
        # Get chapter_text from session
        chapter_text = session.get("story_chapter_text", "")
        print(f"Chapter text from session: {chapter_text[:100]}...")
        
        if not chapter_text:
            print("No chapter text found in session")
            return {"error": "No chapter text found in session"}, 400
        
        # Continue story based on user choice
        story_data = get_story_chunk(chapter_text, user_choice)
        print(f"Story data generated: {story_data}")
        return story_data
    except Exception as e:
        print(f"Story Continue Error: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500


# AI Story Generator Function
def get_story_chunk(chapter_text, user_choice=None):
    """
    Generate a story chunk based on chapter text and user choice.
    
    If user_choice is None: Generate story introduction + 2–3 choices
    Else: Continue story based on user choice + return next choices
    """
    
    # Use OpenAI model to generate story
    # Build prompt based on whether this is the start or continuation
    if user_choice is None:
        # Generate story introduction
        prompt = f"""
You are an educational story generator.  
Create a fun, interactive 'choose your own adventure' style story  
based ONLY on the chapter text provided.

Requirements:
- Keep story simple, engaging, educational.
- Make the student part of the story.
- After each story chunk, ALWAYS give 2–3 choices.
- Return ONLY valid JSON (no extra text) in this exact format:

{{
  "story": "story paragraph here",
  "choices": ["choice 1", "choice 2", "choice 3"]
}}

Chapter text: {chapter_text}
"""
    else:
        # Continue story based on user choice
        prompt = f"""
You are an educational story generator.  
Continue the 'choose your own adventure' style story based on the user's choice.

Previous chapter text: {chapter_text}
User's choice: {user_choice}

Requirements:
- Keep story simple, engaging, educational.
- Make the student part of the story.
- After each story chunk, ALWAYS give 2–3 choices.
- Return ONLY valid JSON (no extra text) in this exact format:

{{
  "story": "story paragraph here",
  "choices": ["choice 1", "choice 2", "choice 3"]
}}
"""
    
    try:
        # Generate response using OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=MAX_TOKENS + 500,
            response_format={ "type": "json_object" }
        )
        
        response_text = response.choices[0].message.content
        
        # Parse the JSON response
        import json
        import re
        
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            print(f"No JSON found in response: {response_text}")
            return {"error": "Invalid response format from AI"}
        
        try:
            story_data = json.loads(json_match.group())
            # Ensure we have the required fields
            if 'story' not in story_data or 'choices' not in story_data:
                print(f"Missing required fields in story data: {story_data}")
                return {"error": "Invalid story format from AI"}
            # Ensure story is a string
            if not isinstance(story_data['story'], str):
                print(f"Story is not a string: {story_data}")
                return {"error": "Invalid story format from AI"}
            # Limit story length to prevent overly long responses
            if len(story_data['story']) > 1000:
                story_data['story'] = story_data['story'][:1000] + "..."
                print("Limited story length to 1000 characters")
            # Ensure choices is a list
            if not isinstance(story_data['choices'], list):
                print(f"Choices is not a list: {story_data}")
                return {"error": "Invalid story format from AI"}
            # If choices is empty, it's the end of the story
            if len(story_data['choices']) == 0:
                print("Story has reached the end (empty choices)")
            # Limit choices to maximum 3
            if len(story_data['choices']) > 3:
                story_data['choices'] = story_data['choices'][:3]
                print(f"Limited choices to 3: {story_data['choices']}")
            # Ensure all choices are strings
            for i, choice in enumerate(story_data['choices']):
                if not isinstance(choice, str):
                    print(f"Choice {i} is not a string: {choice}")
                    return {"error": "Invalid story format from AI"}
            return story_data
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Response text: {response.text}")
            # Try to fix common JSON issues
            try:
                fixed_json = json_match.group().replace("'", '"')
                story_data = json.loads(fixed_json)
                # Ensure we have the required fields
                if 'story' not in story_data or 'choices' not in story_data:
                    print(f"Missing required fields in fixed story data: {story_data}")
                    return {"error": "Invalid story format from AI"}
                # Ensure story is a string
                if not isinstance(story_data['story'], str):
                    print(f"Story is not a string: {story_data}")
                    return {"error": "Invalid story format from AI"}
                # Limit story length to prevent overly long responses
                if len(story_data['story']) > 1000:
                    story_data['story'] = story_data['story'][:1000] + "..."
                    print("Limited story length to 1000 characters")
                # Ensure choices is a list
                if not isinstance(story_data['choices'], list):
                    print(f"Choices is not a list: {story_data}")
                    return {"error": "Invalid story format from AI"}
                # If choices is empty, it's the end of the story
                if len(story_data['choices']) == 0:
                    print("Story has reached the end (empty choices)")
                # Limit choices to maximum 3
                if len(story_data['choices']) > 3:
                    story_data['choices'] = story_data['choices'][:3]
                    print(f"Limited choices to 3: {story_data['choices']}")
                # Ensure all choices are strings
                for i, choice in enumerate(story_data['choices']):
                    if not isinstance(choice, str):
                        print(f"Choice {i} is not a string: {choice}")
                        return {"error": "Invalid story format from AI"}
                return story_data
            except json.JSONDecodeError:
                print(f"Failed to parse even after fixing: {response.text}")
                return {"error": "Invalid JSON response from AI"}
    
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return {"error": "Invalid JSON response from AI"}
    except Exception as e:
        print(f"Error in get_story_chunk: {e}")
        return {"error": str(e)}


# API endpoint to get chapter text for story game
@app.route("/api/get_chapter_text")
@login_required(role="student")
def api_get_chapter_text():
    try:
        user_id = session["user"]["id"]
        
        # Get the last uploaded PDF for this student
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT filename FROM uploads WHERE student_id = ? ORDER BY uploaded_at DESC LIMIT 1", (user_id,))
        result = cur.fetchone()
        
        if not result:
            conn.close()
            return {"error": "No uploaded files found"}, 404
        
        filename = result["filename"]
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        
        if not os.path.exists(filepath):
            conn.close()
            return {"error": "File not found"}, 404
        
        try:
            # Extract text from PDF
            pdf_text = extract_text_hybrid(filepath)
            
            if not pdf_text.strip():
                conn.close()
                return {"error": "No text found in the uploaded file"}, 404
            
            # Limit text to first 2000 characters to avoid token limits
            pdf_text = pdf_text[:2000]
            
            conn.close()
            
            return {"text": pdf_text}
        
        except Exception as e:
            conn.close()
            print(f"Error extracting text: {e}")
            return {"error": str(e)}, 500
    
    except Exception as e:
        print(f"Error in api_get_chapter_text: {e}")
        return {"error": str(e)}, 500

# AI Tutor Route
@app.route("/ai_tutor")
@login_required(role="student")
def ai_tutor():
    user = session.get("user")
    
    # Get the last uploaded PDF for this student
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM uploads WHERE student_id = ? ORDER BY uploaded_at DESC LIMIT 1", (user["id"],))
    result = cur.fetchone()
    
    pdf_text = ""
    if result:
        filename = result["filename"]
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(filepath):
            try:
                # Use robust extraction
                pdf_text = extract_text_hybrid(filepath)
                
                if not pdf_text.strip():
                    pdf_text = "Could not extract text from file."
            except Exception as e:
                print(f"Error reading file: {e}")
                pdf_text = "Error loading textbook content."
    
    # Create or restore tutor session
    # For now, we'll use a simple session ID based on user ID and timestamp
    # In a production environment, you'd want to store this in the database
    session_id = f"tutor_{user['id']}_{int(time.time())}"
    
    conn.close()
    
    return render_template("ai_tutor.html", 
                         name=user.get("name"), 
                         user=user,
                         pdf_text=pdf_text,
                         session_id=session_id)

# AI Tutor API
@app.route("/api/ai_tutor", methods=["POST"])
@login_required(role="student")
def api_ai_tutor():
    # Quota log
    check_and_update_quota(session["user"]["id"])
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        mode = data.get("mode", "teach")
        user_message = data.get("user_message", "")
        selected_text = data.get("selected_text", "")
        pdf_text = data.get("pdf_text", "")
        session_id = data.get("session_id", "")
        
        # Get last 8 messages from database for context
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT role, message FROM ai_tutor_sessions 
            WHERE student_id = ? 
            ORDER BY id DESC 
            LIMIT 8
        """, (user_id,))
        
        context_messages = cur.fetchall()
        conn.close()
        
        # Build prompt based on mode
        # Core Persona: Dyslexia Specialist
        system_prompt = """
You are a warm, patient, and encouraging AI tutor specialized in teaching students with dyslexia (Grades 1-5).
Your goal is to make learning accessible, fun, and stress-free.

**Crucial Guidelines:**
1.  **Format for Readability:**
    -   Use short, clear sentences.
    -   **Bold** key terms (e.g., "**Photosynthesis** is how plants eat").
    -   Use bullet points frequently.
    -   Avoid big blocks of text. Max 2-3 sentences per paragraph.
2.  **Tone:**
    -   Be extremely encouraging ("You're doing great!", "Good try!").
    -   Never describe things as "easy" or "simple" (this can be discouraging). Instead say "Let's break this down."
3.  **Multi-Sensory Cues:**
    -   Encourage visualization ("Imagine a big red apple").
    -   Suggest actions ("Trace the letter A in the air").
"""
        
        prompt = ""
        
        if mode == "teach":
            prompt = f"""
{system_prompt}
**Task: Teach Grade {grade if 'grade' in locals() else '1-5'} Content**
-   Break the concept into small steps.
-   Use emojis to create visual anchors (e.g., 🍎 for apple).
-   End with a "Check-in" question to ensure they understood.
-   Primary Source: {pdf_text[:2000] if pdf_text else 'No text provided. Use general knowledge.'}
Student Question: {user_message}
"""
        elif mode == "doubt":
            prompt = f"""
{system_prompt}
**Task: Doubt Solver**
-   Directly answer the question.
-   Use a real-world analogy (like pizza, colors, or games).
-   User Question: {user_message}
"""
        elif mode == "quiz":
            prompt = f"""
{system_prompt}
**Task: Adaptive Assessment**
Context: {pdf_text[:500] if pdf_text else 'General knowledge'}...
Student Message: "{user_message}"

If the student message looks like an answer, evaluate it efficiently.
If it's a request (e.g., "start"), generate a question.

Output format (Internal Use):
- **Evaluation**: (Correct/Incorrect/N/A)
- **Explanation**: (Short, encouraging feedback. If wrong, explain ONE key reason).
- **New Question**: (Ask a relevant, single-choice question).
- **Difficulty**: (1-10)
"""
        elif mode == "explain":
            text_to_explain = selected_text if selected_text else user_message
            prompt = f"""
{system_prompt}
**Task: Explain Text**
Explain this specific text: "{text_to_explain[:500]}"

Provide 3 short sections:
1.  **In a Nutshell** 🥜: One sentence summary.
2.  **Picture This** 🖼️: A visual analogy.
3.  **Why It Matters** 🌟: Connect it to their life.
"""
        elif mode == "diagram":
            prompt = f"""
{system_prompt}
**Task: Visual Diagram**
Create a CLEAR, simple ASCII art diagram for: '{user_message}'.
-   Use box-and-arrow style.
-   Keep labels short.
-   Add a 1-sentence caption explaining the drawing.
"""
        else:
            prompt = f"{system_prompt}\nJust chat nicely with the student. Respond to: {user_message}"
        
        # Use OpenAI model to generate response
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=MAX_TOKENS
        )
        
        if not response or not response.choices:
            return {"error": "Failed to generate response"}, 500
            
        ai_reply = response.choices[0].message.content

        # Post-process Quiz response for better display
        if mode == "quiz":
            try:
                # Parse the structured response
                lines = ai_reply.split('\n')
                quiz_data = {}
                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        quiz_data[key.strip('- *').lower()] = value.strip()
                
                # Format friendly response
                formatted_reply = ""
                
                # Handle Evaluation
                evaluation = quiz_data.get('evaluation', '').lower()
                if 'correct' in evaluation and 'incorrect' not in evaluation:
                    formatted_reply += "✅ **Correct!** 🎉\n\n"
                elif 'incorrect' in evaluation:
                    formatted_reply += "❌ **Not quite.** \n\n"
                
                # Add Explanation if present (and not just "N/A")
                explanation = quiz_data.get('explanation', '')
                if explanation and explanation != 'N/A':
                    formatted_reply += f"_{explanation}_\n\n"
                
                # Add New Question
                new_question = quiz_data.get('new question', '')
                if new_question:
                    formatted_reply += f"**Next Question:**\n{new_question}"
                
                # Fallback if parsing failed or empty
                if formatted_reply:
                    ai_reply = formatted_reply
            except Exception as e:
                print(f"Error parsing quiz response: {e}")
                # Leave ai_reply as is if parsing fails
        
        # Save to database
        conn = get_db()
        cur = conn.cursor()
        
        # Save user message
        if user_message:
            cur.execute("""
                INSERT INTO ai_tutor_sessions (student_id, role, message, timestamp)
                VALUES (?, ?, ?, ?)
            """, (user_id, "user", user_message, datetime.now(timezone.utc).isoformat()))
        
        # Save AI response
        cur.execute("""
            INSERT INTO ai_tutor_sessions (student_id, role, message, timestamp)
            VALUES (?, ?, ?, ?)
        """, (user_id, "assistant", ai_reply, datetime.now(timezone.utc).isoformat()))
        
        conn.commit()
        conn.close()
        
        return {
            "response": ai_reply,
            "session_id": session_id
        }
    
    except Exception as e:
        print(f"AI Tutor Error: {e}")
        return {"error": str(e)}, 500



# --- Student Progress API ---

@app.route("/api/save_progress", methods=["POST"])
@login_required(role="student")
def save_progress():
    user = session.get("user")
    data = request.json
    
    activity_type = data.get("activity_type")
    # Store data as JSON string
    import json
    progress_data = json.dumps(data.get("data"))
    
    if not activity_type or not progress_data:
        return jsonify({"error": "Missing data"}), 400
        
    conn = get_db()
    c = conn.cursor()
    
    # Upsert (Insert or Replace) logic
    try:
        c.execute("""
            INSERT INTO student_progress (student_id, activity_type, data_json, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, activity_type) 
            DO UPDATE SET data_json=excluded.data_json, last_updated=CURRENT_TIMESTAMP
        """, (user["id"], activity_type, progress_data))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error saving progress: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/load_progress/<activity_type>", methods=["GET"])
@login_required(role="student")
def load_progress(activity_type):
    user = session.get("user")
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT data_json FROM student_progress WHERE student_id = ? AND activity_type = ?", (user["id"], activity_type))
    row = c.fetchone()
    conn.close()
    
    if row:
        import json
        return jsonify({"success": True, "data": json.loads(row["data_json"])})
    else:
        return jsonify({"success": True, "data": None})


# ---------- Run ----------


@app.route("/api/submit_progress", methods=["POST"])
@login_required(role="student")
def submit_progress():
    """Save student progress/quiz attempts"""
    try:
        user = session.get("user")
        data = request.get_json()
        
        quiz_id = data.get("quiz_id")
        score = data.get("score")
        total = data.get("total")
        
        if not all([quiz_id, score is not None, total]):
            return {"error": "Missing data"}, 400
            
        conn = get_db()
        c = conn.cursor()
        
        c.execute("""
            INSERT INTO quiz_attempts (student_id, quiz_id, score, total, attempted_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user["id"], quiz_id, score, total, datetime.now(timezone.utc).isoformat()))
        
        conn.commit()
        conn.close()
        
        return {"success": True, "message": "Progress saved!"}
        
    except Exception as e:
        print(f"Error submitting progress: {e}")
        return {"error": str(e)}, 500



def send_reset_otp_email(email, name, otp):
    """Send password reset OTP email to the user"""
    print(f"DEBUG: Attempting to send OTP to {email}...")
    try:
        # Get email settings from environment variables
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        email_user = os.getenv('EMAIL_ADDRESS')
        email_password = os.getenv('EMAIL_PASSWORD')
        
        print(f"DEBUG: Using SMTP Server: {smtp_server}:{smtp_port}")
        print(f"DEBUG: Email User: {email_user}")
        
        if not email_user or not email_password:
            print("ERROR: EMAIL_ADDRESS or EMAIL_PASSWORD not configured in .env file")
            print(f"DEBUG: Falling back to console OTP: {otp}")
            return False
            
        # Create message
        msg = MIMEMultipart()
        msg['From'] = f"Udaan Team <{email_user}>"
        msg['To'] = email
        msg['Subject'] = f"{otp} is your Udaan Reset Code"
        
        # Email body
        body = f"""
Dear {name},

Your password reset OTP for Udaan Learning Platform is:

{otp}

This code will expire in 15 minutes.

If you did not request this password reset, please ignore this email.

Best regards,
The Udaan Team
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to server and send email
        print("DEBUG: Connecting to SMTP server...")
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
            server.starttls()  # Enable encryption
            
        print("DEBUG: Attempting to login...")
        server.login(email_user, email_password)
        text = msg.as_string()
        print("DEBUG: Sending mail...")
        server.sendmail(email_user, email, text)
        server.quit()
        
        print(f"SUCCESS: Password reset OTP sent successfully to {email}")
        return True
        
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to send email: {str(e)}")
        import traceback
        traceback.print_exc()
        # Fallback: print the OTP to console
        print(f"DEBUG: FALLBACK OTP: {otp}")
        return False


@app.route('/forgot-password/student', methods=["GET", "POST"])
def forgot_password_student():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        print(f"DEBUG: Password reset request for email: {email}")
        
        if not email:
            flash("Please enter your email address.")
            return redirect(url_for('forgot_password_student'))
        
        conn = get_db()
        c = conn.cursor()
        
        # Find student by email
        c.execute("SELECT id, name, email FROM students WHERE email = ?", (email,))
        student = c.fetchone()
        
        if not student:
            print(f"DEBUG: Email {email} not found in database.")
            flash(f"No account found with the email: {email}. Please check your spelling or register first.")
            return redirect(url_for('forgot_password_student'))
        
        print(f"DEBUG: Found student: {student['name']} (ID: {student['id']})")
        
        # Generate 6-digit OTP
        import random
        otp = str(random.randint(100000, 999999))
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        
        # Store OTP in database
        c.execute("UPDATE students SET reset_otp = ?, reset_otp_expires = ? WHERE id = ?",
                 (otp, expires_at, student['id']))
        conn.commit()
        conn.close()
        
        # Store email in session for the next step
        session['reset_email'] = email
        
        # Send the reset OTP email
        email_sent = send_reset_otp_email(student['email'], student['name'], otp)
        
        if email_sent:
            flash(f"A 6-digit OTP has been sent to your email. Please enter it below.")
        else:
            # Fallback for development
            flash(f"OTP generated. For development: {otp}")
        
        return redirect(url_for('verify_otp_student'))
    
    return render_template('forgot_password_student.html', request_method='GET')


@app.route('/verify-otp/student', methods=["GET", "POST"])
def verify_otp_student():
    email = session.get('reset_email')
    if not email:
        return redirect(url_for('forgot_password_student'))
        
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        
        if not otp:
            flash("Please enter the OTP.")
            return render_template('verify_otp_student.html')
            
        conn = get_db()
        c = conn.cursor()
        
        # Check if OTP is valid
        c.execute("SELECT id, reset_otp, reset_otp_expires FROM students WHERE email = ?", (email,))
        student = c.fetchone()
        
        if not student or student['reset_otp'] != otp:
            flash("Invalid OTP.")
            return render_template('verify_otp_student.html')
            
        # Check if OTP has expired
        expires_at = datetime.fromisoformat(student['reset_otp_expires'])
        if datetime.now(timezone.utc) > expires_at:
            flash("OTP has expired. Please request a new one.")
            return redirect(url_for('forgot_password_student'))
            
        # OTP is valid, generate a temporary token for the reset page
        reset_token = secrets.token_urlsafe(32)
        token_expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        c.execute("UPDATE students SET reset_token = ?, reset_token_expires = ?, reset_otp = NULL WHERE id = ?",
                 (reset_token, token_expires_at, student['id']))
        conn.commit()
        conn.close()
        
        return redirect(url_for('reset_password', token=reset_token))
        
    return render_template('verify_otp_student.html')


@app.route('/reset-password/<token>', methods=["GET", "POST"])
def reset_password(token):
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        if not password or not confirm_password:
            flash("Please enter both password fields.")
            return redirect(url_for('reset_password', token=token))
        
        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for('reset_password', token=token))
        
        if len(password) < 6:
            flash("Password must be at least 6 characters long.")
            return redirect(url_for('reset_password', token=token))
        
        conn = get_db()
        c = conn.cursor()
        
        # Check if token exists and hasn't expired
        c.execute("SELECT id FROM students WHERE reset_token = ? AND reset_token_expires > ?",
                 (token, datetime.now(timezone.utc).isoformat()))
        student = c.fetchone()
        
        if not student:
            flash("Invalid or expired reset token.")
            conn.close()
            return redirect(url_for('forgot_password_student'))
        
        # Hash the new password
        password_hash = generate_password_hash(password)
        
        # Update password and clear the reset token
        c.execute("UPDATE students SET password_hash = ?, reset_token = NULL, reset_token_expires = NULL WHERE reset_token = ?",
                 (password_hash, token))
        conn.commit()
        conn.close()
        
        flash("Your password has been reset successfully. You can now log in.")
        return redirect(url_for('login_student'))
    
    # Check if token is valid for GET request
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM students WHERE reset_token = ? AND reset_token_expires > ?",
             (token, datetime.now(timezone.utc).isoformat()))
    student = c.fetchone()
    conn.close()
    
    if not student:
        flash("Invalid or expired reset token.")
        return redirect(url_for('forgot_password_student'))
    
    return render_template('reset_password.html')


# Initialize DB and Migrations on startup (Required for Gunicorn/Render)
# This ensures tables are created even if the app defaults to basic tables
try:
    init_db()
    # Run migration to handle existing databases that may not have all columns
    migrate_student_progress_table()
    # Run additional database migration to ensure schema matches production
    migrate_database()
    # Create default teacher accounts for each grade
    create_default_teachers()
except Exception as e:
    print(f"Startup DB Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  
    app.run(host='0.0.0.0', port=port, debug=True)
