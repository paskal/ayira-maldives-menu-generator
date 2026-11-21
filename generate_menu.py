import base64
import html
import io
import json
import logging
import os
import posixpath
import string
import sys
import typing
import xml.etree.ElementTree as ET
import zipfile

import google.oauth2.service_account
import googleapiclient.discovery
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO_PATH = os.path.join(SCRIPT_DIR, 'default_logo.txt')


def load_default_logo() -> str:
    """Load default logo from file."""
    try:
        with open(DEFAULT_LOGO_PATH, encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning("Default logo file not found, using empty logo")
        return ""
    except OSError as e:
        logger.warning(f"Failed to read default logo: {e}")
        return ""


class Cell(typing.TypedDict, total=False):
    formattedValue: str


class MenuItem(typing.TypedDict):
    title: str
    price: str
    description: str
    image_src: str


class RowData(typing.TypedDict):
    values: list[Cell]


MenuData = dict[str, list[MenuItem]]
ImageMap = dict[tuple[int, int], str]


def get_config() -> tuple[str, str, dict[str, typing.Any]]:
    """Validate and return configuration from environment variables."""
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID environment variable is required")

    # An empty name selects the first tab. GitHub Actions passes an unset
    # secret as an empty string, so empty and missing mean the same.
    sheet_name = os.environ.get('SHEET_NAME', '').strip()

    gcp_creds_json = os.environ.get('GCP_CREDS_JSON')
    if not gcp_creds_json:
        raise ValueError("GCP_CREDS_JSON environment variable is required")

    try:
        gcp_creds = json.loads(gcp_creds_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"GCP_CREDS_JSON is not valid JSON: {e}") from e

    return spreadsheet_id, sheet_name, gcp_creds


def load_template() -> string.Template:
    """Load HTML template from file."""
    template_path = os.path.join(SCRIPT_DIR, 'template.html')
    with open(template_path, encoding='utf-8') as f:
        return string.Template(f.read())


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""
    os.makedirs('generated', exist_ok=True)


def get_cell_value(cell: Cell) -> str:
    """Extract the string value from a cell."""
    return cell.get('formattedValue', '')


def get_services(
    gcp_creds: dict[str, typing.Any],
) -> tuple[googleapiclient.discovery.Resource, googleapiclient.discovery.Resource]:
    """Initialize Google Sheets and Drive services."""
    creds = google.oauth2.service_account.Credentials.from_service_account_info(
        gcp_creds,
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly',
        ],
    )
    sheets = googleapiclient.discovery.build('sheets', 'v4', credentials=creds)
    drive = googleapiclient.discovery.build('drive', 'v3', credentials=creds)
    return sheets, drive


def download_xlsx(
    drive_service: googleapiclient.discovery.Resource,
    spreadsheet_id: str,
) -> bytes:
    """Download the spreadsheet as XLSX."""
    request = drive_service.files().export_media(
        fileId=spreadsheet_id,
        mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()


XLSX_NS = {
    'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
}
REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
IMAGE_MIME = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'gif': 'gif', 'webp': 'webp'}


