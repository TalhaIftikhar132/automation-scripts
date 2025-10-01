"""
seo_crawler.py

A simple SEO crawler using Selenium + requests.

Features:
- Render pages with Selenium (headless Chrome)
- Extract title, meta description, H1, canonical, images (src+alt)
- Collect internal/external links
- Check HTTP status for links and images (using requests) concurrently
- Respect robots.txt
- Export results to CSV
"""

import time
import csv
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque, defaultdict

import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from urllib.robotparser import RobotFileParser

# ----------------------
# Configuration
# ----------------------
HEADLESS = True
USER_AGENT = "SeleniumSEO/1.0 (+https://example.com)"
MAX_PAGES = 200  # guard to avoid crawling entire web unintentionally
WORKERS = 10     # concurrency for requests checks
REQUEST_TIMEOUT = 10
POLITE_DELAY = 0.5  # seconds between page fetches
ALLOWED_SCHEMES = ("http", "https")
OUTPUT_CSV = "seo_crawl_results.csv"

# ----------------------
# Helpers
# ----------------------
def same_domain(base, url):
    try:
        return urllib.parse.urlparse(base).netloc == urllib.parse.urlparse(url).netloc
    except Exception:
        return False

def normalize_url(base, link):
    if not link:
        return None
    link = link.strip()
    # ignore javascript: and mailto:, tel:, anchors only
    if link.startswith("javascript:") or link.startswith("mailto:") or link.startswith("tel:") or link.startswith("#"):
        return None
    return urllib.parse.urljoin(base, link.split('#')[0])

