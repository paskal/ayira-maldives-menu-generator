import hashlib
import json
import os
import string
import typing
import urllib.request

import google.api_core.client_options
import google.oauth2.service_account
import googleapiclient.discovery


class CellFormat(typing.TypedDict, total=False):
    backgroundColor: typing.Dict[str, float]
    backgroundImage: typing.Dict[str, str]
    padding: typing.Dict[str, int]
    horizontalAlignment: str
    verticalAlignment: str
    textFormat: typing.Dict[str, typing.Any]


class CellValue(typing.TypedDict, total=False):
    stringValue: str
    numberValue: float


class Cell(typing.TypedDict, total=False):
    userEnteredValue: CellValue
    effectiveValue: CellValue
    formattedValue: str
    effectiveFormat: CellFormat


class MenuItem(typing.TypedDict):
    title: str
    price: str
    description: str
    image: str


MenuData = typing.Dict[str, typing.List[MenuItem]]
ImageMap = typing.Dict[typing.Tuple[int, int], str]
SheetData = typing.Dict[str, typing.Any]

# Configuration
SPREADSHEET_ID = os.environ['SPREADSHEET_ID']
SHEET_NAME = os.environ.get('SHEET_NAME', 'Sheet1')
GCP_CREDS = json.loads(os.environ['GCP_CREDS_JSON'])

# HTML Template using standard Python string.Template
HTML_TEMPLATE = string.Template('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${title}</title>
    <style>
        :root {
            --bg: #ffffff;
            --text: #333333;
            --accent: #2c5f2d;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #1a1a1a;
                --text: #ffffff;
            }
        }
        body {
            font-family: system-ui, sans-serif;
            margin: 0;
            padding: 20px;
            background: var(--bg);
            color: var(--text);
        }
        .logo {
            max-width: 200px;
            margin: 0 auto 2rem;
            display: block;
        }
        .category {
            margin-bottom: 3rem;
        }
        h1 { text-align: center; color: var(--accent); }
        h2 { border-bottom: 2px solid var(--accent); }
        .item {
            margin: 1.5rem 0;
            padding: 1rem;
            background: rgba(0,0,0,0.05);
            border-radius: 8px;
        }
        .price { color: var(--accent); font-weight: bold; }
        img { max-width: 100%; height: auto; border-radius: 4px; }
    </style>
</head>
<body>
    ${logo_img}
    <h1>${title}</h1>
    ${categories}
