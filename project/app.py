from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from functools import wraps
import PyPDF2
import pyttsx3
import time
import google.generativeai as genai
from deep_translator import GoogleTranslator
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
# from googletrans import Translator
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from PyPDF2 import PdfReader
import fitz 
import pytesseract
from PIL import Image
import json
import re
from pdf2image import convert_from_path
import pytesseract
import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load .env file
load_dotenv()


# Get the API key from .env
api_key = os.getenv("GEMINI_API_KEY")

# Configure Gemini (only once)
if api_key and api_key.strip():
    genai.configure(api_key=api_key)
    print("INFO: Gemini API key loaded successfully")
else:
    print("WARNING: GEMINI_API_KEY not found in .env file. AI features will not work.")

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


app = Flask(__name__)
app.secret_key = "dev-secret-change-this"  
DB = "database.db"
books=[]

BOOKS_FOLDER = os.path.join("static", "books")
os.makedirs(BOOKS_FOLDER, exist_ok=True)

UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "static/audio"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Hybrid PDF Text Extraction
def extract_text_hybrid(pdf_path):
    """Try PyPDF2 first, if no text then fallback to OCR."""
    text = ""
    try:
        pdf_reader = PyPDF2.PdfReader(open(pdf_path, "rb"))
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        print("⚠️ Error reading with PyPDF2:", e)

    if text.strip():
        return text

    # Fallback: OCR
    print("⚠️ No text found, using OCR...")
    try:
        pages = convert_from_path(pdf_path)
        for page in pages:
            text += pytesseract.image_to_string(page)
    except Exception as e:
        print("⚠️ OCR failed:", e)

    return text

def text_to_pdf(text, output_pdf, font_path, font_size=12):
    print("Registering font:", font_path)  # Debug
    pdfmetrics.registerFont(TTFont("CustomFont", font_path))
    c = canvas.Canvas(output_pdf, pagesize=A4)
    width, height = A4
    left_margin = 50
    top_margin = height - 50
    bottom_margin = 50
    line_height = font_size + 4  # Add a little spacing

    textobject = c.beginText(left_margin, top_margin)
    textobject.setFont("CustomFont", font_size)

    for line in text.split("\n"):
        if textobject.getY() < bottom_margin:
            c.drawText(textobject)
            c.showPage()
            textobject = c.beginText(left_margin, top_margin)
            textobject.setFont("CustomFont", font_size)
        textobject.textLine(line)
    c.drawText(textobject)
    c.save()

