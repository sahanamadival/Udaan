from PIL import Image, ImageDraw, ImageFont
import os

alphabet_dir = "e:/Udaan6.0/Udaan/project/static/alphabet_images"

# Create more alphabet images
additional_words = ["fish", "giraffe", "house", "ice_cream", "jump"]
additional_letters = ["F", "G", "H", "I", "J"]

colors = {
    "fish": ("#87ceeb", "#4682b4"),
    "giraffe": ("#deb887", "#daa520"),
    "house": ("#cd853f", "#8b4513"),
    "ice_cream": ("#ffb6c1", "#ff69b4"),
    "jump": ("#9370db", "#8a2be2")
}

width, height = 200, 200

for word, letter in zip(additional_words, additional_letters):
    img = Image.new('RGB', (width, height), colors[word][0])
    draw = ImageDraw.Draw(img)
    
    try:
        font_large = ImageFont.truetype("arial.ttf", 24)
        font_medium = ImageFont.truetype("arial.ttf", 16)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
    
    # Draw circle
    draw.ellipse([50, 30, 150, 130], fill=colors[word][1])
    
    # Draw letter
    letter_bbox = draw.textbbox((0, 0), letter, font=font_large)
    letter_width = letter_bbox[2] - letter_bbox[0]
    letter_height = letter_bbox[3] - letter_bbox[1]
    draw.text((100 - letter_width//2, 80 - letter_height//2), letter, fill="white", font=font_large)
    
    # Draw word
    display_word = word.replace("_", " ").title()
    word_bbox = draw.textbbox((0, 0), display_word, font=font_medium)
    word_width = word_bbox[2] - word_bbox[0]
    draw.text((100 - word_width//2, 150), display_word, fill="white", font=font_medium)
    
    # Save image
    img.save(f"{alphabet_dir}/{word}.png")
    print(f"Created {word}.png")

print("Additional alphabet images created!")