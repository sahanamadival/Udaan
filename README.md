# 🕊️ Udaan – Accessible AI-Powered Learning Platform

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Backend-lightgrey?logo=flask&logoColor=black)
![SQLite](https://img.shields.io/badge/SQLite-DB-yellow?logo=sqlite&logoColor=white)
![AI](https://img.shields.io/badge/AI-OpenAI-red?logo=openai&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 🌟 About Udaan
**Udaan** is a **Flask-based web app** designed to empower students with diverse learning needs.  
It leverages **AI** to provide grade-wise learning, interactive science modules, AI-powered writing labs, summaries, translations, dyslexia-friendly reading, audio narration, flashcards, quizzes, and dashboards for both students and teachers.

---

## 🚀 Features

### 👩‍🎓 Student Dashboard
- 📚 Upload textbooks (PDF/DOCX/TXT → text extraction + OCR fallback)
- 🎧 Audio narration (TTS)
- 🤖 AI-generated summaries (GPT)
- 🌐 Translations: Hindi PDFs with **Noto fonts**
- 📝 Dyslexia-friendly reader: adjustable spacing, overlays, in-page TTS
- 🃏 Flashcards & MCQ quizzes powered by GPT
- 📖 Library of uploaded books
- 🎓 **Grade-wise learning**: Separate dashboards for Grade 1 and Grade 5
- 📊 **Dynamic progress tracking**: Real SQLite-based stats instead of dummy data
- 📈 **Subject modules**: Reading, Writing, Math, Science, Creative per grade

### 👨‍🏫 Teacher Dashboard
- 📚 Upload & view books
- 📊 Dynamic class stats
- 🏆 Recent students (activity-ranked)
- 📈 Student progress view: uploads, flashcards, quizzes, average scores
- 👀 **Real activity visibility**: Teacher can see actual student engagement

### 💾 Storage
- SQLite database for users, uploads, flashcards, quiz attempts, and grade-specific progress
- Automatic schema migration for safe upgrades

---

## 🛠️ Tech Stack
- **Backend:** Python, Flask, SQLite  
- **AI:** OpenAI API (GPT, TTS)  
- **PDF/Image Handling:** PyPDF2, pdf2image, PyMuPDF (fitz), Pillow  
- **OCR:** Tesseract (pytesseract)  
- **PDF Generation:** reportlab  
- **Frontend:** Jinja templates, vanilla JS, modern responsive CSS
- **Speech:** Web Speech API for browser-based TTS/STT

---

## 📁 Repository Structure
```
app/                    # Global styles (Next.js-like structure)
project/
  app.py                # Flask app entrypoint
  requirements.txt      # Python dependencies
  database.db           # SQLite DB (auto-created)
  static/
    books/              # Teacher-uploaded books
    translations/       # Generated translated PDFs
    narrations/         # Generated audio files
    audio/              # Temporary AI-generated audio (git-ignored)
    styles.css          # Shared CSS
    bot.jpg             # Friendly robot image 🤖
  templates/            # Jinja2 templates (auth, dashboards, readers, etc.)
  uploads/              # Student uploads
  Noto_Sans_Devanagari/ # Fonts for Hindi PDF output
```

---

## ⚙️ Setup

1️⃣ **Create & activate a virtual environment**
```bash
cd project
python -m venv venv
venv\Scripts\activate
```

2️⃣ **Install dependencies**
```bash
pip install -r requirements.txt
```

3️⃣ **Configure environment variables**
Create a `.env` file in `project/`:
```env
OPENAI_API_KEY=your_openai_api_key_here
```

4️⃣ **Verify asset paths**
- Ensure Tesseract path in `app.py` matches your installation
- Optional: Confirm Poppler is installed and on PATH

5️⃣ **Run the app**
```bash
python app.py
```
🌐 App runs at http://127.0.0.1:5000/

### Database Initialization
The SQLite database is automatically created on first run using `schema.sql`.
No database file is stored in the repository.
The schema supports Grade 1 to Grade 5 dynamically.

---

## 🎯 Usage Overview

### 🧑 Student
- Sign up/login → Grade-specific Dashboard
- Upload textbooks → OCR fallback for scans/images
- Use features: Audio, Summary, Translation, Dyslexic Reader, Flashcards, Quizzes
- Access teacher-uploaded PDFs via library
- **Grade 4**: Interactive science body exploration + AI writing lab
- **Progress tracking**: View real stats and daily streaks

### 👩‍🏫 Teacher
- Sign up/login → Dashboard
- Upload/view books
- Monitor student progress: uploads, flashcards, quizzes, average scores
- **Real activity data**: See actual student engagement per grade

---

## 📌 Important Paths & Fonts
- 🈵 **Hindi PDFs:** `Noto Sans Devanagari` (`project/Noto_Sans_Devanagari/`)
  - Ensure `NotoSansDevanagari-Regular.ttf` exists
- 📂 **Translations:** `project/static/translations/`
- 🔊 **Narrations:** `project/static/narrations/`
- 🎵 **Temp Audio:** `project/static/audio/` (auto-created, git-ignored)

---

## 🔒 Security Notes
- Set a strong `app.secret_key` in production
- Never commit `.env` with real keys
- Validate & sanitize uploads; limit file size and content type
- **Google OAuth**: Secure OAuth 2.0 authentication for students and teachers
- **DB auto-creation**: SQLite database safely created on first run
- **Safe file handling**: Temporary audio files automatically cleaned
- **Production ready**: Schema migrations handle version upgrades safely

---

## ⚠️ Troubleshooting
- **Tesseract not found:** Update path in `app.py`, confirm `tesseract.exe` works in terminal
- **pdf2image errors on Windows:** Install Poppler & add `bin` to PATH
- **OpenAI errors:** Verify `OPENAI_API_KEY` & network/proxy
- **Missing fonts:** Ensure `NotoSansDevanagari-Regular.ttf` exists
- **Schema conflicts:** Automatic migration handles database upgrades

---

## 🌟 Extending
- Replace placeholder charts with JS chart library (Chart.js)
- Add per-student pages & deeper analytics
- Persist dyslexic reader preferences via localStorage
- Add server-side MP3 generation (currently pyttsx3 is client-side)
- **Grade expansion**: Easy to add Grade 1, 3, 5 with similar patterns
- **Feature modules**: Plug-and-play architecture for new subjects

---

## 📝 Notes
- Default `app.secret_key` is for development only; set a secure key in production
- File uploads: Consider limiting size and validating content type to avoid misuse
- Fonts & translations: Ensure Noto Sans Devanagari is present to avoid broken Hindi PDFs
- **Database**: Auto-migration system handles schema changes safely
- **Audio files**: Generated in `static/audio/` and automatically git-ignored
- **UI consistency**: Clean navigation without emojis, responsive design across grades

---

## 📜 License
- **Fonts:** Licensed per included OFL
- **App code:** MIT (customizable)

---