# Translation 
def translate_pdf_to_pdf(input_pdf, output_pdf, target_lang, font_path):
    font_name = f"Font_{target_lang}"
    pdfmetrics.registerFont(TTFont(font_name, font_path))
    # translator = Translator()

    with open(input_pdf, "rb") as book:
        reader = PyPDF2.PdfReader(book)
        c = canvas.Canvas(output_pdf, pagesize=A4)
        width, height = A4

        for num in range(len(reader.pages)):
            text = reader.pages[num].extract_text()
            if text:
                # Skip translation since translator is not properly configured
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
    # Try to use Gemini model with fallback
    model = None
    model_names = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]
    
    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name)
            # Test if model works
            test_response = model.generate_content("Hello, are you there?")
            if test_response and hasattr(test_response, 'text'):
                break
            model = None
        except Exception as e:
            continue
    
    if model is None:
        return {"error": "No compatible Gemini model found"}
    
    # Ask Gemini to generate diagram data
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
    
    try:
        # Generate response
        response = model.generate_content(prompt)
        
        if not response or not hasattr(response, 'text'):
            return {"error": "Failed to generate diagram data"}
        
        # Parse the JSON response
        import json
        import re
        
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{{.*\}}', response.text, re.DOTALL)
        if not json_match:
            return {"error": "Invalid response format from AI"}
        
        diagram_data = json.loads(json_match.group().replace("'", '"'))
        
        return diagram_data
    
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return {"error": "Invalid JSON response from AI"}
    except Exception as e:
        print(f"Error in extract_labels_for_dragdrop: {e}")
        return {"error": str(e)}

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        age INTEGER,
        grade TEXT,
        accessibility TEXT,
        email TEXT,
        phone TEXT,
        password_hash TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        password_hash TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        filename TEXT,
        uploaded_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS flashcards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        filename TEXT,
        num_flashcards INTEGER,
        created_at TEXT,
        data TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        quiz_id TEXT,
        score INTEGER,
        total INTEGER,
        attempted_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )""")
    
    # Create AI Tutor sessions table
    c.execute("""CREATE TABLE IF NOT EXISTS ai_tutor_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        role TEXT,          -- 'user' or 'assistant'
        message TEXT,
        difficulty INTEGER DEFAULT 3,
        timestamp TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )""")
    
    # Create puzzle_data table for drag-and-drop game
    c.execute("""CREATE TABLE IF NOT EXISTS puzzle_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        filename TEXT,
        puzzle_json TEXT,
        created_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )""")
    
    conn.commit()
    conn.close()


def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user:
                flash("Please log in first.")
                return redirect(url_for("index"))
            if role and user.get("role") != role:
                flash(f"Access restricted to {role}s only.")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapped
    return decorator

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
    if role not in ("student", "teacher"):
        flash("Invalid role selected.")
        return redirect(url_for("index"))
    return render_template("auth_options.html", role=role)

# Student signup/login 
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
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
    return render_template("signup_student.html")

@app.route("/login/student", methods=["GET", "POST"])
def login_student():
    if request.method == "POST":
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
            session["user"] = {"role": "student", "id": user["id"], "name": user["name"], "grade": user["grade"]}
            # Redirect to grade-specific dashboard for grades 1-5
            if user["grade"] and user["grade"] in ["1", "2", "3", "4", "5"]:
                return redirect(url_for(f"grade_{user['grade']}_dashboard"))
            else:
                # For grades outside 1-5, redirect to general student dashboard
                return redirect(url_for("student_dashboard"))
        else:
            flash("Incorrect password.")
            return redirect(request.url)
    return render_template("login_student.html")

# Teacher signup/login
@app.route("/signup/teacher", methods=["GET", "POST"])
def signup_teacher():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email") or None
        phone = request.form.get("phone") or None
        password = request.form.get("password") or None
        if not name:
            flash("Name is required.")
            return redirect(request.url)

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM teachers WHERE name = ?", (name,))
        if cur.fetchone():
            flash("A teacher/parent with that name already exists.")
            conn.close()
            return redirect(url_for("index"))

        if not password:
            flash("Password is required.")
            conn.close()
            return redirect(request.url)

        password_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO teachers (name, email, phone, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (name, email, phone, password_hash, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
        flash("Teacher/Parent signed up successfully. Please login.")
        return redirect(url_for("index"))
    return render_template("signup_teacher.html")

@app.route("/login/teacher", methods=["GET", "POST"])
def login_teacher():
    if request.method == "POST":
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
            session["user"] = {"role": "teacher", "id": user["id"], "name": user["name"]}
            return redirect(url_for("teacher_dashboard"))
        else:
            flash("Incorrect password.")
            return redirect(request.url)
    return render_template("login_teacher.html")

# Student Dashboard 
@app.route("/dashboard/student")
@login_required(role="student")
def student_dashboard():
    user = session.get("user")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE student_id = ?", (user["id"],))
    uploads = cur.fetchall()
    
    # Calculate progress metrics
    total_uploads = len(uploads)
    
    # Get flashcards count
    cur.execute("SELECT COUNT(*) as count, SUM(num_flashcards) as total FROM flashcards WHERE student_id = ?", (user["id"],))
    flashcard_data = cur.fetchone()
    total_flashcards = flashcard_data["total"] or 0
    
    # Get quiz attempts
    cur.execute("SELECT COUNT(*) as count, AVG(score) as avg_score FROM quiz_attempts WHERE student_id = ?", (user["id"],))
    quiz_data = cur.fetchone()
    total_quizzes = quiz_data["count"] or 0
    avg_quiz_score = quiz_data["avg_score"] or 0
    
    # Calculate progress percentage (weighted average of activities)
    progress_percentage = 0
    # Only calculate progress if the student has any activities
    if total_uploads > 0 or total_flashcards > 0 or total_quizzes > 0:
        # Base progress on uploads, flashcards, and quizzes with more reasonable weighting
        # Max points: 40 (uploads) + 30 (flashcards) + 30 (quizzes) = 100
        upload_points = min(40, total_uploads * 10)  # Up to 40 points for uploads
        flashcard_points = min(30, total_flashcards * 2)  # Up to 30 points for flashcards
        quiz_points = min(30, total_quizzes * 10)  # Up to 30 points for quizzes
        activity_score = upload_points + flashcard_points + quiz_points
        progress_percentage = min(100, activity_score)
    
    # Calculate progress width as percentage
    progress_width_percent = int(progress_percentage) if progress_percentage > 0 else 0
    
    conn.close()
    return render_template("student_dashboard.html", 
                         name=user.get("name"), 
                         uploads=uploads,
                         progress_percent=int(progress_percentage),
                         progress_width=progress_width_percent)

# Grade-specific Dashboard Routes
@app.route("/dashboard/grade/1")
@login_required(role="student")
def grade_1_dashboard():
    user = session.get("user")
    if user.get("grade") != "1":
        flash("Access denied. This dashboard is for Grade 1 students only.")
        return redirect(url_for("student_dashboard"))
    return render_template("grade_1_dashboard.html", user=user)

@app.route("/dashboard/grade/2")
@login_required(role="student")
def grade_2_dashboard():
    user = session.get("user")
    if user.get("grade") != "2":
        flash("Access denied. This dashboard is for Grade 2 students only.")
        return redirect(url_for("student_dashboard"))
    return render_template("grade_2_dashboard.html", user=user)

@app.route("/dashboard/grade/3")
@login_required(role="student")
def grade_3_dashboard():
    user = session.get("user")
    if user.get("grade") != "3":
        flash("Access denied. This dashboard is for Grade 3 students only.")
        return redirect(url_for("student_dashboard"))
    return render_template("grade_3_dashboard.html", user=user)

@app.route("/dashboard/grade/4")
@login_required(role="student")
def grade_4_dashboard():
    user = session.get("user")
    if user.get("grade") != "4":
        flash("Access denied. This dashboard is for Grade 4 students only.")
        return redirect(url_for("student_dashboard"))
    return render_template("grade_4_dashboard.html", user=user)

@app.route("/dashboard/grade/5")
@login_required(role="student")
def grade_5_dashboard():
    user = session.get("user")
    if user.get("grade") != "5":
        flash("Access denied. This dashboard is for Grade 5 students only.")
        return redirect(url_for("student_dashboard"))
    return render_template("grade_5_dashboard.html", user=user)

@app.route("/upload_textbook", methods=["POST"])
@login_required(role="student")
def upload_textbook():
    if "textbook" not in request.files:
        flash("No file selected.")
        return redirect(url_for("student_dashboard"))
    file = request.files["textbook"]
    if file.filename == "":
        flash("No file selected.")
        return redirect(url_for("student_dashboard"))

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
    return redirect(url_for("student_dashboard"))

@app.route("/library")
@login_required(role="student")
def library():
    books_folder = os.path.join(app.static_folder, "books")
    if not os.path.exists(books_folder):
        os.makedirs(books_folder)

    books = sorted(
        os.listdir(books_folder),
        key=lambda x: os.path.getmtime(os.path.join(books_folder, x)),
        reverse=True
    )

    return render_template("library.html", books=books)


@app.route("/audio_narration", methods=["POST"])
@login_required(role="student")
def audio_narration():
    filename = session.get("uploaded_file")
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect(url_for("student_dashboard"))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(filepath):
        flash("File not found on server.")
        return redirect(url_for("student_dashboard"))

    # extracting text directly 
    text = ""
    try:
        pdf_reader = PdfReader(open(filepath, "rb"))
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        flash(f"Error reading PDF: {str(e)}")
        return redirect(url_for("student_dashboard"))

    # Fallback to OCR 
    if not text.strip():
        flash("⚠️ No text found, using OCR...")
        try:
            doc = fitz.open(filepath)
            ocr_text = []
            for page_num in range(len(doc)):
                pix = doc[page_num].get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text.append(pytesseract.image_to_string(img))
            text = "\n".join(ocr_text)
        except Exception as e:
            flash(f"⚠️ OCR failed: {str(e)}")
            return redirect(url_for("student_dashboard"))

    if not text.strip():
        flash("⚠️ Still no readable text found after OCR.")
        return redirect(url_for("student_dashboard"))

    # Generate narration
    student_id = session["user"]["id"]
    timestamp = int(time.time())
    audio_filename = f"{student_id}_{timestamp}.mp3"
    audio_path = os.path.join("static/narrations", audio_filename)
    os.makedirs("static/narrations", exist_ok=True)

    # Convert text to speech
    try:
        engine = pyttsx3.init()
        engine.save_to_file(text, audio_path)
        engine.runAndWait()
    except Exception as e:
        flash(f"Error generating narration: {str(e)}")
        return redirect(url_for("student_dashboard"))

    flash("🎧 Audio narration generated successfully!")

    user = session.get("user")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE student_id = ?", (user["id"],))
    uploads = cur.fetchall()

    # Calculate progress metrics
    total_uploads = len(uploads)
    
    # Get flashcards count
    cur.execute("SELECT COUNT(*) as count, SUM(num_flashcards) as total FROM flashcards WHERE student_id = ?", (user["id"],))
    flashcard_data = cur.fetchone()
    total_flashcards = flashcard_data["total"] or 0
    
    # Get quiz attempts
    cur.execute("SELECT COUNT(*) as count, AVG(score) as avg_score FROM quiz_attempts WHERE student_id = ?", (user["id"],))
    quiz_data = cur.fetchone()
    total_quizzes = quiz_data["count"] or 0
    
    # Calculate progress percentage (weighted average of activities)
    progress_percentage = 0
    # Only calculate progress if the student has any activities
    if total_uploads > 0 or total_flashcards > 0 or total_quizzes > 0:
        # Base progress on uploads, flashcards, and quizzes with more reasonable weighting
        # Max points: 40 (uploads) + 30 (flashcards) + 30 (quizzes) = 100
        upload_points = min(40, total_uploads * 10)  # Up to 40 points for uploads
        flashcard_points = min(30, total_flashcards * 2)  # Up to 30 points for flashcards
        quiz_points = min(30, total_quizzes * 10)  # Up to 30 points for quizzes
        activity_score = upload_points + flashcard_points + quiz_points
        progress_percentage = min(100, activity_score)
    
    # Calculate progress width as percentage
    progress_width_percent = int(progress_percentage) if progress_percentage > 0 else 0
    
    conn.close()
    
    return render_template(
        "student_dashboard.html",
        name=user.get("name"),
        uploads=uploads,
        audio_file=audio_filename,
        progress_percent=int(progress_percentage),
        progress_width=progress_width_percent
    )


@app.route("/generate_summary", methods=["POST"])
@login_required(role="student")
def generate_summary():
    print("DEBUG: Starting generate_summary function")
    
    # Debug: Check what's in the session
    filename = session.get("uploaded_file")
    print(f"DEBUG: Session uploaded_file = {filename}")
    flash(f"Debug: Session uploaded_file = {filename}")
    
    if not filename:
        # Try to get the most recent upload from database as fallback
        user = session.get("user")
        print(f"DEBUG: No file in session, checking database for user {user['id'] if user else 'None'}")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT filename FROM uploads WHERE student_id = ? ORDER BY uploaded_at DESC LIMIT 1", (user["id"],))
        result = cur.fetchone()
        conn.close()
        
        if result:
            filename = result["filename"]
            print(f"DEBUG: Found recent upload = {filename}")
            flash(f"Fallback: Found recent upload = {filename}")
        else:
            print("DEBUG: No uploaded file found in session or database")
            flash("No textbook uploaded yet.")
            return redirect(url_for("student_dashboard"))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    print(f"DEBUG: Looking for file at {filepath}")
    flash(f"Debug: Looking for file at {filepath}")
    
    if not os.path.exists(filepath):
        print(f"DEBUG: File not found at {filepath}")
        flash(f"File not found on server at {filepath}.")
        return redirect(url_for("student_dashboard"))

    # extracting text directly 
    text = ""
    try:
        print(f"DEBUG: Attempting to read PDF file {filepath}")
        pdf_reader = PdfReader(open(filepath, "rb"))
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        print(f"DEBUG: Successfully read PDF, extracted {len(text)} characters")
    except Exception as e:
        print(f"DEBUG: Error reading PDF: {str(e)}")
        flash(f"Error reading PDF: {str(e)}")
        return redirect(url_for("student_dashboard"))

    # Fallback to OCR 
    if not text.strip():
        print("DEBUG: No text found in PDF, attempting OCR")
        flash("⚠️ No text found, using OCR...")
        try:
            doc = fitz.open(filepath)
            ocr_text = []
            for page_num in range(len(doc)):
                pix = doc[page_num].get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text.append(pytesseract.image_to_string(img))
            text = "\n".join(ocr_text)
            print(f"DEBUG: OCR completed, extracted {len(text)} characters")
        except Exception as e:
            print(f"DEBUG: OCR failed: {str(e)}")
            flash(f"⚠️ OCR failed: {str(e)}")
            return redirect(url_for("student_dashboard"))

    if not text.strip():
        print("DEBUG: Still no readable text found after OCR")
        flash("⚠️ Still no readable text found after OCR.")
        return redirect(url_for("student_dashboard"))

    # Show text length for debugging
    print(f"DEBUG: Final text length: {len(text)} characters")
    flash(f"Extracted text length: {len(text)} characters")
    
    # Generate summary via Gemini 
    flash("Generating summary... this may take a few seconds.")

    try:
        # Check if API key is configured
        print(f"DEBUG: Checking API key - api_key = {'SET' if api_key and api_key.strip() else 'NOT SET'}")
        if not api_key or not api_key.strip():
            print("DEBUG: API key not configured")
            flash("⚠️ Gemini API key is not configured. Please contact administrator.")
            flash("To fix this, add your Gemini API key to the .env file in the project directory.")
            return redirect(url_for("student_dashboard"))
            
        # Check if Gemini is configured
        try:
            print("DEBUG: Initializing Gemini model")
            # Try different model names that are commonly available
            model_names = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro", "gemini-1.0-pro", "models/gemini-2.0-flash", "models/gemini-1.5-flash", "models/gemini-pro"]
            model = None
            
            for model_name in model_names:
                try:
                    model = genai.GenerativeModel(model_name)
                    # Test if model works
                    test_response = model.generate_content("Hello, are you there?")
                    if test_response and hasattr(test_response, 'text'):
                        print(f"DEBUG: Successfully initialized model {model_name}")
                        flash(f"Using model: {model_name}")
                        break
                    model = None
                except Exception as e:
                    print(f"DEBUG: Model {model_name} not available: {str(e)}")
                    continue
                    
            if model is None:
                flash("⚠️ No compatible Gemini model found. Please check your API key and quota.")
                return redirect(url_for("student_dashboard"))
                
        except Exception as e:
            print(f"DEBUG: Failed to initialize Gemini API: {str(e)}")
            flash("⚠️ Failed to initialize Gemini API. Please check your API key.")
            return redirect(url_for("student_dashboard"))
            
        # Limit text to prevent token overflow
        prompt = f"Please provide a simplified summary of the following textbook content. Keep it concise but informative:\n\n{text[:8000]}"
        print(f"DEBUG: Sending prompt with {len(prompt)} characters to Gemini API")
        
        # Add debug info
        flash(f"Sending prompt with {len(prompt)} characters to Gemini API")
        
        response = model.generate_content(prompt)
        print(f"DEBUG: Received response from Gemini API")
        
        # Check if we got a response
        if response is None:
            print("DEBUG: No response received from Gemini API")
            flash("⚠️ No response received from Gemini API.")
            return redirect(url_for("student_dashboard"))
            
        if not hasattr(response, 'text'):
            print(f"DEBUG: Response missing text attribute. Response type: {type(response)}")
            # Check for safety ratings or other blocking issues
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                print(f"DEBUG: Prompt blocked due to safety concerns: {response.prompt_feedback}")
                flash(f"⚠️ Gemini API blocked the request due to safety concerns: {response.prompt_feedback}")
                return redirect(url_for("student_dashboard"))
                
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'finish_reason') and candidate.finish_reason != "STOP":
                        print(f"DEBUG: Generation stopped early. Reason: {candidate.finish_reason}")
                        flash(f"⚠️ Gemini API stopped generation early. Reason: {candidate.finish_reason}")
                        return redirect(url_for("student_dashboard"))
                        
            print("DEBUG: Unexpected response format from Gemini API")
            flash("⚠️ Unexpected response format from Gemini API.")
            return redirect(url_for("student_dashboard"))
            
        summary = response.text
        print(f"DEBUG: Generated summary with {len(summary)} characters")
        
        # Check if summary is empty
        if not summary.strip():
            print("DEBUG: Generated summary was empty")
            flash("⚠️ Generated summary was empty. Please try again.")
            return redirect(url_for("student_dashboard"))
            
        flash(f"Successfully generated summary with {len(summary)} characters")
        print(f"DEBUG: Successfully generated summary")
        
    except Exception as e:
        print(f"DEBUG: Error generating summary: {str(e)}")
        flash(f"Error generating summary: {str(e)}")
        return redirect(url_for("student_dashboard"))

    # Refresh uploads list for dashboard
    user = session.get("user")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE student_id = ?", (user["id"],))
    uploads = cur.fetchall()
    
    # Calculate progress metrics
    total_uploads = len(uploads)
    
    # Get flashcards count
    cur.execute("SELECT COUNT(*) as count, SUM(num_flashcards) as total FROM flashcards WHERE student_id = ?", (user["id"],))
    flashcard_data = cur.fetchone()
    total_flashcards = flashcard_data["total"] or 0
    
    # Get quiz attempts
    cur.execute("SELECT COUNT(*) as count, AVG(score) as avg_score FROM quiz_attempts WHERE student_id = ?", (user["id"],))
    quiz_data = cur.fetchone()
    total_quizzes = quiz_data["count"] or 0
    
    # Calculate progress percentage (weighted average of activities)
    progress_percentage = 0
    # Only calculate progress if the student has any activities
    if total_uploads > 0 or total_flashcards > 0 or total_quizzes > 0:
        # Base progress on uploads, flashcards, and quizzes with more reasonable weighting
        # Max points: 40 (uploads) + 30 (flashcards) + 30 (quizzes) = 100
        upload_points = min(40, total_uploads * 10)  # Up to 40 points for uploads
        flashcard_points = min(30, total_flashcards * 2)  # Up to 30 points for flashcards
        quiz_points = min(30, total_quizzes * 10)  # Up to 30 points for quizzes
        activity_score = upload_points + flashcard_points + quiz_points
        progress_percentage = min(100, activity_score)
    
    # Calculate progress width as percentage
    progress_width_percent = int(progress_percentage) if progress_percentage > 0 else 0
    
    conn.close()

    return render_template(
        "student_dashboard.html",
        name=user.get("name"),
        uploads=uploads,
        summary=summary,
        audio_file=session.get("audio_file"),
        progress_percent=int(progress_percentage),
        progress_width=progress_width_percent
    )

@app.route("/translate_text", methods=["POST"])
@login_required(role="student")
def translate_text():
    filename = session.get("uploaded_file")
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect(url_for("student_dashboard"))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(filepath):
        flash("File not found on server.")
        return redirect(url_for("student_dashboard"))

    # --- Step 1: Extract text directly from PDF ---
    text = ""
    try:
        pdf_reader = PdfReader(open(filepath, "rb"))
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text
    except Exception as e:
        flash(f"Error reading PDF: {str(e)}")
        return redirect(url_for("student_dashboard"))

    # --- Step 2: Fallback to OCR if no text ---
    if not text.strip():
        flash("⚠️ No text found, using OCR...")
        try:
            doc = fitz.open(filepath)
            ocr_text = []
            for page_num in range(len(doc)):
                pix = doc[page_num].get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_result = pytesseract.image_to_string(img)
                ocr_text.append(ocr_result if isinstance(ocr_result, str) else "")
            text = "\n".join(ocr_text)
        except Exception as e:
            flash(f"⚠️ OCR failed: {str(e)}")
            return redirect(url_for("student_dashboard"))

    if not text.strip():
        flash("⚠️ Still no readable text found after OCR.")
        return redirect(url_for("student_dashboard"))

    # --- Step 3: Prepare output file ---
    os.makedirs("static/translations", exist_ok=True)
    base = os.path.splitext(filename)[0]
    hindi_file = f"{base}_hindi.pdf"
    hindi_path = os.path.join("static/translations", hindi_file)

    # --- Step 4: Translation with Gemini ---
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Translate to Hindi
        prompt_hi = f"Translate the following English educational text into Hindi, keep it clear and natural and don't bold anything. No * please:\n\n{text}"
        response_hi = model.generate_content(prompt_hi)
        print("Gemini Hindi response:", response_hi.text)  # DEBUG
        hindi_text = response_hi.text if response_hi and response_hi.text else text

        # --- Clean up Gemini output ---
        def clean_text(t):
            t = re.sub(r"```(?:\w+)?", "", t)  # Remove markdown code blocks
            t = t.replace("```", "")
            t = t.strip()
            return t

        hindi_text = clean_text(hindi_text)

        # --- Step 5: Save PDF with proper font ---
        hindi_font_path = os.path.join(os.path.dirname(__file__), "NotoSansDevanagari-Regular.ttf")

        if not os.path.exists(hindi_font_path):
            flash("Hindi font file not found. Please add NotoSansDevanagari-Regular.ttf to your project folder.")
            return redirect(url_for("student_dashboard"))

        text_to_pdf(hindi_text, hindi_path, hindi_font_path)

    except Exception as e:
        flash(f"Error during translation: {str(e)}")
        return redirect(url_for("student_dashboard"))

    flash("✅ Hindi translation ready for download!")

    # --- Step 6: Refresh uploads list for dashboard ---
    user = session.get("user")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE student_id = ?", (user["id"],))
    uploads = cur.fetchall()
    
    # Calculate progress metrics
    total_uploads = len(uploads)
    
    # Get flashcards count
    cur.execute("SELECT COUNT(*) as count, SUM(num_flashcards) as total FROM flashcards WHERE student_id = ?", (user["id"],))
    flashcard_data = cur.fetchone()
    total_flashcards = flashcard_data["total"] or 0
    
    # Get quiz attempts
    cur.execute("SELECT COUNT(*) as count, AVG(score) as avg_score FROM quiz_attempts WHERE student_id = ?", (user["id"],))
    quiz_data = cur.fetchone()
    total_quizzes = quiz_data["count"] or 0
    
    # Calculate progress percentage (weighted average of activities)
    progress_percentage = 0
    # Only calculate progress if the student has any activities
    if total_uploads > 0 or total_flashcards > 0 or total_quizzes > 0:
        # Base progress on uploads, flashcards, and quizzes with more reasonable weighting
        # Max points: 40 (uploads) + 30 (flashcards) + 30 (quizzes) = 100
        upload_points = min(40, total_uploads * 10)  # Up to 40 points for uploads
        flashcard_points = min(30, total_flashcards * 2)  # Up to 30 points for flashcards
        quiz_points = min(30, total_quizzes * 10)  # Up to 30 points for quizzes
        activity_score = upload_points + flashcard_points + quiz_points
        progress_percentage = min(100, activity_score)
    
    # Calculate progress width as percentage
    progress_width_percent = int(progress_percentage) if progress_percentage > 0 else 0
    
    conn.close()

    return render_template(
        "student_dashboard.html",
        name=user.get("name"),
        uploads=uploads,
        hindi_file=hindi_file,
        progress_percent=int(progress_percentage),
        progress_width=progress_width_percent
    )

@app.route("/dyslexic_friendly", methods=["GET", "POST"])
@login_required(role="student")
def dyslexic_friendly():
    """
    Show a dyslexic-friendly reader for the currently uploaded PDF.

    - Do NOT store the extracted text in the Flask session
      (it makes the cookie too large).
    - Always re-read from the uploaded PDF whenever this view is hit.
    """
    filename = session.get("uploaded_file")
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect(url_for("student_dashboard"))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(filepath):
        flash("File not found on server.")
        return redirect(url_for("student_dashboard"))

    # Use the existing hybrid extractor (PyPDF2 + OCR fallback)
    raw_text = extract_text_hybrid(filepath)

    if not raw_text or not raw_text.strip():
        flash("⚠️ Still no readable text found, even after OCR.")
        return redirect(url_for("student_dashboard"))

    # Keep the text as plain text with newlines.
    # We will handle formatting and word-wrapping on the client.
    clean_text = raw_text

    print("DEBUG dyslexic_friendly: text length sent to template =", len(clean_text))

    return render_template("dyslexic_reader.html", text=clean_text)



@app.route("/generate_flashcards", methods=["POST"])
@login_required(role="student")
def generate_flashcards():
    import json, re
    filename = session.get("uploaded_file")

    # Validate filename BEFORE any DB operation
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect(url_for("student_dashboard"))

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
        (session["user"]["id"], filename)
    )
    conn.commit()
    conn.close()

    # ------------------------
    # Extract text from PDF
    # ------------------------
    text = ""
    try:
        pdf_reader = PdfReader(open(filepath, "rb"))
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    except:
        text = ""

    if not text.strip():
        try:
            doc = fitz.open(filepath)
            ocr_text = []
            for page_num in range(len(doc)):
                pix = doc[page_num].get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text.append(pytesseract.image_to_string(img))
            text = "\n".join(ocr_text)
        except:
            flash("⚠️ Unable to extract text from PDF.")
            return redirect(url_for("student_dashboard"))

    # ------------------------
    # Generate flashcards (10)
    # ------------------------
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = (
        "Generate 10 flashcards from the following text. "
        "Return ONLY JSON array in this format: "
        "[{\"question\":\"...\", \"answer\":\"...\"}]\n\n"
        f"{text[:4000]}"
    )

    try:
        resp = model.generate_content(prompt)
        raw = resp.text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError("No JSON array found.")

        json_array = match.group()
        flashcards = json.loads(json_array)

    except Exception as e:
        flash(f"Error generating flashcards: {str(e)}")
        return redirect(url_for("student_dashboard"))

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
            session["user"]["id"],
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
                    session["user"]["id"],
                    filename,
                    json.dumps(puzzle_data),
                    datetime.now(timezone.utc).isoformat()
                )
            )
    except Exception as e:
        print(f"Error generating puzzle data: {e}")
    
    conn.commit()
    conn.close()

    return render_template("flashcard.html", flashcards=flashcards)

@app.route("/generate_quiz", methods=["POST"])
@login_required(role="student")
def generate_quiz():
    filename = session.get("uploaded_file")
    if not filename:
        flash("No textbook uploaded yet.")
        return redirect(url_for("student_dashboard"))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    # Extract text
    text = ""
    try:
        pdf_reader = PdfReader(open(filepath, "rb"))
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        flash(f"Error reading PDF: {str(e)}")
        return redirect(url_for("student_dashboard"))

    # Fallback to OCR 
    if not text.strip():
        flash("⚠️ No text found, using OCR...")
        try:
            doc = fitz.open(filepath)
            ocr_text = []
            for page_num in range(len(doc)):
                pix = doc[page_num].get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text.append(pytesseract.image_to_string(img))
            text = "\n".join(ocr_text)
        except Exception as e:
            flash(f"⚠️ OCR failed: {str(e)}")
            return redirect(url_for("student_dashboard"))

    if not text.strip():
        flash("⚠️ Still no readable text found after OCR.")
        return redirect(url_for("student_dashboard"))

    # Generate quiz with Gemini 
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = f"""
Create a multiple-choice quiz (MCQ) of 10 questionsfrom the following text.  
Make sure to cover all important concepts.  

