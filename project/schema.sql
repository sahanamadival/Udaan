-- Udaan Database Schema
-- Production-ready schema supporting Grade 1 to Grade 5 dynamically

-- Students table
CREATE TABLE IF NOT EXISTS students (
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
    google_id TEXT
);



-- File uploads table
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    filename TEXT,
    uploaded_at TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- Flashcards table
CREATE TABLE IF NOT EXISTS flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    filename TEXT,
    num_flashcards INTEGER,
    created_at TEXT,
    data TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- Quiz attempts table
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    quiz_id TEXT,
    score INTEGER,
    total INTEGER,
    attempted_at TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- AI Tutor sessions table
CREATE TABLE IF NOT EXISTS ai_tutor_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    role TEXT,          -- 'user' or 'assistant'
    message TEXT,
    difficulty INTEGER DEFAULT 3,
    timestamp TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- Puzzle data table for drag-and-drop game
CREATE TABLE IF NOT EXISTS puzzle_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    filename TEXT,
    puzzle_json TEXT,
    created_at TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- AI summaries table
CREATE TABLE IF NOT EXISTS ai_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    filename TEXT,
    summary TEXT,
    created_at TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- Writing progress table
CREATE TABLE IF NOT EXISTS writing_progress (
    id INTEGER PRIMARY KEY,
    student_id TEXT,
    text TEXT,
    word_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Writing streak table
CREATE TABLE IF NOT EXISTS writing_streak (
    student_id TEXT PRIMARY KEY,
    last_date DATE,
    streak_count INTEGER DEFAULT 0
);

-- Enhanced student progress table supporting all grades (1-5)
CREATE TABLE IF NOT EXISTS student_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    grade INTEGER,  -- 1, 2, 3, 4, or 5
    books_analyzed INTEGER DEFAULT 0,
    math_solved INTEGER DEFAULT 0,
    science_done INTEGER DEFAULT 0,
    creative_done INTEGER DEFAULT 0,
    reading_done INTEGER DEFAULT 0,
    writing_done INTEGER DEFAULT 0,
    last_activity_date DATE,
    streak_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- Grade-specific activity tracking table
CREATE TABLE IF NOT EXISTS grade_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    grade INTEGER,  -- 1, 2, 3, 4, or 5
    activity_type TEXT,  -- 'reading', 'writing', 'math', 'science', 'creative'
    activity_count INTEGER DEFAULT 0,
    last_completed DATE,
    FOREIGN KEY(student_id) REFERENCES students(id)
);

-- Vocabulary notebook table
CREATE TABLE IF NOT EXISTS vocab_notebook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    word TEXT NOT NULL,
    definition TEXT,
    example TEXT,
    subject TEXT,
    created_at TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
);
-- Teachers table
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    password_hash TEXT,
    created_at TEXT