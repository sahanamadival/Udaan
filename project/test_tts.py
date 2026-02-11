
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("ERROR: OPENAI_API_KEY not found in environment.")
    exit(1)

print(f"API Key found: {api_key[:15]}...")

try:
    client = OpenAI(api_key=api_key)
    print("Client initialized.")
    
    print("Attempting TTS generation...")
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input="This is a test of the audio generation system."
    )
    
    output_file = "test_audio.mp3"
    response.stream_to_file(output_file)
    print(f"Success! Audio saved to {output_file}")
    
except Exception as e:
    print(f"ERROR: {e}")
