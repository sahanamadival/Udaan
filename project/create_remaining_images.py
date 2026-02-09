from PIL import Image, ImageDraw, ImageFont
import os

alphabet_dir = "e:/Udaan6.0/Udaan/project/static/alphabet_images"

# Create remaining alphabet images (K-Z)
remaining_words = ["kite", "lion", "monkey", "nest", "orange", "pig", "queen", "rabbit", "sun", "tiger", "umbrella", "van", "window", "xylophone", "yellow", "zebra"]
remaining_letters = ["K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]

# Color schemes for each letter
colors = {
    "kite": ("#ff9f80", "#ff6b35"),
    "lion": ("#ffb347", "#ff8c00"),
    "monkey": ("#d2b48c", "#8b4513"),
    "nest": ("#8fbc8f", "#228b22"),
    "orange": ("#ffa500", "#ff8c00"),
    "pig": ("#ffb6c1", "#ffc0cb"),
    "queen": ("#da70d6", "#ba55d3"),
    "rabbit": ("#fffacd", "#f5f5dc"),
    "sun": ("#ffd700", "#ffdf00"),
    "tiger": ("#ffa07a", "#ff7f50"),
    "umbrella": ("#87cefa", "#00bfff"),
    "van": ("#778899", "#708090"),
    "window": ("#87ceeb", "#4682b4"),
    "xylophone": ("#dda0dd", "#c71585"),
    "yellow": ("#ffff00", "#ffd700"),
    "zebra": ("#f0f8ff", "#1e90ff")
}

width, height = 200, 200

for word, letter in zip(remaining_words, remaining_letters):
    img = Image.new('RGB', (width, height), colors[word][0])
    draw = ImageDraw.Draw(img)
    
    try:
        font_large = ImageFont.truetype("arial.ttf", 24)
        font_medium = ImageFont.truetype("arial.ttf", 16)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
    
    # Draw main shape
    if word == "kite":
        # Draw kite shape
        draw.polygon([(100, 30), (130, 80), (100, 130), (70, 80)], fill=colors[word][1])
        draw.line([(100, 30), (100, 130)], fill="white", width=2)
        draw.line([(70, 80), (130, 80)], fill="white", width=2)
    elif word == "lion":
        # Draw lion face
        draw.ellipse([70, 50, 130, 110], fill=colors[word][1])
        draw.ellipse([80, 60, 90, 70], fill="white")  # eye
        draw.ellipse([110, 60, 120, 70], fill="white")  # eye
        draw.arc([85, 75, 115, 95], 0, 180, fill="white", width=2)  # smile
    elif word == "monkey":
        # Draw monkey face
        draw.ellipse([75, 50, 125, 100], fill=colors[word][1])
        draw.ellipse([85, 60, 95, 70], fill="white")  # eye
        draw.ellipse([105, 60, 115, 70], fill="white")  # eye
        draw.ellipse([90, 75, 110, 85], fill="#a0522d")  # nose
    elif word == "nest":
        # Draw nest with eggs
        draw.ellipse([60, 80, 140, 140], fill=colors[word][1])
        draw.ellipse([80, 90, 95, 105], fill="#f0e68c")  # egg
        draw.ellipse([105, 90, 120, 105], fill="#f0e68c")  # egg
    elif word == "orange":
        # Draw orange
        draw.ellipse([70, 60, 130, 120], fill=colors[word][1])
        draw.line([100, 40, 100, 60], fill="#228b22", width=3)  # stem
    else:
        # Default circle for other words
        draw.ellipse([50, 30, 150, 130], fill=colors[word][1])
    
    # Draw letter
    letter_bbox = draw.textbbox((0, 0), letter, font=font_large)
    letter_width = letter_bbox[2] - letter_bbox[0]
    letter_height = letter_bbox[3] - letter_bbox[1]
    draw.text((100 - letter_width//2, 80 - letter_height//2), letter, fill="white", font=font_large)
    
    # Draw word
    display_word = word.title()
    word_bbox = draw.textbbox((0, 0), display_word, font=font_medium)
    word_width = word_bbox[2] - word_bbox[0]
    draw.text((100 - word_width//2, 150), display_word, fill="white", font=font_medium)
    
    # Save image
    img.save(f"{alphabet_dir}/{word}.png")
    print(f"Created {word}.png")

print("All remaining alphabet images created!")