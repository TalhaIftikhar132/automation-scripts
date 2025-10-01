from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import requests
import time
import csv
from urllib.parse import urljoin, urldefrag, urlparse
from collections import deque

# ---- CONFIG ----
START_URL = "https://technologyrental.sg/"
DOMAIN = urlparse(START_URL).netloc
MAX_PAGES = 500  # safeguard limit

# ---- Normalize URLs ----
def normalize(url, base):
    if not url:
        return ""
    url = url.strip()
    if url.startswith(("data:", "blob:", "mailto:", "javascript:")):
        return ""
    full = urljoin(base, url)
    full, _ = urldefrag(full)
    return full

# ---- HTTP check ----
def http_check(session, img_url, timeout=10):
    try:
        h = session.head(img_url, allow_redirects=True, timeout=timeout)
        return h.status_code
    except:
        try:
            g = session.get(img_url, allow_redirects=True, timeout=timeout, stream=True)
            return g.status_code
        except:
            return 0

# ---- Audit one page ----
def audit_page(driver, session, url):
    broken = []
    try:
        driver.get(url)
        time.sleep(1)

        images = driver.find_elements(By.TAG_NAME, "img")
        print(f"  Found {len(images)} images on {url}")

        for idx, img in enumerate(images, start=1):
            try:
                img_url = (img.get_attribute("currentSrc") or img.get_attribute("src") or "").strip()
                img_url = normalize(img_url, driver.current_url)

                if not img_url.startswith(("http://", "https://")):
                    natural_w = driver.execute_script("return arguments[0].naturalWidth||0;", img)
                    if natural_w == 0:
                        broken.append((url, img_url or "<empty src>", "naturalWidth=0"))
                    continue

                natural_w = driver.execute_script("return arguments[0].naturalWidth||0;", img)
                status = http_check(session, img_url)
                if natural_w == 0 or not (200 <= status < 400):
                    broken.append((url, img_url, f"HTTP {status}, naturalWidth={natural_w}"))

            except Exception as e:
                broken.append((url, "<error obtaining src>", str(e)))

    except Exception as e:
        print(f"  ⚠️ Error loading page {url}: {e}")

    return broken

# ---- Crawl website ----
def crawl_website():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

    session = requests.Session()
    session.headers.update({"User-Agent": "BrokenImageAudit/1.0"})

    visited = set()
    queue = deque([START_URL])
    all_broken = []

    while queue and len(visited) < MAX_PAGES:
        url = queue.popleft()
        if url in visited or urlparse(url).netloc != DOMAIN:
            continue

        print(f"\n🔎 Auditing: {url}")
        visited.add(url)

        broken = audit_page(driver, session, url)
        all_broken.extend(broken)

        # Collect internal links
        try:
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                href = normalize(href, driver.current_url)
                if href and urlparse(href).netloc == DOMAIN and href not in visited:
                    queue.append(href)
        except:
            pass

    driver.quit()

    # ---- Save to CSV ----
    with open("broken_images_report.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Page URL", "Image URL", "Issue"])
        writer.writerows(all_broken)

    print("\n====== AUDIT SUMMARY ======")
    if not all_broken:
        print("🎉 No broken images found.")
    else:
        print(f"❌ Found {len(all_broken)} broken images. See broken_images_report.csv")

if __name__ == "__main__":
    crawl_website()
