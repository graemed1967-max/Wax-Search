# Wax Mage Tracker

Tracks Wax Mage vinyl (hand-poured Editions /25, Collabs, Exclusives) across Gotta Groove's store and blog,
Bandcamp labels, Shopify and WooCommerce shops. Shows what is in stock, on pre-order, announced or sold out,
and flags anything new.

## Android setup (about 10 minutes, free)

You host it on GitHub. GitHub scans every hour and publishes the page; your phone just opens the link.

1. Make a free account at github.com, then **New repository** (e.g. `wax-mage`), set to Public.
2. Upload every file from this folder: **Add file > Upload files**. Drag in the contents of the unzipped
   folder, including the hidden `.github` folder (if your file manager hides it, create it in the GitHub
   web editor: **Add file > Create new file**, name it `.github/workflows/scan.yml`, paste the contents).
3. **Settings > Pages**: Source = *Deploy from a branch*, Branch = `main`, folder `/ (root)`. Save.
   Your site will be at `https://YOUR-USERNAME.github.io/wax-mage/`.
4. **Actions** tab: enable workflows if asked, open *Scan Wax Mage stock*, tap **Run workflow**.
   After a minute the page shows real stock. From then on it refreshes itself hourly.
5. On your phone, open the link in Chrome, tap the menu (three dots) > **Add to Home screen** / **Install app**.

### Phone alerts when something new drops (optional)
1. Install the free **ntfy** app from Google Play and tap **+** to subscribe to a topic with a long, random
   name nobody could guess, e.g. `waxmage-k7x2q9m4p1`.
2. In your GitHub repo: **Settings > Secrets and variables > Actions > New repository secret**,
   name `NTFY_TOPIC`, value = the same topic name.
3. You'll get a notification for new listings, new announcements and restocks. Tapping it opens the tracker.
   (Anyone who knows the topic name can read the alerts, so keep it private.)

## Run it on a computer instead
    pip install -r requirements.txt
    python tracker.py        # scans every source, writes data.json + data.js
    open index.html          # just double-click it; no server needed

## Add sources
Edit `sources.json`: add a Bandcamp label (`"sub": "labelname"`), a Shopify store (`"domain"`), or a WooCommerce
store (`"base"`). Bandcamp labels that mention Wax Mage are also found automatically and remembered.

## Not scanned automatically
eBay and Discogs need API keys / block scraping, so the page links to live searches for them instead.

## Tests
    python tests/test_tracker.py   # offline, uses sample pages
