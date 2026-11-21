# Ayira Maldives Menu Publishing

This repo hosts a **single-page HTML menu** for a guesthouse or restaurant, automatically generated from a Google Sheet.  
After the code runs, you’ll have:

- A live menu page on GitHub Pages.
- Automatic updates on every push or once a day.
- A QR code and link, so guests can open the menu on their phones.

## How It Works

1. We have a **Google Sheet** with columns:

        Title	Price	Category	Description	Photo		Logo

   in **columns A–E**. A dish needs at least a title and a category.
2. We **insert** a logo image in **cell G2** (with "logo" in G1).
3. We put the menu title, such as the restaurant name, in **cell H2**.
4. We **insert** dish images in the **Photo** column’s cells.
5. This Python script reads your Google credentials and:

- Fetches all rows of the sheet,
- Downloads embedded images (logo + dish images),
- Builds an `index.html` file with a mobile-friendly, dark-mode design,
- The workflow then deploys it to GitHub Pages.

## Step-by-Step Setup

1. **Fork this Repository**  
   On GitHub, click "Fork" to copy it into your own account. GitHub disables workflows in a fork until you enable them in its "Actions" tab.

2. **Create a Google Cloud Service Account**

- Go to [Google Cloud Console](https://console.cloud.google.com/).
- Create a new project (or pick an existing one).
- Find through search **Google Sheets API** and **Google Drive API** and enable them.
- In “APIs & Services → Credentials,” create a **Service Account** and write down it **email**.
- Open the service account, go to "Keys" → "Add key" → "Create new key" and choose **JSON**.
- Download the **JSON** credentials file, open it in a text editor, and copy the entire text.  
  This is your `GCP_CREDS_JSON`.

3. **Create a Google Sheet**

- At the top row, create these exact headers in columns **A** through **G**:
  ```
  Title	Price	Category	Description	Photo		Logo
  ```
- In **cell G2**, go to "Insert → Image → Insert image in cell" and pick the **logo** file.
- In **cell H2**, type the title shown at the top of the page. Without it, the page is titled "Restaurant Menu".
- For each dish row, do the same “Insert image in cell” in the **Photo** column if you have an image.
- Click "Share" and give the service account's email **Viewer** access, so the script can read the sheet.
- Copy the **spreadsheet ID** from the URL: if your sheet link is  
  `https://docs.google.com/spreadsheets/d/XXXXXXXXXX/edit#gid=0`,  
  the `XXXXXXXXXX` part is your **SPREADSHEET_ID**.

4. **Add GitHub Secrets**

- In your forked repository, click "Settings" → "Secrets and variables" → "Actions."
- Click "New repository secret" and add the following (exact name in uppercase):
    - `SPREADSHEET_ID` = your sheet's ID
    - `SHEET_NAME` = the sheet tab name if you want to use something other than the first tab, e.g. `Sheet1`
    - `GCP_CREDS_JSON` = the entire text from your service account JSON file

5. **Turn on GitHub Pages**

- In "Settings" → "Pages", set "Source" to **GitHub Actions**.

6. **That’s it!**

- When you push any change or at least once a day, GitHub Actions will run the `generate_menu.py` script, fetch your sheet, build `index.html`, and publish it to GitHub Pages.
- Your live menu will appear at `https://<yourUserOrOrg>.github.io/<yourRepoName>/index.html` (or just `<yourRepoName>`/ if you set the default to `index.html`).
- The workflow also creates an artifact each time it runs: **menu-qr.png** (a QR code pointing to the link).

### Converting an Existing JPG or PDF Menu to a Google Sheet

If you have a menu in JPG or PDF form, you can ask ChatGPT to parse it into columns.  
Here’s a **ready-made prompt**:

    Please read this menu image (or PDF) and convert it into tab-separated text with columns in the exact order:
    Title	Price	Category	Description

Then paste the text result into your Google Sheet (A–D) under the headers.

## Day-to-Day Usage

- **Price changes**: Just edit them in the Google Sheet. Wait for the daily auto-run, or open the "Deploy Menu" workflow in the "Actions" tab and click "Run workflow" to rebuild the page now.
- **Add new dishes**: Insert a new row in the Sheet with a Title, Price, Category, optional Description, and (optionally) “Insert → Image in cell” for Photo.
- **Check the build logs**: In GitHub → “Actions” tab of your repo.
- **If the page stops updating**: GitHub can disable the "Deploy Menu" workflow after 60 days of repository inactivity; while it is disabled, neither the daily run nor a push updates the page. If the workflow page in the "Actions" tab shows that it is disabled, click "Enable workflow", then "Run workflow" to rebuild the page now.

That’s it—enjoy your automated menu system!

---

**Questions?**  
Feel free to open an issue if something doesn’t work as expected.