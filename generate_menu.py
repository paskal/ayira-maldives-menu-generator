import json
import os
import string
import typing

import google.api_core.client_options
import google.oauth2.service_account
import googleapiclient.discovery


class Cell(typing.TypedDict, total=False):
    formattedValue: str


class MenuItem(typing.TypedDict):
    title: str
    price: str
    description: str
    image_src: str


class RowData(typing.TypedDict):
    values: typing.List[Cell]


MenuData = typing.Dict[str, typing.List[MenuItem]]
ImageMap = typing.Dict[typing.Tuple[int, int], str]

# Configuration
SPREADSHEET_ID = os.environ['SPREADSHEET_ID']
SHEET_NAME = os.environ.get('SHEET_NAME', 'Sheet1')
GCP_CREDS = json.loads(os.environ['GCP_CREDS_JSON'])

# Taken from https://github.com/kevin-vaghasiya/restaurant-menu-webapp-gas,
# Author Kevin Vaghasiya.
HTML_TEMPLATE = string.Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    ::-webkit-scrollbar { width: 2px; }
    ::-webkit-scrollbar-thumb {
      background-color: #888;
      border-radius: 2px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background-color: #555;
    }
  </style>
</head>
<body class="container mx-auto">
  <div>
    <div class="grid grid-cols-3">
      <div class="col-span-3 md:col-span-1 flex justify-center md:block">
        <img id="logo_img" src="$logo_src" alt="${title} logo" class="h-24" />
      </div>
      <div class="col-span-3 md:col-span-2 px-4 md:flex md:flex-row-reverse justify-center items-end">
        <div class="md:w-1/2 md:ml-4">
          <label for="category" class="block text-xs font-medium leading-6 text-gray-700">Category</label>
          <select
            id="category"
            name="category"
            onchange="setItems()"
            class="block w-full rounded-md p-2 text-gray-900 border border-gray-300 rounded-lg bg-gray-50 focus:border-indigo-700"
          >
            <option selected value="">All</option>
            $categories
          </select>
        </div>
        <div class="flex-1 mt-4 md:w-1/2">
          <div class="relative">
            <div class="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
              <svg
                class="w-4 h-4 text-gray-500"
                aria-hidden="true"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 20 20"
              >
                <path
                  stroke="currentColor"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="m19 19-4-4m0-7A7 7 0 1 1 1 8a7 7 0 0 1 14 0Z"
                />
              </svg>
            </div>
            <input
              type="search"
              id="search"
              onkeyup="setItems()"
              class="block w-full p-2 pl-10 text-sm text-gray-900 border border-gray-300 rounded-lg bg-gray-50 focus:border-indigo-700"
              placeholder="Search"
            />
          </div>
        </div>
      </div>
    </div>
    <div class="my-2 p-2 bg-gray-50"></div>
    <div class="divider divide-y-2 px-4 pb-10" id="menu_wrapper">
      <!-- All categories + items go here -->
      $menu_items
    </div>
  </div>
  <script>
    // Toggle each item, then hide entire category blocks if all items are hidden
    function setItems() {
      const searchText = document.getElementById("search").value.toLowerCase();
      const selectedCategory = document.getElementById("category").value;
      const items = document.querySelectorAll(".menu-item");

      // 1. Show/Hide each item
      items.forEach(item => {
        const category = item.getAttribute("data-category");
        const name = item.querySelector(".item-title").innerText.toLowerCase();

        if (
          (selectedCategory === "" || category === selectedCategory) &&
          name.includes(searchText)
        ) {
          item.style.display = "block";
        } else {
          item.style.display = "none";
        }
      });

      // 2. For each category-block, hide if no item inside is visible
      const blocks = document.querySelectorAll(".category-block");
      blocks.forEach(block => {
        const blockItems = block.querySelectorAll(".menu-item");
        // Check if at least one is visible
        let anyVisible = false;
        blockItems.forEach(i => {
          if (i.style.display !== "none") {
            anyVisible = true;
          }
        });
        block.style.display = anyVisible ? "" : "none";
      });
    }

    // Expand truncated description on "More" click
    function expandItem(id) {
      const descEl = document.getElementById("desc_" + id);
      const fullDesc = descEl.getAttribute("data-full-description");
      descEl.innerText = fullDesc;
    }
  </script>
