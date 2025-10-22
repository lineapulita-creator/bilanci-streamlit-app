# semantic_crawler/crawler_semantic.py
import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque

from .matchers import classify, is_pdf, host_of

DEFAULT_TIMEOUT = 15.0

def normalize_base(base_url: str) -> str:
    return base_url.rstrip("/")

def same_site(url: str, base: str) -> bool:
    return urlparse(url).netloc.lower().endswith(urlparse(base).netloc.lower())

async def fetch_text(client: httpx.AsyncClient, url: str) -> tuple[int, str, str]:
    try:
        r = await client.get(url, timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        ctype = r.headers.get("content-type", "")
        text = r.text if "text/html" in ctype.lower() else ""
        return r.status_code, ctype, text
    except Exception:
        return 0, "", ""

def extract_links(base_url: str, html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url + "/", href)
        txt = (a.get_text() or "").strip()
        out.append((full, txt))
    return out

async def crawl_and_classify(config: dict) -> dict:
    base = normalize_base(config["base_url"])
    seeds = [urljoin(base + "/", s) for s in config.get("seeds", [])]
    allow_hosts = [h.lower() for h in config.get("allowlist_hosts", [])]
    max_depth = int(config.get("max_depth", 2))
    max_pages = int(config.get("max_pages", 60))
    top_n = int(config.get("top_n_links", 20))
    ua = config.get("user_agent", "EstraSemanticCrawler/1.0")

    visited = set()
    q = deque([(s, 0) for s in seeds])
    results = []

    headers = {"User-Agent": ua, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}

    async with httpx.AsyncClient(headers=headers) as client:
        pages_count = 0
        while q and pages_count < max_pages and len(results) < top_n:
            url, depth = q.popleft()
            if url in visited or depth > max_depth:
                continue
            visited.add(url)
            status, ctype, html = await fetch_text(client, url)
            pages_count += 1

            # Salta non-HTML
            if status != 200 or "text/html" not in ctype.lower() or not html:
                continue
            links = extract_links(url, html)

            # Classifica i link appena estratti
            for href, txt in links:
                cat, conf = classify(href, txt, allow_hosts)
                results.append({
                    "url": href,
                    "text": txt,
                    "category": cat,
                    "confidence": conf,
                    "host": host_of(href),
                    "is_pdf": is_pdf(href),
                    "from_page": url
                })
                if len(results) >= top_n:
                    break

            # Enqueue navigazione interna (solo stesso sito)
            if depth < max_depth:
                for href, _ in links:
                    if same_site(href, base) and href not in visited and not is_pdf(href):
                        q.append((href, depth + 1))

            # Stop se abbiamo già i top N
            if len(results) >= top_n:
                break
    # Ordina: prima i target più promettenti
    results.sort(key=lambda r: (
        0 if r["category"] in ["pdf_bilancio_target", "pdf_sostenibilita_target"] else
        1 if r["category"] in ["pdf_bilancio_generico", "section_bilanci"] else
        2 if r["category"].startswith("host_esterno") else
        3,
        -r["confidence"]
    ))

    return {
        "ok": True,
        "scanned_pages": len(visited),
        "returned": len(results),
        "items": results[:top_n]
    }
