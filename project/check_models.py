import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Get the API key from .env
api_key = os.getenv("GEMINI_API_KEY")

# Configure Gemini
if api_key and api_key.strip():
    genai.configure(api_key=api_key)
    print("INFO: Gemini API key loaded successfully")
else:
    print("WARNING: GEMINI_API_KEY not found in .env file.")
    exit(1)

# List available models
try:
    print("Available models:")
    for model in genai.list_models():
        if 'generateContent' in model.supported_generation_methods:
            print(f"- {model.name}")
except Exception as e:
    print(f"Error listing models: {e}")