⚠️ Important formatting rules:  
- Each option **must** start with a letter and a dot, like "A. ...", "B. ...", "C. ...", "D. ...".  
- The "answer" field must contain only the **letter** ("A", "B", "C", or "D"), not the full text.  

Strictly return valid JSON in this format:

[
  {{
    "question": "What is ...?",
    "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
    "answer": "B"
  }},
  ...
]

Text:
{text[:6000]}
"""


        response = model.generate_content(prompt)
        raw = response.text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        quiz = json.loads(raw)

    except Exception as e:
        flash(f"Error generating quiz: {str(e)}")
        return redirect(url_for("student_dashboard"))

    session["quiz"] = quiz
    session["quiz_file"] = filename  

    return render_template("quiz.html", quiz=quiz)

@app.route("/submit_quiz", methods=["POST"])
@login_required(role="student")
def submit_quiz():
    quiz = session.get("quiz")
    if not quiz:
        flash("No quiz found.")
        return redirect(url_for("student_dashboard"))

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

    return render_template("quiz_results.html", score=score, total=len(quiz), results=results)

# ---------- Teacher Dashboard ----------
@app.route("/dashboard/teacher")
@login_required(role="teacher")
def teacher_dashboard():
    user = session.get("user")
    conn = get_db()
    cur = conn.cursor()

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

    # Sort by activity descending and keep top 6 for the dashboard list
    recent_students.sort(key=lambda s: s["activity"], reverse=True)
    recent_students = recent_students[:6]

    num_students = len(students)
    class_avg_pct = 0
    if num_students and total_quizzes:
        class_avg_pct = round((total_scores / num_students) * 100, 1)

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
    )


@app.route("/upload_books", methods=["GET", "POST"])
@login_required(role="teacher")
def upload_books():
    if request.method == "POST":
        if "book" not in request.files:
            flash("No file selected")
            return redirect(request.url)
        file = request.files["book"]
        if file.filename.endswith(".pdf"):
            filepath = os.path.join(BOOKS_FOLDER, file.filename)
            file.save(filepath)
            flash("Book uploaded successfully!")
            return redirect(url_for("upload_books"))
        else:
            flash("Only PDF files allowed!")
            return redirect(request.url)

    all_books = sorted(
        [f for f in os.listdir(BOOKS_FOLDER) if f.lower().endswith(".pdf")],
        key=lambda x: os.path.getmtime(os.path.join(BOOKS_FOLDER, x)),
        reverse=True
    )
    return render_template("upload_books.html", books=all_books)


@app.route("/student_progress")
@login_required(role="teacher")
def student_progress():
    conn = get_db()
    cur = conn.cursor()

    filter_id = request.args.get("student_id")
    if filter_id:
        cur.execute("SELECT * FROM students WHERE id = ?", (filter_id,))
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
    flash("Logged out.")
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

        # Generate audio using pyttsx3 (blocking)
        try:
            engine = pyttsx3.init()
            engine.save_to_file(raw_text, audio_path)
            engine.runAndWait()
        except Exception as e:
            return {"error": f"TTS failed: {str(e)}"}, 500

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
        
        # Try to use Gemini model with fallback
        model = None
        model_names = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                # Test if model works
                test_response = model.generate_content("Hello, are you there?")
                if test_response and hasattr(test_response, 'text'):
                    break
                model = None
            except Exception as e:
                continue
        
        if model is None:
            conn.close()
            return {"error": "No compatible Gemini model found"}, 500
        
        # Ask Gemini to generate diagram data
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
        
        # Generate response
        response = model.generate_content(prompt)
        
        if not response or not hasattr(response, 'text'):
            conn.close()
            return {"error": "Failed to generate diagram data"}, 500
        
        # Parse the JSON response
        import json
        import re
        
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
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
    
    # Try to use Gemini model with fallback
    model = None
    model_names = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]
    
    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name)
            # Test if model works
            test_response = model.generate_content("Hello, are you there?")
            if test_response and hasattr(test_response, 'text'):
                break
            model = None
        except Exception as e:
            continue
    
    if model is None:
        return {"error": "No compatible Gemini model found"}
    
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
        # Generate response
        response = model.generate_content(prompt)
        
        if not response or not hasattr(response, 'text'):
            return {"error": "Failed to generate story"}
        
        # Parse the JSON response
        import json
        import re
        
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not json_match:
            print(f"No JSON found in response: {response.text}")
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
                # Try to extract text from PDF
                pdf_reader = PyPDF2.PdfReader(open(filepath, "rb"))
                for page in pdf_reader.pages:
                    pdf_text += page.extract_text() or ""
                
                # If no text found, try OCR
                if not pdf_text.strip():
                    pdf_text = extract_text_hybrid(filepath)
            except Exception as e:
                print(f"Error reading PDF: {e}")
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
        prompt = ""
        
        if mode == "teach":
            prompt = f"Teach this chapter step-by-step using simple explanations, examples, analogies, and include 3 micro-questions. Chapter text: {pdf_text}"
        elif mode == "doubt":
            prompt = f"Explain this question in simple terms + real-world analogy + example: {user_message}"
        elif mode == "quiz":
            prompt = f"""
