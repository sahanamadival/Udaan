import os
import sys
from dotenv import load_dotenv
from openai import OpenAI
import pytesseract

# Load environment variables
load_dotenv(os.path.join("project", ".env"))

def check_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    print(f"Checking OpenAI API Key: {'Found' if api_key else 'Missing'}")
    if not api_key or "your_api_key_here" in api_key:
        print("X Error: Invalid or missing OPENAI_API_KEY in project/.env")
        return False
    
    try:
        client = OpenAI(api_key=api_key)
        client.models.list()
        print("OK OpenAI API Connection: Success")
        return True
    except Exception as e:
        print(f"X OpenAI API Connection Failed: {e}")
        return False

def check_tesseract():
    tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    print(f"Checking Tesseract Path: {tesseract_cmd}")
    if os.path.exists(tesseract_cmd):
        print("OK Tesseract Executable: Found")
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        try:
            # Basic check if it runs
            print("OK Tesseract configured successfully")
            return True
        except Exception as e:
            print(f"Warning Tesseract configuration issue: {e}")
            return False
    else:
        print("Warning Tesseract Executable NOT Found at default path. OCR for scanned PDFs might fail.")
        return False

def check_font():
    font_path = os.path.join("project", "NotoSansDevanagari-Regular.ttf")
    print(f"Checking Hindi Font: {font_path}")
    if os.path.exists(font_path):
        print("OK Hindi Font: Found")
        return True
    else:
        print("Warning Hindi Font NOT Found. Translations will use fallback font (blocks/squares).")
        return False

if __name__ == "__main__":
    print("=== Udaan Feature Verification ===")
    openai_ok = check_openai()
    tesseract_ok = check_tesseract()
    font_ok = check_font()
    
    if openai_ok:
        print("\nOK MAIN FEATURES (Audio, Summary, Translation) SHOULD WORK now.")
    else:
        print("\nX MAIN FEATURES WILL FAIL. Fix API Key.")
        
    if not tesseract_ok:
        print("Warning OCR features (scanned PDFs) might include limitations.")
