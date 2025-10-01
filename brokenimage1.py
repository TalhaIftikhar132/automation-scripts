# fast_broken_images_crawler.py

import time
import requests
import openpyxl
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from collections import deque
from concurrent.futures import ThreadPoolExecutor


# Device viewports
DEVICES = {
    "Desktop": (1920, 1080),
     "laptops":(1025,1420),
    "iPad": (768, 1024),
    "Mobile": (375, 667),
}

START_URL = "https://technologyrental.sg/"   # change to your website
MAX_PAGES = 300                     # audit limit
MAX_WORKERS = 20                    # parallel HTTP requests
TIMEOUT = 3                         # HTTP timeout in seconds


def setup_driver():
    """Launch Chrome once and reuse by resizing."""
    chrome_options = Options()
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver


def check_image_status(src):
    """Check if image URL is broken."""
    if not src:
        return "Missing src"
    try:
        response = requests.get(src, timeout=TIMEOUT)
        if response.status_code == 200:
            return "OK"
        else:
            return f"Broken (Status {response.status_code})"
    except Exception as e:
        return f"Error: {str(e)}"


def check_images(driver, device):
    """Check all images on current page using threads."""
    results = []
    images = driver.find_elements(By.TAG_NAME, "img")
    img_srcs = [img.get_attribute("src") for img in images]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        statuses = list(executor.map(check_image_status, img_srcs))

    for src, status in zip(img_srcs, statuses):
        results.append((device, driver.current_url, src if src else "N/A", status))

    return results


def get_links(driver, base_url):
    """Extract internal links from current page."""
    links = set()
    for el in driver.find_elements(By.TAG_NAME, "a"):
        href = el.get_attribute("href")
        if href and href.startswith(base_url):
            links.add(href.split("#")[0])  # remove anchors
    return links


def save_to_excel(results, filename="broken_images_fast_audit.xlsx"):
    """Save results to Excel file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Broken Images Report"

    headers = ["Device", "Page URL", "Image URL", "Status"]
    ws.append(headers)

    for row in results:
        ws.append(row)

    wb.save(filename)
    print(f"✅ Report saved as {filename}")


def crawl_site():
    all_results = []
    visited = set()
    queue = deque([START_URL])

    base_url = urlparse(START_URL).scheme + "://" + urlparse(START_URL).netloc
    driver = setup_driver()

    while queue and len(visited) < MAX_PAGES:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        print(f"\n🌍 Crawling {url} ({len(visited)}/{MAX_PAGES})")
        try:
            driver.get(url)
            time.sleep(2)  # short wait

            for device, (width, height) in DEVICES.items():
                driver.set_window_size(width, height)
                time.sleep(0.5)  # allow resize
                results = check_images(driver, device)
                all_results.extend(results)

            # collect links (desktop only to avoid duplicates)
            links = get_links(driver, base_url)
            for link in links:
                if link not in visited and len(visited) + len(queue) < MAX_PAGES:
                    queue.append(link)

        except Exception as e:
            print(f"⚠️ Error on {url}: {e}")

    driver.quit()
    save_to_excel(all_results)


if __name__ == "__main__":
    crawl_site()
