# Project Setup Instructions 🚀

Welcome to the **Udaan** project! Follow these steps to set up the project on your computer so that all features (including AI Summary and AI Tutor) work correctly.

## 1. Install Python Dependencies
First, make sure you have Python installed. Then, install the required libraries:

```bash
pip install -r requirements.txt
```

## 2. Set Up Environment Variables (.env)
The project needs an OpenAI API Key to generate summaries, quizzes, and chat responses.

1.  Create a file named `.env` in the `project/` folder (same folder as `app.py`).
2.  Add your API key inside it:

```ini
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **Note:** Do NOT share this file on GitHub. Each teammate should use their own key or share it securely.

## 3. Install Tesseract OCR (For Scanned PDFs)
To read text from images or scanned PDFs, you need **Tesseract OCR**.

### Windows:
1.  Download Tesseract from here: [Tesseract Installer](https://github.com/UB-Mannheim/tesseract/wiki)
2.  Install it.
3.  **Important:** During installation, note the install path (usually `C:\Program Files\Tesseract-OCR`).
4.  Add this line to your `.env` file if it's not in the standard path:
    ```ini
    TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
    ```

### Mac (Homebrew):
```bash
brew install tesseract
```

## 4. Run the App
```bash
python app.py
```
Open your browser to `http://127.0.0.1:5000`.

## Troubleshooting
- **"AI Summary not working":** Check if your `OPENAI_API_KEY` is correct in `.env`.
- **"Tesseract not found":** The app will still work, but you won't be able to upload scanned PDFs. Text-based PDFs will work fine.
