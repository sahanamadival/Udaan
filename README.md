# 🕊️ Udaan – Accessible AI-Powered Learning Platform

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Backend-lightgrey?logo=flask&logoColor=black)
![SQLite](https://img.shields.io/badge/SQLite-DB-yellow?logo=sqlite&logoColor=white)
![AI](https://img.shields.io/badge/AI-OpenAI-red?logo=openai&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 🌟 About Udaan
**Udaan** is a comprehensive, **Flask-based educational platform** designed to empower students from **Grade 1 to Grade 5**, with a special focus on accessibility and diverse learning needs. 

It leverages **Generative AI** to provide personalized tutoring, grade-specific gamified learning, dyslexia-friendly reading tools, and deeper teacher insights.

---

## 🚀 Key Features

### 👩‍🎓 For Students
#### **1. Personalized Learning Dashboards (Grades 1-5)**
Tailored interfaces and content for each grade level:
- **Grade 1:** Alphabets, Shapes, Basic Math, Fun Quizzes.
- **Grade 2:** Reading, Sentences, Nature, Numbers, Science.
- **Grade 3:** Grammar (Nouns/Verbs), Logic Puzzles, Math, Environmental Science.
- **Grade 4:** Advanced Reading, Writing, Phonics, "Word Wizzle" Games, Interactive Science.
- **Grade 5:** Vocabulary, History, Multiplication, Paragraph Writing.

#### **2. AI & Accessibility Tools**
- **🤖 AI Tutor:** Context-aware chat assistant that helps explain topics from uploaded textbooks.
- **📝 Dyslexia-Friendly Reader:** Customizable text display (OpenDyslexic font, spacing, color overlays) + specific "Read Aloud" functionality.
- **🎧 Natural Text-to-Speech:** High-quality narration using Edge TTS.
- **🌐 Language Support:** Instant translation of PDFs and text (English -> Hindi) with proper font rendering.
- **📚 Smart Library:** Upload textbooks (PDF/DOCX/TXT) -> Auto-extract text -> Generate Summaries & Flashcards.

#### **3. Gamified Learning**
- **Mental Math & Logic:** Interactive puzzles and speed math.
- **Language Games:** Word building, sentence arrangement, and spelling challenges.
- **Immersive Stories:** Interactive storytelling modules.

---

### 👨‍🏫 For Teachers
- **📊 Class Analytics:** Monitor student engagement, quizzes taken, and books read.
- **📂 Resource Management:** Upload books and study materials for specific grades.
- **📈 Progress Tracking:** View detailed stats for individual students or the whole class.
- **🏆 Leaderboards:** Encourage participation through activity tracking.

---

## 🛠️ Tech Stack
- **Backend:** Python, Flask
- **Database:** SQLite (Auto-migrating schema)
- **AI services:** 
  - OpenAI API (GPT-4o/3.5 for Logic, Summaries, Quiz Generation)
  - Edge TTS (High-quality speech synthesis)
- **Frontend:** HTML5, CSS3, JavaScript, Jinja2 Templates
- **Data Processing:** 
  - `PyPDF2`, `pdf2image`, `pytesseract` (OCR) for file parsing.
  - `reportlab` for generating accessibility-optimized PDFs.
  - `deep_translator` for localization.

---

## 📂 Project Structure
```
Udaan/
├── app/                    # Global styles/assets
├── project/
│   ├── app.py              # Main Flask Application
│   ├── database.db         # SQLite Database (Auto-created)
│   ├── requirements.txt    # Dependencies
│   ├── templates/          # HTML Templates (organized by feature/grade)
│   │   ├── grade_1_*.html  # Grade 1 Modules
│   │   ├── ...
│   │   ├── grade_5_*.html  # Grade 5 Modules
│   │   ├── ai_tutor.html   # AI Chat Interface
│   │   └── teacher_*.html  # Teacher Dashboards
│   └── static/
│       ├── books/          # Uploaded resources
│       ├── audio/          # Generated TTS files
│       ├── translations/   # Translated documents
│       └── styles.css      # Core Stylesheet
└── README.md
```

---

## ⚙️ Setup & Installation

### 1. Clone & Prepare
```bash
git clone https://github.com/sahanamadival/Udaan.git
cd Udaan/project
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```
*Note: You may need to install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and [Poppler](https://github.com/oschwartz10612/poppler-windows/releases/) separately and add them to your system PATH if you plan to use the OCR features on Windows.*

### 4. Configuration
Create a `.env` file in the `project/` directory:
```env
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key_here
GOOGLE_CLIENT_ID=your_google_client_id (Optional for OAuth)
GOOGLE_CLIENT_SECRET=your_google_client_secret (Optional)
```

### 5. Run the Application
```bash
python app.py
```
Visit **http://127.0.0.1:5000** in your browser.

---

## 🔒 Security & Privacy
- **Authentication:** Secure session-based auth with optional Google OAuth.
- **Data Safety:** Passwords are hashed. Uploaded files are processed locally or via secure APIs.
- **Privacy:** Temporary audio files are cleaned up automatically.

---

## 🤝 Contributing
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 License
Values accessibility and education. Distributed under the MIT License.
