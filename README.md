# Ayira Maldives Menu Publishing

This repo hosts a **single-page HTML menu** for a guesthouse or restaurant, automatically generated from a Google Sheet.  
After the code runs, you’ll have:

- A live menu page on GitHub Pages.
- Automatic updates on every push or once a day.
- A QR code and link, so guests can open the menu on their phones.

## How It Works

1. We have a **Google Sheet** with columns:

        Title	Price	Category	Description	Photo		Logo

   in **columns A–E**.
2. We **insert** a logo image in **cell G2** (with "logo" in G1).
3. We **insert** dish images in the **Photo** column’s cells.
4. This Python script reads your Google credentials and:

- Fetches all rows of the sheet,
- Downloads embedded images (logo + dish images),
- Builds an `index.html` file with a mobile-friendly, dark-mode design,
- Commits + deploys to GitHub Pages.

## Step-by-Step Setup

1. **Fork this Repository**  
   On GitHub, click "Fork" to copy it into your own account.

2. **Create a Google Cloud Service Account**

- Go to [Google Cloud Console](https://console.cloud.google.com/).
- Create a new project (or pick an existing one).
- Enable **Google Sheets API** and **Google Drive API**.
- In “APIs & Services → Credentials,” create a **Service Account** with these APIs enabled.
- Download the **JSON** credentials file, open it in a text editor, and copy the entire text.  
  This is your `GCP_CREDS_JSON`.

3. **Create a Google Sheet**

- At the top row, create these exact headers in columns **A** through **G**:
  ```
  Title	Price	Category	Description	Photo		Logo
  ```
- In **cell G2**, go to "Insert → Image → Insert image in cell" and pick the **logo** file.
- For each dish row, do the same “Insert image in cell” in the **Photo** column if you have an image.
- Copy the **spreadsheet ID** from the URL: if your sheet link is  
  `https://docs.google.com/spreadsheets/d/XXXXXXXXXX/edit#gid=0`,  
  the `XXXXXXXXXX` part is your **SPREADSHEET_ID**.

4. **Add GitHub Secrets**

- In your forked repository, click “Settings” → “Secrets and variables” → “Actions.”
- Click “New repository secret” and add the following (exact name in uppercase):
    - `SPREADSHEET_ID` = your sheet’s ID
    - `SHEET_NAME` = the sheet tab name if you want to use something other than the first tab, e.g. `Sheet1`
    - `RESTAURANT_TITLE` = e.g. `Ayira Maldives Menu` (optional; defaults to the same if not set)
    - `GCP_CREDS_JSON` = the entire text from your service account JSON file

5. **That’s it!**

- When you push any change or at least once a day, GitHub Actions will run the `generate_menu.py` script, fetch your sheet, build `index.html`, and push it back.
- Your live menu will appear at `https://<yourUserOrOrg>.github.io/<yourRepoName>/index.html` (or just `<yourRepoName>`/ if you set the default to `index.html`).
- The workflow also creates two artifacts each time it runs:
    1. **menu-url.txt** (the direct link),
    2. **menu-qr.png** (a QR code pointing to the link).

### Converting an Existing JPG or PDF Menu to a Google Sheet

If you have a menu in JPG or PDF form, you can ask ChatGPT to parse it into columns.  
Here’s a **ready-made prompt**:

    Please read this menu image (or PDF) and convert it into tab-separated text with columns in the exact order:
    Title	Price	Category	Description

Then paste the text result into your Google Sheet (A–E) under the headers.

## Day-to-Day Usage

- **Price changes**: Just edit them in the Google Sheet. Wait for the daily auto-run or push a dummy commit to trigger the workflow.
- **Add new dishes**: Insert a new row in the Sheet with a Title, Price, Category, optional Description, and (optionally) “Insert → Image in cell” for Photo.
- **Check the build logs**: In GitHub → “Actions” tab of your repo.

That’s it—enjoy your automated menu system!

---

**Questions?**  
Feel free to open an issue if something doesn’t work as expected.