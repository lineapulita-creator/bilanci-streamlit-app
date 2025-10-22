from __future__ import annotations
import re, heapq, unicodedata
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

KEY_TERMS = [
    "bilancio", "bilanci", "bilancio d'esercizio", "bilancio consolidato",
    "relazione finanziaria annuale", "relazione annuale integrata",
    "bilanci e relazioni", "documenti finanziari", "documentazione finanziaria",
    "financial statements", "consolidated financial statements",
    "annual report", "integrated annual report", "financial report",
    "investor", "investor relations", "investitori",
    "amministrazione trasparente", "trasparenza", "bilanci-relazioni"
]
URL_HINTS = [
    "investor", "investor-relations", "investitori", "relazioni", "bilanci",
    "financial", "report", "documenti", "amministrazione-trasparente",
    "governance", "documentation"
]

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s.strip().lower())

def _same_domain(seed: str, url: str) -> bool:
    a = urlparse(seed).netloc
    b = urlparse(url).netloc
    return a == b or b.endswith("." + a) or a.endswith("." + b)

def _score_link(url: str, anchor_text: str, year: int) -> float:
    t = _norm(anchor_text) + " " + _norm(url)
    score = 0.0
    if str(year) in t or str(year-1) in t:
        score += 1.5
    for k in KEY_TERMS:
        if k in t: score += 1.0
    for h in URL_HINTS:
        if h in url.lower(): score += 0.8
    if url.lower().endswith(".pdf"): score += 1.2
    return score

def _extract_links(base_url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        url = urljoin(base_url, href)
        txt = a.get_text(" ", strip=True) or href
        if url not in seen:
            seen.add(url); out.append((url, txt))
    return out

def crawl_for_pdf(entry_urls: list[str], year: int, max_pages=50, max_depth=4, timeout=15) -> dict:
    visited = set()
    pq = []  # (-score, depth, url, anchor, parent)
    for u in entry_urls:
        heapq.heappush(pq, (-5.0, 0, u, "entry", None))

    with httpx.Client(follow_redirects=True, timeout=timeout, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BilanciCrawler/1.0)"
    }) as client:
        while pq and len(visited) < max_pages:
            neg_s, depth, url, text, parent = heapq.heappop(pq)
            if url in visited: continue
            visited.add(url)
            if depth > max_depth: continue

            if url.lower().endswith(".pdf") and _score_link(url, text, year) >= 2.0:
                return {"pdf": url, "score": _score_link(url, text, year), "via": parent or "seed", "visited": len(visited)}

            try:
                r = client.get(url)
                if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                    continue
                html = r.text
            except Exception:
                continue

            links = _extract_links(url, html)
            origin = entry_urls[0]
            for u2, txt in links:
                if not _same_domain(origin, u2): continue
                sc = _score_link(u2, txt, year)
                if u2.lower().endswith(".pdf") and sc >= 2.0:
                    return {"pdf": u2, "score": sc, "via": url, "visited": len(visited)}
                heapq.heappush(pq, (-sc, depth+1, u2, txt, url))

    return {"pdf": None, "reason": "not_found_within_limits", "visited": len(visited)}