You are an adaptive quiz tutor with difficulty levels 1–10.

Difficulty: 3
Student answer: {user_message}
Generate:
- Whether answer is correct
- Explanation
- Next question
- Updated difficulty
"""
        elif mode == "explain":
            text_to_explain = selected_text if selected_text else user_message
            prompt = f"""
Explain this passage in 4 styles:
1. Simple  
2. Real-world analogy  
3. Story version  
4. Technical explanation  
Text: {text_to_explain}
"""
        elif mode == "diagram":
            prompt = f"Generate a clean ASCII diagram explaining this topic under 40 lines: {user_message}"
        else:
            prompt = user_message
        
        # Try to use Gemini model with fallback
        model = None
        model_names = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                # Test if model works
                test_response = model.generate_content("Hello, are you there?")
                if test_response and hasattr(test_response, 'text'):
                    break
                model = None
            except Exception as e:
                continue
        
        if model is None:
            return {"error": "No compatible Gemini model found"}, 500
        
        # Generate response
        response = model.generate_content(prompt)
        
        if not response or not hasattr(response, 'text'):
            return {"error": "Failed to generate response"}, 500
        
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
        """, (user_id, "assistant", response.text, datetime.now(timezone.utc).isoformat()))
        
        conn.commit()
        conn.close()
        
        return {
            "response": response.text,
            "session_id": session_id
        }
    
    except Exception as e:
        print(f"AI Tutor Error: {e}")
        return {"error": str(e)}, 500