def fetch_status(url):
    # returns (url, status_code or None, error or None)
    try:
        # use HEAD first, fallback to GET if not allowed
        resp = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code >= 400:
            # sometimes HEAD returns 405; fallback to GET
            if resp.status_code == 405:
                resp = requests.get(url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        return (url, resp.status_code, None)
    except requests.RequestException as e:
        return (url, None, str(e))

# ----------------------
# Crawler
# ----------------------
class SEOCrawler:
    def __init__(self, start_url, max_pages=MAX_PAGES, headless=HEADLESS):
        self.start_url = start_url.rstrip('/')
        self.base_netloc = urllib.parse.urlparse(self.start_url).netloc
        self.max_pages = max_pages
        self.visited = set()
        self.to_visit = deque([self.start_url])
        self.results = []  # list of dicts per page
        self.link_checks = {}  # url -> (status, error)
        self.image_checks = {}
        self.robots = RobotFileParser()
        self._init_robots()
        self._init_driver(headless)

    def _init_driver(self, headless):
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={USER_AGENT}")
        # optional: disable images to speed up rendering
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(30)
        except WebDriverException as e:
            print("Error starting Chrome WebDriver:", e)
            raise

    def _init_robots(self):
        robots_url = urllib.parse.urljoin(self.start_url, "/robots.txt")
        try:
            self.robots.set_url(robots_url)
            self.robots.read()
        except Exception:
            # if robots unreadable, default allow
            pass

    def _allowed_by_robots(self, url):
        try:
            return self.robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def crawl(self):
        while self.to_visit and len(self.visited) < self.max_pages:
            url = self.to_visit.popleft()
            if url in self.visited:
                continue
            if not self._allowed_by_robots(url):
                print(f"Blocked by robots.txt: {url}")
                self.visited.add(url)
                continue
            print(f"Crawling ({len(self.visited)+1}/{self.max_pages}): {url}")
            try:
                self._crawl_page(url)
            except Exception as e:
                print("Error crawling", url, e)
            self.visited.add(url)
            time.sleep(POLITE_DELAY)
        # At end, run checks for all discovered links/images
        self._bulk_check_links_images()
        return self.results

    def _crawl_page(self, url):
        try:
            self.driver.get(url)
        except TimeoutException:
            print("Timeout loading:", url)
        except WebDriverException as e:
            print("WebDriver exception loading:", url, e)

        page_data = {
            "url": url,
            "status": None,  # we'll fill from requests
            "title": None,
            "meta_description": None,
            "h1": None,
            "canonical": None,
            "internal_links": set(),
            "external_links": set(),
            "images": [],  # list of {"src", "alt"}
        }

        # use requests to get HTTP status
        s_url, status, err = fetch_status(url)
        page_data["status"] = status

        # Extract title
        try:
            title_el = self.driver.find_element(By.TAG_NAME, "title")
            page_data["title"] = title_el.get_attribute("textContent").strip() if title_el else ""
        except Exception:
            page_data["title"] = ""

        # meta description
        try:
            meta = self.driver.find_elements(By.XPATH, "//meta[translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='description']")
            if meta:
                page_data["meta_description"] = meta[0].get_attribute("content") or ""
            else:
                # try meta property
                meta = self.driver.find_elements(By.XPATH, "//meta[translate(@property,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='og:description']")
                page_data["meta_description"] = meta[0].get_attribute("content") if meta else ""
        except Exception:
            page_data["meta_description"] = ""

        # h1
        try:
            h1 = self.driver.find_elements(By.TAG_NAME, "h1")
            page_data["h1"] = h1[0].text.strip() if h1 else ""
        except Exception:
            page_data["h1"] = ""

        # canonical
        try:
            can = self.driver.find_elements(By.XPATH, "//link[translate(@rel,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='canonical']")
            page_data["canonical"] = can[0].get_attribute("href") if can else ""
        except Exception:
            page_data["canonical"] = ""

        # Collect links
        anchors = self.driver.find_elements(By.TAG_NAME, "a")
        for a in anchors:
            href = a.get_attribute("href")
            full = normalize_url(url, href)
            if not full:
                continue
            parsed = urllib.parse.urlparse(full)
            if parsed.scheme not in ALLOWED_SCHEMES:
                continue
            if same_domain(self.start_url, full):
                page_data["internal_links"].add(full)
                if full not in self.visited and full not in self.to_visit and len(self.visited) + len(self.to_visit) < self.max_pages:
                    self.to_visit.append(full)
            else:
                page_data["external_links"].add(full)

        # Images
        imgs = self.driver.find_elements(By.TAG_NAME, "img")
        for img in imgs:
            src = img.get_attribute("src")
            alt = img.get_attribute("alt") or ""
            nsrc = normalize_url(url, src)
            if not nsrc:
                continue
            page_data["images"].append({"src": nsrc, "alt": alt})

        # convert sets to lists for JSON/CSV friendliness
        page_data["internal_links"] = list(page_data["internal_links"])
        page_data["external_links"] = list(page_data["external_links"])

        self.results.append(page_data)

    def _bulk_check_links_images(self):
        # gather all unique URLs to check
        urls_to_check = set()
        images_to_check = set()
        for page in self.results:
            urls_to_check.update(page["internal_links"])
            urls_to_check.update(page["external_links"])
            for img in page["images"]:
                images_to_check.add(img["src"])

        print(f"Checking {len(urls_to_check)} links and {len(images_to_check)} images with {WORKERS} workers...")

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            # Links
            link_futures = {ex.submit(fetch_status, u): u for u in urls_to_check}
            for fut in as_completed(link_futures):
                u = link_futures[fut]
                try:
                    url, status, err = fut.result()
                    self.link_checks[u] = {"status": status, "error": err}
                except Exception as e:
                    self.link_checks[u] = {"status": None, "error": str(e)}
            # Images
            img_futures = {ex.submit(fetch_status, u): u for u in images_to_check}
            for fut in as_completed(img_futures):
                u = img_futures[fut]
                try:
                    url, status, err = fut.result()
                    self.image_checks[u] = {"status": status, "error": err}
                except Exception as e:
                    self.image_checks[u] = {"status": None, "error": str(e)}

    def save_csv(self, out_path=OUTPUT_CSV):
        # Flatten results into CSV-friendly rows: one row per page
        rows = []
        for p in self.results:
            broken_internal = [u for u in p["internal_links"] if (self.link_checks.get(u, {}).get("status") or 0) >= 400 or self.link_checks.get(u, {}).get("status") is None]
            broken_external = [u for u in p["external_links"] if (self.link_checks.get(u, {}).get("status") or 0) >= 400 or self.link_checks.get(u, {}).get("status") is None]
            broken_images = [img["src"] for img in p["images"] if (self.image_checks.get(img["src"], {}).get("status") or 0) >= 400 or self.image_checks.get(img["src"], {}).get("status") is None]

            rows.append({
                "page_url": p["url"],
                "http_status": p["status"],
                "title": p["title"],
                "meta_description": p["meta_description"],
                "meta_description_len": len(p["meta_description"] or ""),
                "h1": p["h1"],
                "canonical": p["canonical"],
                "internal_links_count": len(p["internal_links"]),
                "external_links_count": len(p["external_links"]),
                "images_count": len(p["images"]),
                "broken_internal_links": ";".join(broken_internal),
                "broken_external_links": ";".join(broken_external),
                "broken_images": ";".join(broken_images),
            })

        df = pd.DataFrame(rows)
        df.to_csv(out_path, index=False)
        print(f"Saved results to {out_path}")

    def shutdown(self):
        try:
            self.driver.quit()
        except Exception:
            pass

# ----------------------
# CLI runner
# ----------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python seo_crawler.py <start_url> [max_pages]")
        sys.exit(1)
    start_url = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_PAGES

    crawler = SEOCrawler(start_url, max_pages=max_pages)
    try:
        crawler.crawl()
        crawler.save_csv()
    finally:
        crawler.shutdown()


if __name__ == "__main__":
    main()
