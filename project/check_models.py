import os
from openai import OpenAI
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Get the API key from .env
api_key = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
if api_key and api_key.strip():
    client = OpenAI(api_key=api_key)
    print("INFO: OpenAI API key loaded successfully")
else:
    print("WARNING: OPENAI_API_KEY not found in .env file.")
    exit(1)

# List available models
try:
    print("Available models:")
    models = client.models.list()
    for model in models.data:
        print(f"- {model.id}")
except Exception as e:
    print(f"Error listing models: {e}")