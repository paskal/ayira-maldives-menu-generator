import html
import json
import logging
import os
import string
import sys
import typing

import google.oauth2.service_account
import googleapiclient.discovery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO_PATH = os.path.join(SCRIPT_DIR, 'default_logo.txt')


def load_default_logo() -> str:
    """Load default logo from file."""
    try:
        with open(DEFAULT_LOGO_PATH, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning("Default logo file not found, using empty logo")
        return ""
    except IOError as e:
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

    sheet_name = os.environ.get('SHEET_NAME', 'Sheet1')

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
    with open(template_path, 'r', encoding='utf-8') as f:
        return string.Template(f.read())


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""
    os.makedirs('generated', exist_ok=True)


def get_cell_value(cell: Cell) -> str:
    """Extract the string value from a cell."""
    return cell.get('formattedValue', '')


def get_services(gcp_creds: dict[str, typing.Any]) -> googleapiclient.discovery.Resource:
    """Initialize Google Sheets service."""
    creds = google.oauth2.service_account.Credentials.from_service_account_info(
        gcp_creds,
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
    )
    return googleapiclient.discovery.build('sheets', 'v4', credentials=creds)


def get_sheet_data(
    sheets_service: googleapiclient.discovery.Resource,
    spreadsheet_id: str,
    sheet_name: str,
) -> tuple[str, list[RowData]]:
    """Fetch product data and menu title from Google Sheets."""
    sheet_data = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        ranges=[f"{sheet_name}!A2:D", f"{sheet_name}!G2:H2"],
        includeGridData=True,
        fields="sheets.data.rowData.values.formattedValue",
    ).execute()

    title_data = None
    for sheet in sheet_data['sheets']:
        for data in sheet['data']:
            if 'rowData' in data and data['rowData']:
                for row in data['rowData']:
                    if 'values' in row and len(row['values']) > 1:
                        title_data = row['values'][-1]
                        break

    menu_title = get_cell_value(title_data) if title_data else "Restaurant Menu"
    return menu_title, sheet_data['sheets'][0]['data'][0].get('rowData', [])


def process_menu_items(values: list[RowData], image_map: ImageMap) -> MenuData:
    """Process menu items and handle embedded images."""
    menu: MenuData = {}

    for i, row in enumerate(values, start=2):
        if 'values' not in row or len(row['values']) < 3:
            continue

        cells = row['values']
        title = get_cell_value(cells[0])
        price = get_cell_value(cells[1])
        category = get_cell_value(cells[2])
        description = get_cell_value(cells[3]) if len(cells) > 3 else ""

        # image embedding not yet implemented
        image_src = ""

        if category not in menu:
            menu[category] = []

        menu[category].append({
            'title': title,
            'price': price,
            'description': description,
            'image_src': image_src,
        })

    return menu


def get_logo_src(image_map: ImageMap) -> str:
    """Get logo path if it exists in G2 (index 6), otherwise return default."""
    # image embedding not yet implemented
    return load_default_logo()


def generate_html(
    template: string.Template,
    menu_data: MenuData,
    title: str,
    logo_src: str,
) -> str:
    """Generate HTML from menu data with proper escaping."""
    escaped_title = html.escape(title)
    categories_html = ''.join(
        f'<option value="{html.escape(category)}">{html.escape(category)}</option>'
        for category in menu_data.keys()
    )

    menu_items_html = ''
    item_id_counter = 0

    for category, items in menu_data.items():
        escaped_category = html.escape(category)
        menu_items_html += f'''
          <div class="category-block col-span-12 mt-4" data-category-group="{escaped_category}">
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-gray-100 mb-2">{escaped_category}</h3>
            <ul class="grid md:grid-cols-3 gap-4">
        '''

        for item in items:
            item_id_counter += 1
            unique_id = str(item_id_counter)
            title_text = html.escape(item['title'])
            price_text = html.escape(item['price'])
            full_desc = html.escape(item['description'] or "")
            escaped_image_src = html.escape(item['image_src'])

            image_html = ''
            if item['image_src']:
                image_html = f'''
                  <div>
                    <img
                      class="h-16 md:h-20 w-16 md:w-20 bg-gray-50 rounded-lg dark:bg-gray-800"
                      src="{escaped_image_src}"
                      alt="{title_text}"
                    />
                  </div>
                '''

            truncated_desc = full_desc
            more_button_html = ""
            if len(full_desc) > 80:
                truncated_desc = full_desc[:80] + "..."
                more_button_html = f' <button class="text-xs text-gray-700 hover:text-gray-900" onclick="expandItem(\'{unique_id}\')">More</button>'

            desc_html = f'''
              <p
                id="desc_{unique_id}"
                data-full-description="{full_desc}"
                class="mt-1 overflow-hidden whitespace-normal text-xs leading-5 text-gray-500"
              >
                {truncated_desc}{more_button_html}
              </p>
            '''

            menu_items_html += f'''
            <li class="menu-item border border-gray-200 rounded-md p-2 flex justify-between gap-x-6 py-3 dark:border-gray-700" data-category="{escaped_category}">
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
    except IOError as e:
        logger.error(f"Failed to read template: {e}")
        return 1

    try:
        ensure_directories()
        sheets_service = get_services(gcp_creds)
        logger.info("Google Sheets service initialized")

        menu_title, products_data = get_sheet_data(sheets_service, spreadsheet_id, sheet_name)
        logger.info(f"Fetched menu data: '{menu_title}' with {len(products_data)} rows")

        image_map: ImageMap = {}
        logo_src = get_logo_src(image_map)

        menu = process_menu_items(products_data, image_map)
        total_items = sum(len(items) for items in menu.values())
        logger.info(f"Processed {total_items} menu items in {len(menu)} categories")

        generated_html = generate_html(template, menu, menu_title, logo_src)

        with open('generated/index.html', 'w', encoding='utf-8') as f:
            f.write(generated_html)
        logger.info("Generated index.html successfully")

        return 0

    except Exception as e:
        logger.exception(f"Failed to generate menu: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