</body>
</html>
""")


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""
    for path in ['generated']:
        os.makedirs(path, exist_ok=True)


def get_cell_value(cell: Cell) -> str:
    """Extract the string value from a cell."""
    return cell.get('formattedValue', '')


def get_services() -> googleapiclient.discovery.Resource:
    """Initialize Google Sheets service."""
    creds = google.oauth2.service_account.Credentials.from_service_account_info(
        GCP_CREDS,
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets.readonly',
        ]
    )
    sheets = googleapiclient.discovery.build('sheets', 'v4', credentials=creds)
    return sheets


def get_sheet_data(sheets_service: googleapiclient.discovery.Resource) -> typing.Tuple[str, typing.List[RowData]]:
    """Fetch product data and menu title from Google Sheets."""
    # Get restaurant title and logo
    sheet_data = sheets_service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        ranges=[f"{SHEET_NAME}!A2:D", f"{SHEET_NAME}!G2:H2"],
        # Up to description, as photos are retrieved elsewhere, and separately title
        includeGridData=True,
        fields="sheets.data.rowData.values.formattedValue",
    ).execute()

    # Extract title from H2
    title_data = None
    for sheet in sheet_data['sheets']:
        for data in sheet['data']:
            if 'rowData' in data and data['rowData']:
                for row in data['rowData']:
                    if 'values' in row and len(row['values']) > 1:  # Looking for H2 cell
                        title_data = row['values'][-1]  # Last cell is H2
                        break

    menu_title = get_cell_value(title_data) if title_data else "Restaurant Menu"

    # return values for the first range (A2:D...) as product data
    return menu_title, sheet_data['sheets'][0]['data'][0].get('rowData', [])


def extract_image_ids(sheets_service: googleapiclient.discovery.Resource) -> ImageMap:
    """Extract images from a Google Spreadsheet (placeholder, not implemented)."""
    return {}


def process_menu_items(values: typing.List[typing.Dict[str, typing.Any]], image_map: ImageMap) -> MenuData:
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
        image_src = ""
        if image_id:
            # embedding image would be done here
            pass

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
    """Get logo path if it exists in G2 (index 6)."""
    logo_src = "data:image/jpg;base64,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"
    logo_id = image_map.get((2, 6))
    if logo_id:
        # Embed logo here
        pass
    return logo_src


def generate_html(menu_data: MenuData, title: str, logo_src: typing.Optional[str] = None) -> str:
    categories_html = ''.join(f'<option value="{category}">{category}</option>' for category in menu_data.keys())

    menu_items_html = ''
    item_id_counter = 0

    for category, items in menu_data.items():
        # Open a container (e.g. <div> or <li>) for this entire category
        menu_items_html += f'''
          <div class="category-block col-span-12 mt-4" data-category-group="{category}">
            <h3 class="text-lg font-medium leading-6 text-gray-900 mb-2">{category}</h3>
            <ul class="grid md:grid-cols-3 gap-4">
        '''

        # Add each item
        for item in items:
            item_id_counter += 1
            unique_id = str(item_id_counter)
            title_text = item['title']
            price_text = item['price']
            full_desc = item['description'] or ""
            image_html = ''
            if item['image_src']:
                image_html = f'''
                  <div>
                    <img
                      class="h-16 md:h-20 w-16 md:w-20 bg-gray-50 rounded-lg"
                      src="{item['image_src']}"
                      alt="{title_text}"
                    />
                  </div>
                '''

            # Truncate for "More" button
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

            # Each item has class="menu-item" and data-category
            menu_items_html += f'''
            <li class="menu-item border border-gray-200 rounded-md p-2 flex justify-between gap-x-6 py-3" data-category="{category}">
              <div class="flex-1">
                <p class="item-title text-base font-semibold leading-6 text-gray-800">{title_text}</p>
                <p class="mt-1 truncate text-sm leading-5 text-gray-500">{price_text}</p>
                {desc_html}
              </div>
              {image_html}
            </li>
            '''

        # Close the UL and container
        menu_items_html += '''
            </ul>
          </div>
        '''

    # Return the final HTML
    return HTML_TEMPLATE.substitute(
        title=title,
        logo_src=logo_src,
        categories=categories_html,
        menu_items=menu_items_html
    )


def main() -> None:
    """Main function to generate the menu."""
    ensure_directories()

    # Initialize services
    sheets_service = get_services()

    # Get sheet data with menu items and title
    menu_title, products_data = get_sheet_data(sheets_service)

    # Extract image IDs from sheet data (including logo)
    image_map = extract_image_ids(sheets_service)

    # Get logo source
    logo_src = get_logo_src(image_map)

    # Process menu items
    menu = process_menu_items(products_data, image_map)

    # Generate and save HTML
    html = generate_html(menu, menu_title, logo_src)

    with open('generated/index.html', 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == "__main__":
    main()
