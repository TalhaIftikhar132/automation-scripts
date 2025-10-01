import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urldefrag, urlparse
from collections import deque, defaultdict
import csv

# ---- CONFIG ----
START_URL = "https://ipadrental.us/"
DOMAIN = urlparse(START_URL).netloc
MAX_PAGES = 200
TITLE_MIN, TITLE_MAX = 30, 65
DESC_MIN, DESC_MAX = 70, 155

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

# ---- Fetch page ----
def fetch_page(url):
    try:
        resp = requests.get(url, headers={"User-Agent": "SEOAuditBot/1.0"}, timeout=12)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None

# ---- Audit one page ----
def audit_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    findings = {"url": url, "title": "", "title_status": "", "desc": "", "desc_status": "", "h1s": []}

    # Title
    title_tag = soup.find("title")
    if title_tag and title_tag.text.strip():
        title = title_tag.text.strip()
        findings["title"] = title
        if len(title) < TITLE_MIN:
            findings["title_status"] = "Too Short"
        elif len(title) > TITLE_MAX:
            findings["title_status"] = "Too Long"
        else:
            findings["title_status"] = "OK"
    else:
        findings["title_status"] = "Missing"

    # Description
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag and desc_tag.get("content", "").strip():
        desc = desc_tag["content"].strip()
        findings["desc"] = desc
        if len(desc) < DESC_MIN:
            findings["desc_status"] = "Too Short"
        elif len(desc) > DESC_MAX:
            findings["desc_status"] = "Too Long"
        else:
            findings["desc_status"] = "OK"
    else:
        findings["desc_status"] = "Missing"

    # H1s
    h1s = [h1.get_text(strip=True) for h1 in soup.find_all("h1")]
    findings["h1s"] = h1s

    return findings

# ---- Crawl website ----
def crawl_site():
    visited = set()
    queue = deque([START_URL])
    results = []

    while queue and len(visited) < MAX_PAGES:
        url = queue.popleft()
        if url in visited or urlparse(url).netloc != DOMAIN:
            continue

        print(f"🔎 Auditing: {url}")
        visited.add(url)

        html = fetch_page(url)
        if not html:
            continue

        # Audit page
        findings = audit_page(url, html)
        results.append(findings)

        # Extract links
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = normalize(link["href"], url)
            if href and urlparse(href).netloc == DOMAIN and href not in visited:
                queue.append(href)

    return results

# ---- Save results ----
def save_results(results):
    with open("seo_audit_ipadrental.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Page URL", "Title", "Title Status", "Description", "Description Status", "H1s"])
        for r in results:
            writer.writerow([r["url"], r["title"], r["title_status"], r["desc"], r["desc_status"], "; ".join(r["h1s"])])

    print("\n✅ Audit complete. Results saved to seo_audit_ipadrental.csv")

if __name__ == "__main__":
    results = crawl_site()
    save_results(results)