</body>
</html>''')

CATEGORY_TEMPLATE = string.Template('''
    <div class="category">
        <h2>${category}</h2>
        ${items}
    </div>''')

ITEM_TEMPLATE = string.Template('''
        <div class="item">
            <h3>${title} <span class="price">${price}</span></h3>
            ${description}
            ${image}
        </div>''')


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""
    for path in ['generated/images']:
        os.makedirs(path, exist_ok=True)


def get_cell_value(cell: Cell) -> str:
    """Extract the string value from a cell."""
    if 'formattedValue' in cell:
        return cell['formattedValue']
    if 'effectiveValue' in cell:
        value = cell['effectiveValue']
        if 'stringValue' in value:
            return value['stringValue']
        if 'numberValue' in value:
            return str(value['numberValue'])
    return ''


def get_services() -> typing.Tuple[googleapiclient.discovery.Resource, googleapiclient.discovery.Resource]:
    """Initialize Google Sheets and Drive services."""
    creds = google.oauth2.service_account.Credentials.from_service_account_info(
        GCP_CREDS,
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
    )
    sheets = googleapiclient.discovery.build('sheets', 'v4', credentials=creds)
    drive = googleapiclient.discovery.build('drive', 'v3', credentials=creds)
    return sheets, drive


def get_sheet_data(sheets_service: googleapiclient.discovery.Resource) -> typing.Tuple[str, SheetData]:
    """Fetch data and embedded images from Google Sheets."""
    # Get restaurant title and logo
    sheet_data = sheets_service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        ranges=[f"{SHEET_NAME}!A2:E", f"{SHEET_NAME}!G2:H2"],  # Include logo and title cells
        includeGridData=True
    ).execute()

    # Extract title from H2
    title_data = None
    for sheet in sheet_data['sheets']:
        for data in sheet['data']:
            if 'rowData' in data and data['rowData']:
                for row in data['rowData']:
                    if 'values' in row and len(row['values']) > 1:  # Looking for H2 cell
                        title_data = row['values'][-1]  # Last cell should be H2
                        break

    restaurant_title = get_cell_value(title_data) if title_data else "Restaurant Menu"

    return restaurant_title, sheet_data


def extract_image_ids(sheet_data: SheetData) -> ImageMap:
    """Extract image IDs from cell data."""
    image_map: ImageMap = {}

    if 'sheets' in sheet_data:
        for sheet in sheet_data['sheets']:
            for data in sheet['data']:
                if 'rowData' in data:
                    for row_idx, row in enumerate(data['rowData'], start=2):  # start=2 because we begin from A2
                        if 'values' in row:
                            for col_idx, cell in enumerate(row['values']):
                                if row_idx == 2 and cell and not cell.get('userEnteredValue',{}).get('stringValue') and not cell.get('userEnteredValue',{}).get('numberValue'):  # G2 is the logo cell
                                    print(json.dumps(cell))
                                if cell.get('effectiveFormat', {}).get('backgroundImage', {}).get('sourceUrl'):
                                    image_url = cell['effectiveFormat']['backgroundImage']['sourceUrl']
                                    if 'id=' in image_url:
                                        image_id = image_url.split('id=')[1].split('&')[0]
                                        image_map[(row_idx, col_idx)] = image_id

    return image_map


def download_drive_image(drive_service: googleapiclient.discovery.Resource, file_id: str, filename: str) -> bool:
    """Download image from Google Drive."""
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with urllib.request.urlopen(request.uri) as response:
            if response.status == 200:
                with open(filename, 'wb') as f:
                    f.write(response.read())
                return True
    except Exception as e:
        print(f"Failed to download image {file_id}: {str(e)}")
        return False


def process_menu_items(values: typing.List[typing.Dict[str, typing.Any]], image_map: ImageMap,
                       drive_service: googleapiclient.discovery.Resource) -> MenuData:
    """Process menu items and handle embedded images."""
    menu: MenuData = {}

    for i, row in enumerate(values, start=2):  # start=2 because we begin from A2
        if 'values' not in row or len(row['values']) < 3:
            continue

        cells = row['values']
        title = get_cell_value(cells[0])
        price = get_cell_value(cells[1])
        category = get_cell_value(cells[2])
        description = get_cell_value(cells[3]) if len(cells) > 3 else ""

        # Check for image in column E (index 4)
        image_id = image_map.get((i, 4))
        image_path = ""

        if image_id:
            filename = f"generated/images/{hashlib.md5(title.encode()).hexdigest()[:8]}.jpg"
            if download_drive_image(drive_service, image_id, filename):
                image_path = filename

        if category not in menu:
            menu[category] = []

        menu[category].append({
            'title': title,
            'price': price,
            'description': description,
            'image': image_path
        })

    return menu


def get_logo_path(image_map: ImageMap, drive_service: googleapiclient.discovery.Resource) -> typing.Optional[str]:
    """Get logo path if it exists in G2."""
    logo_id = image_map.get((2, 6))  # G2 is at index 6
    if logo_id:
        logo_path = "generated/images/logo.jpg"
        if download_drive_image(drive_service, logo_id, logo_path):
            return logo_path
    return None


def generate_html(menu_data: MenuData, restaurant_title: str, logo_path: typing.Optional[str] = None) -> str:
    """Generate HTML using templates."""
    # Process categories
    categories_html: typing.List[str] = []
    for category, items in menu_data.items():
        # Process items in category
        items_html: typing.List[str] = []
        for item in items:
            # Prepare optional elements
            description_html = f"<p>{item['description']}</p>" if item['description'] else ""
            image_html = f'<img src="{item["image"]}" alt="{item["title"]}">' if item['image'] else ""

            # Generate item HTML
            items_html.append(ITEM_TEMPLATE.substitute(
                title=item['title'],
                price=item['price'],
                description=description_html,
                image=image_html
            ))

        # Generate category HTML
        categories_html.append(CATEGORY_TEMPLATE.substitute(
            category=category,
            items=''.join(items_html)
        ))

    # Generate logo HTML
    logo_html = f'<img src="{logo_path}" alt="Logo" class="logo">' if logo_path else ''

    # Generate final HTML
    return HTML_TEMPLATE.substitute(
        title=restaurant_title,
        logo_img=logo_html,
        categories=''.join(categories_html)
    )


def main() -> None:
    """Main function to generate the menu."""
    ensure_directories()

    # Initialize services
    sheets_service, drive_service = get_services()

    # Get sheet data with both menu items and logo/title area
    restaurant_title, sheet_data = get_sheet_data(sheets_service)

    # Extract image IDs from sheet data (including logo)
    image_map = extract_image_ids(sheet_data)

    # Get logo path
    logo_path = get_logo_path(image_map, drive_service)

    # Get menu values from the first range (A2:E)
    values = sheet_data['sheets'][0]['data'][0].get('rowData', [])

    # Process menu items
    menu = process_menu_items(values, image_map, drive_service)

    # Generate and save HTML
    html = generate_html(menu, restaurant_title, logo_path)
    with open('generated/index.html', 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == "__main__":
    main()
