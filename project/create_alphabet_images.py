from PIL import Image, ImageDraw, ImageFont
import os

# Create alphabet images directory if it doesn't exist
alphabet_dir = "e:/Udaan6.0/Udaan/project/static/alphabet_images"
os.makedirs(alphabet_dir, exist_ok=True)

# Image specifications
width, height = 200, 200
background_colors = {
    "apple": "#ff6b6b",
    "ball": "#4ecdc4", 
    "cat": "#a8e6cf",
    "dog": "#ffd93d",
    "elephant": "#ff9aa2"
}

letter_colors = {
    "apple": "#ff5252",
    "ball": "#26a69a",
    "cat": "#4caf50",
    "dog": "#ffc107",
    "elephant": "#e91e63"
}

# Create images for each word
words = ["apple", "ball", "cat", "dog", "elephant"]
letters = ["A", "B", "C", "D", "E"]

for word, letter in zip(words, letters):
    # Create new image
    img = Image.new('RGB', (width, height), background_colors[word])
    draw = ImageDraw.Draw(img)
    
    # Try to use a font (fallback to default if not available)
    try:
        font_large = ImageFont.truetype("arial.ttf", 24)
        font_medium = ImageFont.truetype("arial.ttf", 16)
        font_small = ImageFont.truetype("arial.ttf", 12)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Draw letter circle
    circle_y = 80 if word != "elephant" else 85
    draw.ellipse([100-50, circle_y-50, 100+50, circle_y+50], fill=letter_colors[word])
    
    # Draw letter
    letter_bbox = draw.textbbox((0, 0), letter, font=font_large)
    letter_width = letter_bbox[2] - letter_bbox[0]
    letter_height = letter_bbox[3] - letter_bbox[1]
    draw.text((100 - letter_width//2, circle_y - letter_height//2), letter, fill="white", font=font_large)
    
    # Draw word
    word_bbox = draw.textbbox((0, 0), word.capitalize(), font=font_medium)
    word_width = word_bbox[2] - word_bbox[0]
    word_y = 110 if word != "elephant" else 125
    draw.text((100 - word_width//2, word_y), word.capitalize(), fill="white", font=font_medium)
    
    # Add specific details for some animals
    if word == "apple":
        # Draw apple stem
        draw.line([100, 30, 100, 50], fill="#8b4513", width=3)
    elif word == "cat":
        # Draw cat eyes and mouth
        draw.ellipse([85-3, 75-3, 85+3, 75+3], fill="white")
        draw.ellipse([115-3, 75-3, 115+3, 75+3], fill="white")
        draw.arc([80, 100, 120, 130], 0, 180, fill="white", width=2)
    elif word == "dog":
        # Draw dog eyes and mouth
        draw.ellipse([85-4, 75-4, 85+4, 75+4], fill="white")
        draw.ellipse([115-4, 75-4, 115+4, 75+4], fill="white")
        draw.arc([75, 105, 125, 135], 0, 180, fill="white", width=3)
    elif word == "elephant":
        # Draw elephant eyes and trunk
        draw.ellipse([80-5, 70-5, 80+5, 70+5], fill="white")
        draw.ellipse([120-5, 70-5, 120+5, 70+5], fill="white")
        draw.arc([85, 100, 115, 130], 0, 180, fill="white", width=2)
    
    # Save as PNG
    img.save(f"{alphabet_dir}/{word}.png")
    print(f"Created {word}.png")

# Create default image
default_img = Image.new('RGB', (width, height), "#e0e0e0")
draw = ImageDraw.Draw(default_img)

# Draw question mark circle
draw.ellipse([60, 40, 140, 120], fill="#bdbdbd")
try:
    font_large = ImageFont.truetype("arial.ttf", 30)
    font_medium = ImageFont.truetype("arial.ttf", 14)
    font_small = ImageFont.truetype("arial.ttf", 12)
except:
    font_large = ImageFont.load_default()
    font_medium = ImageFont.load_default()
    font_small = ImageFont.load_default()

draw.text((100, 70), "?", fill="#757575", font=font_large, anchor="mm")
draw.text((100, 135), "Image Not Found", fill="#757575", font=font_medium, anchor="mm")

# Draw default button
draw.rectangle([50, 150, 150, 180], fill="#9e9e9e", outline=None)
draw.text((100, 165), "Default", fill="white", font=font_small, anchor="mm")

default_img.save(f"{alphabet_dir}/default.png")
print("Created default.png")

print("All alphabet images created successfully!")