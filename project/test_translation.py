try:
    from deep_translator import GoogleTranslator
    print("deep_translator is installed.")
    
    text = "Hello, this is a test sentence to translate."
    translated = GoogleTranslator(source='auto', target='hi').translate(text)
    print(f"Original: {text}")
    print(f"Translated: {translated}")
    
except ImportError:
    print("Error: deep_translator module not found. Please install it.")
except Exception as e:
    print(f"Error during translation: {e}")