def read_rels(zf: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Map relationship ids of an XLSX part to (type, resolved part path)."""
    rels_path = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
    if rels_path not in zf.namelist():
        return {}
    with zf.open(rels_path) as f:
        root = ET.parse(f).getroot()
    rels: dict[str, tuple[str, str]] = {}
    for rel in root.findall(f'{{{PKG_REL_NS}}}Relationship'):
        target = rel.get('Target', '')
        if target.startswith('/'):
            resolved = target.lstrip('/')
        else:
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        rels[rel.get('Id', '')] = (rel.get('Type', ''), resolved)
    return rels


def find_sheet_part(zf: zipfile.ZipFile, sheet_title: str) -> str | None:
    """Return the worksheet part for the tab with the given title, or the first tab for an empty title."""
    with zf.open('xl/workbook.xml') as f:
        sheets = ET.parse(f).getroot().findall('main:sheets/main:sheet', XLSX_NS)
    if not sheets:
        return None
    if not sheet_title:
        chosen = sheets[0]
    else:
        chosen = next((sh for sh in sheets if sh.get('name') == sheet_title), None)
        if chosen is None:
            # Images are keyed by cell only, so another tab's photos would land on the wrong dishes
            logger.warning(f"Tab '{sheet_title}' not found in the XLSX export, skipping images")
            return None
    rel = read_rels(zf, 'xl/workbook.xml').get(chosen.get(f'{{{REL_NS}}}id', ''))
    return rel[1] if rel else None


def images_from_xlsx(data: bytes, sheet_title: str) -> ImageMap:
    """Extract images anchored to cells of one tab, keyed by 0-based (row, col)."""
    image_map: ImageMap = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        sheet_part = find_sheet_part(zf, sheet_title)
        if not sheet_part:
            return image_map

        drawing_parts = [
            target for rel_type, target in read_rels(zf, sheet_part).values()
            if rel_type.endswith('/drawing')
        ]
        for drawing_part in drawing_parts:
            if drawing_part not in zf.namelist():
                continue
            drawing_rels = read_rels(zf, drawing_part)
            with zf.open(drawing_part) as f:
                root = ET.parse(f).getroot()

            anchors = root.findall('xdr:oneCellAnchor', XLSX_NS) + root.findall('xdr:twoCellAnchor', XLSX_NS)
            for anchor in anchors:
                col_elem = anchor.find('xdr:from/xdr:col', XLSX_NS)
                row_elem = anchor.find('xdr:from/xdr:row', XLSX_NS)
                blip = anchor.find('.//a:blip', XLSX_NS)
                if col_elem is None or row_elem is None or blip is None:
                    continue

                rel = drawing_rels.get(blip.get(f'{{{REL_NS}}}embed', ''))
                if not rel or rel[1] not in zf.namelist():
                    continue
                image_file = rel[1]
                mime = IMAGE_MIME.get(image_file.rsplit('.', 1)[-1].lower(), 'jpeg')
                b64 = base64.b64encode(zf.read(image_file)).decode('ascii')
                row, col = int(row_elem.text or '0'), int(col_elem.text or '0')
                image_map[(row, col)] = f"data:image/{mime};base64,{b64}"

    return image_map


def sheet_ranges(sheet_name: str) -> list[str]:
    """Build the A1 ranges for menu rows and the title cell of a tab."""
    if not sheet_name:
        return ['A2:E', 'H2']
    quoted = "'" + sheet_name.replace("'", "''") + "'"
    return [f'{quoted}!A2:E', f'{quoted}!H2']


def get_sheet_data(
    sheets_service: googleapiclient.discovery.Resource,
    spreadsheet_id: str,
    sheet_name: str,
) -> tuple[str, str, list[RowData]]:
    """Fetch the tab title, menu title and product rows from Google Sheets."""
    sheet_data = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        ranges=sheet_ranges(sheet_name),
        includeGridData=True,
        fields="sheets(properties.title,data.rowData.values(formattedValue))",
    ).execute()

    sheet = sheet_data['sheets'][0]
    sheet_title = sheet.get('properties', {}).get('title', sheet_name)
    data = sheet.get('data', [])

    title_data = None
    if len(data) > 1:
        title_range = data[1]
        if title_range.get('rowData'):
            row = title_range['rowData'][0]
            if row.get('values'):
                title_data = row['values'][0]

    menu_title = get_cell_value(title_data) if title_data else ""
    menu_title = menu_title or "Restaurant Menu"

    rows = data[0].get('rowData', []) if data else []
    return sheet_title, menu_title, rows


def process_menu_items(values: list[RowData], image_map: ImageMap) -> MenuData:
    """Process menu items and map embedded images."""
    menu: MenuData = {}

    for row_idx, row in enumerate(values):
        cells = row.get('values', [])
        title = get_cell_value(cells[0]) if len(cells) > 0 else ""
        price = get_cell_value(cells[1]) if len(cells) > 1 else ""
        category = get_cell_value(cells[2]) if len(cells) > 2 else ""
        description = get_cell_value(cells[3]) if len(cells) > 3 else ""

        if not title.strip() or not category.strip():
            if any(get_cell_value(cell) for cell in cells):
                logger.warning(f"Skipping sheet row {row_idx + 2}: it needs both a title and a category")
            continue

        # Image map uses (row, col) where row is 1-indexed from XLSX (row 1 = sheet row 2)
        # Data starts at row 2, so row_idx 0 corresponds to XLSX row 1
        image_src = image_map.get((row_idx + 1, 4), "")

        if category not in menu:
            menu[category] = []

        menu[category].append({
            'title': title,
            'price': price,
            'description': description,
            'image_src': image_src,
        })

    return menu


def generate_html(
    template: string.Template,
    menu_data: MenuData,
    title: str,
    logo_src: str,
) -> str:
    """Generate HTML from menu data with proper escaping."""
    escaped_title = html.escape(title)
    # Generate "All" button plus category buttons (all same style, no active state)
    btn_class = "px-3 py-1 text-sm rounded-full bg-gray-200 dark:bg-gray-700 hover:bg-indigo-600 hover:text-white"
    categories_html = f'''<button onclick="selectCategory('')" class="{btn_class}">All</button>'''
    categories_html += ''.join(
        f'''<button onclick="selectCategory({index})" class="{btn_class}">{html.escape(category)}</button>'''
        for index, category in enumerate(menu_data)
    )

    menu_items_html = ''
    item_id_counter = 0

    for index, (category, items) in enumerate(menu_data.items()):
        escaped_category = html.escape(category)
        menu_items_html += f'''
          <div id="cat-{index}" class="category-block col-span-12 mt-4">
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-gray-100 mb-2">{escaped_category}</h3>
            <ul class="grid md:grid-cols-3 gap-4">
        '''

        for item in items:
            item_id_counter += 1
            unique_id = str(item_id_counter)
            title_text = html.escape(item['title'])
            price_text = html.escape(item['price'])
            description = item['description'] or ""
            full_desc = html.escape(description)
            escaped_image_src = html.escape(item['image_src'])

            image_html = ''
            if item['image_src']:
                image_html = f'''
                  <div>
                    <img
                      class="h-48 md:h-64 w-48 md:w-64 bg-gray-50 rounded-lg dark:bg-gray-800 object-cover"
                      src="{escaped_image_src}"
                      alt="{title_text}"
                    />
                  </div>
                '''

            # Truncate before escaping, so an entity such as &amp; is never cut in half
            truncated_desc = full_desc
            more_button_html = ""
            if len(description) > 80:
                truncated_desc = html.escape(description[:80]) + "..."
                more_button_html = (
                    ' <button class="text-xs text-gray-700 hover:text-gray-900'
                    ' dark:text-gray-300 dark:hover:text-gray-100"'
                    f' onclick="expandItem(\'{unique_id}\')">More</button>'
                )

            desc_html = f'''
              <p
                id="desc_{unique_id}"
                data-full-description="{full_desc}"
                class="mt-1 overflow-hidden whitespace-normal text-xs leading-5 text-gray-500 dark:text-gray-400"
              >
                {truncated_desc}{more_button_html}
              </p>
            '''

            menu_items_html += f'''
            <li class="menu-item border border-gray-200 rounded-md p-2 flex justify-between gap-x-6 py-3 dark:border-gray-700">
              <div class="flex-1">
                <p class="item-title text-base font-semibold leading-6">{title_text}</p>
                <p class="mt-1 truncate text-sm leading-5 text-gray-500 dark:text-gray-400">{price_text}</p>
                {desc_html}
              </div>
              {image_html}
            </li>
            '''

        menu_items_html += '''
            </ul>
          </div>
        '''

    escaped_logo_src = html.escape(logo_src)
    return template.safe_substitute(
        title=escaped_title,
        logo_src=escaped_logo_src,
        categories=categories_html,
        menu_items=menu_items_html,
    )


def main() -> int:
    """Main function to generate the menu."""
    try:
        spreadsheet_id, sheet_name, gcp_creds = get_config()
        logger.info("Configuration loaded successfully")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    try:
        template = load_template()
        logger.info("Template loaded successfully")
    except FileNotFoundError:
        logger.error("Template file 'template.html' not found")
        return 1
    except OSError as e:
        logger.error(f"Failed to read template: {e}")
        return 1

    try:
        ensure_directories()
        sheets_service, drive_service = get_services(gcp_creds)
        logger.info("Google services initialized")

        sheet_title, menu_title, products_data = get_sheet_data(sheets_service, spreadsheet_id, sheet_name)
        logger.info(f"Fetched menu data from tab '{sheet_title}': '{menu_title}' with {len(products_data)} rows")

        image_map = images_from_xlsx(download_xlsx(drive_service, spreadsheet_id), sheet_title)
        logger.info(f"Extracted {len(image_map)} images from the tab")

        # Logo is at G2 which is (row=1, col=6) in 0-indexed XLSX coordinates
        logo_src = image_map.get((1, 6), "") or load_default_logo()

        menu = process_menu_items(products_data, image_map)
        total_items = sum(len(items) for items in menu.values())
        logger.info(f"Processed {total_items} menu items in {len(menu)} categories")

        generated_html = generate_html(template, menu, menu_title, logo_src)

        with open('generated/index.html', 'w', encoding='utf-8') as f:
            f.write(generated_html)
        logger.info("Generated index.html successfully")

        return 0

    except Exception:
        logger.exception("Failed to generate menu")
        return 1


if __name__ == "__main__":
    sys.exit(main())
