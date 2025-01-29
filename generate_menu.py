import hashlib
import json
import os
from pathlib import Path

import qrcode
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configuration
SPREADSHEET_ID = os.environ['SPREADSHEET_ID']
SHEET_NAME = os.environ.get('SHEET_NAME', 'Sheet1')
RESTAURANT_TITLE = os.environ.get('RESTAURANT_TITLE', 'Ayira Maldives Menu')
GCP_CREDS = json.loads(os.environ['GCP_CREDS_JSON'])
BASE_URL = f"https://{os.environ.get('GITHUB_REPOSITORY_OWNER', 'paskal')}.github.io/{os.environ.get('GITHUB_REPOSITORY', 'paskal/ayira-maldives-menu-generator').split('/')[1]}"

# Setup directories
Path("generated/images").mkdir(parents=True, exist_ok=True)

# Authenticate with Google
creds = service_account.Credentials.from_service_account_info(GCP_CREDS, scopes=[
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
])
sheets_service = build('sheets', 'v4', credentials=creds)
drive_service = build('drive', 'v3', credentials=creds)


def download_image(url, filename):
    response = requests.get(url, headers={"Authorization": f"Bearer {creds.token}"})
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)


def get_drawings():
    # result = sheets_service.spreadsheets().get(
    #     spreadsheetId=SPREADSHEET_ID,
    #     includeGridData=False,
    #     fields="sheets.properties,sheets.developerMetadata"
    # ).execute()

    # commented out as it fails with:
    # Traceback (most recent call last):
    #   File "/Users/dmitry/Documents/code/tmp/ayira-maldives-menu-generator/generate_menu.py", line 200, in <module>
    #     main()
    #   File "/Users/dmitry/Documents/code/tmp/ayira-maldives-menu-generator/generate_menu.py", line 144, in main
    #     image_map = process_images()
    #   File "/Users/dmitry/Documents/code/tmp/ayira-maldives-menu-generator/generate_menu.py", line 52, in process_images
    #     drawings = get_drawings()
    #   File "/Users/dmitry/Documents/code/tmp/ayira-maldives-menu-generator/generate_menu.py", line 42, in get_drawings
    #     drawings = sheets_service.spreadsheets().drawings().list(
    # AttributeError: 'Resource' object has no attribute 'drawings'
    # drawings = sheets_service.spreadsheets().drawings().list(
    #     spreadsheetId=SPREADSHEET_ID,
    #     sheetId=result['sheets'][0]['properties']['sheetId']
    # ).execute().get('drawings', [])

    drawings = {}

    return drawings


def process_images():
    drawings = get_drawings()
    image_map = {}

    for drawing in drawings:
        pos = drawing['position']
        col = pos['overlayPosition']['anchorCell']['columnIndex']
        row = pos['overlayPosition']['anchorCell']['rowIndex']

        if 'image' in drawing['shape']['shapeType']:
            content_uri = drawing['shape']['imageProperties']['contentUri']
            image_map[(row, col)] = content_uri

    return image_map


def generate_html(menu_data, logo_path):
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{RESTAURANT_TITLE}</title>
    <style>
        :root {{
            --bg: #ffffff;
            --text: #333333;
            --accent: #2c5f2d;
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #1a1a1a;
                --text: #ffffff;
            }}
        }}
        body {{
            font-family: system-ui, sans-serif;
            margin: 0;
            padding: 20px;
            background: var(--bg);
            color: var(--text);
        }}
        .logo {{
            max-width: 200px;
            margin: 0 auto 2rem;
            display: block;
        }}
        .category {{
            margin-bottom: 3rem;
        }}
        h1 {{ text-align: center; color: var(--accent); }}
        h2 {{ border-bottom: 2px solid var(--accent); }}
        .item {{
            margin: 1.5rem 0;
            padding: 1rem;
            background: rgba(0,0,0,0.05);
            border-radius: 8px;
        }}
        .price {{ color: var(--accent); font-weight: bold; }}
        img {{ max-width: 100%; height: auto; border-radius: 4px; }}
    </style>
</head>
<body>
    <img src="{logo_path}" alt="Logo" class="logo">
    <h1>{RESTAURANT_TITLE}</h1>"""

    for category, items in menu_data.items():
        html += f"""
    <div class="category">
        <h2>{category}</h2>"""
        for item in items:
            html += f"""
        <div class="item">
            <h3>{item['title']} <span class="price">${item['price']}</span></h3>
            {f"<p>{item['description']}</p>" if item['description'] else ""}
            {f'<img src="{item["image"]}">' if item['image'] else ""}
        </div>"""
        html += "\n    </div>"

    html += """
</body>
</html>"""
    return html


def main():
    # Get menu data
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:E"
    ).execute()
    values = result.get('values', [])

    # Process images
    image_map = process_images()

    # Download logo
    logo_url = None
    for (row, col), url in image_map.items():
        if row == 1 and col == 8:  # I2 (0-based)
            logo_url = url
            break

    logo_path = "generated/images/logo.png"
    if logo_url:
        download_image(logo_url, logo_path)

    # Process menu items
    menu = {}
    for i, row in enumerate(values):
        if len(row) < 3: continue

        title = row[0]
        price = row[1]
        category = row[2]
        description = row[3] if len(row) > 3 else ""
        image_url = image_map.get((i + 1, 4), None)  # E column (0-based index 4)

        image_path = ""
        if image_url:
            ext = image_url.split('.')[-1].split('?')[0]
            filename = f"{hashlib.md5(title.encode()).hexdigest()[:8]}.{ext}"
            image_path = f"images/{filename}"
            download_image(image_url, image_path)

        item = {
            'title': title,
            'price': price,
            'description': description,
            'image': image_path if image_path else ""
        }

        if category not in menu:
            menu[category] = []
        menu[category].append(item)

    # Generate HTML
    html = generate_html(menu, logo_path if logo_url else "")
    with open('generated/index.html', 'w') as f:
        f.write(html)

    # Generate QR code
    qr = qrcode.make(BASE_URL)
    qr.save("generated/menu-qr.png")

    # Create artifacts
    with open("generated/menu-url.txt", "w") as f:
        f.write(BASE_URL)


if __name__ == "__main__":
    main()