# ---------- Run ----------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))  # Use PORT environment variable or default to 5000
    app.run(host='0.0.0.0', port=port, debug=False) 
`n`ndef get_font_path(font_filename):`n    """Helper function to get the correct font path for both local and Render environments"""`n    # Try multiple possible locations for font files`n    possible_paths = [`n        os.path.join(os.path.dirname(__file__), font_filename),  # Same directory as app.py`n        os.path.join(os.path.dirname(__file__), 'static', 'fonts', font_filename),  # In static/fonts/`n        os.path.join(os.path.dirname(__file__), '..', 'static', 'fonts', font_filename),  # Parent static/fonts/`n        os.path.join(os.getcwd(), font_filename),  # Current working directory`n    ]`n    `n    for path in possible_paths:`n        path = os.path.normpath(path)  # Normalize path separators`n        if os.path.exists(path):`n            print(f'Found font at: {path}')`n            return path`n    `n    print(f'Font file {font_filename} not found in any expected location')`n    return None`n`ndef text_to_pdf(text, output_pdf, font_path, font_size=12):`n    print('Registering font:', font_path)  # Debug`n    # Use helper function to find the correct font path`n    actual_font_path = get_font_path(font_path)`n    if actual_font_path:`n        pdfmetrics.registerFont(TTFont('CustomFont', actual_font_path))`n        font_name = 'CustomFont'`n    else:`n        print('Using default font instead of custom font')`n        font_name = 'Helvetica'  # Default font that's always available`n`n    c = canvas.Canvas(output_pdf, pagesize=A4)`n    width, height = A4`n    left_margin = 50`n    top_margin = height - 50`n    bottom_margin = 50`n    line_height = font_size + 4  # Add a little spacing`n`n    textobject = c.beginText(left_margin, top_margin)`n    textobject.setFont(font_name, font_size)`n`n    for line in text.split('\\n'):`n        if textobject.getY() < bottom_margin:`n            c.drawText(textobject)`n            c.showPage()`n            textobject = c.beginText(left_margin, top_margin)`n            textobject.setFont(font_name, font_size)`n        textobject.textLine(line)`n    c.drawText(textobject)`n    c.save()
