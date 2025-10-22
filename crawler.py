from __future__ import annotations
import re, heapq, unicodedata
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

# Alcuni PDF sono ospitati su CDN o storage esterni leciti per documenti societari
ALLOWED_EXTERNAL_PDF_HOSTS = [
    "emarketstorage.com",   # frequente per società quotate
    "borsaitaliana.it",
    "azureedge.net",
    "amazonaws.com",
    "cloudfront.net",
    "sharepoint.com",
    "microsoft.com",
]

# Lessico: italiano + inglese + termini struttura
KEY_TERMS = [
    # IT
    "bilancio", "bilanci", "bilancio d'esercizio", "bilancio consolidato",
    "relazione finanziaria annuale", "relazione annuale integrata",
    "bilanci e relazioni", "documenti finanziari", "documentazione finanziaria",
    # EN
    "financial statements", "consolidated financial statements",
    "annual report", "integrated annual report", "financial report",
    # Struttura / sezioni
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

def _registrable(host: str) -> str:
    # Heuristica: ultimi due label (estra.it, gruppohera.it)
    parts = (host or "").split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:]).lower()
    return (host or "").lower()

def _same_domain(seed: str, url: str) -> bool:
    a = urlparse(seed).netloc.lower()
    b = urlparse(url).netloc.lower()
    if a == b or a.endswith("." + b) or b.endswith("." + a):
        return True
    return _registrable(a) == _registrable(b)

def _is_allowed_external_pdf(seed: str, url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if not url.lower().endswith(".pdf"):
        return False
    return any(h in host for h in ALLOWED_EXTERNAL_PDF_HOSTS)

def _score_link(url: str, anchor_text: str, year: int) -> float:
    t = _norm(anchor_text) + " " + _norm(url)
    score = 0.0
    # anno nel testo/link (considera anche year-1 per etichette fuorvianti)
    if str(year) in t or str(year - 1) in t:
        score += 1.5
    # parole chiave
    for k in KEY_TERMS:
        if k in t:
            score += 1.0
    # suggeritori di struttura nell'URL
    for h in URL_HINTS:
        if h in url.lower():
            score += 0.8
    # PDF bonus (+ extra se host esterno ammesso)
    if url.lower().endswith(".pdf"):
        score += 1.2
        host = urlparse(url).netloc.lower()
        if any(h in host for h in ALLOWED_EXTERNAL_PDF_HOSTS):
            score += 0.5
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
    """
    Visita il dominio a partire dagli entrypoint HTML e ritorna il primo PDF 'buono' per l'anno.
    Ritorna dict con chiavi: pdf|None, score, via, visited, reason (se non trovato).
    """
    visited = set()
    # priority queue: (-score, depth, url, anchor, parent)
    pq = []
    for u in entry_urls:
        heapq.heappush(pq, (-5.0, 0, u, "entry", None))

    with httpx.Client(follow_redirects=True, timeout=timeout, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BilanciCrawler/1.0)"
    }) as client:
        while pq and len(visited) < max_pages:
            neg_s, depth, url, text, parent = heapq.heappop(pq)
            if url in visited:
                continue
            visited.add(url)
            if depth > max_depth:
                continue

            # Caso: già PDF plausibile
            if url.lower().endswith(".pdf") and _score_link(url, text, year) >= 2.0:
                return {"pdf": url, "score": _score_link(url, text, year), "via": parent or "seed", "visited": len(visited)}

            # Fetch HTML
            try:
                r = client.get(url)
                if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                    continue
                html = r.text
            except Exception:
                continue

            # Estrai link e valuta
            links = _extract_links(url, html)
            origin = entry_urls[0]
            for u2, txt in links:
                same_dom = _same_domain(origin, u2)
                allowed_ext_pdf = _is_allowed_external_pdf(origin, u2)
                if not same_dom and not allowed_ext_pdf:
                    continue

                # scarta protocolli non http(s), mailto, anchor
                if not u2.lower().startswith(("http://", "https://")):
                    continue
                if u2.lower().startswith(("mailto:", "tel:")) or u2.endswith("#"):
                    continue

                sc = _score_link(u2, txt, year)

                # se è PDF e score alto → return
                if u2.lower().endswith(".pdf") and sc >= 2.0:
                    return {"pdf": u2, "score": sc, "via": url, "visited": len(visited)}

                # enqueue per navigare
                heapq.heappush(pq, (-sc, depth + 1, u2, txt, url))

    return {"pdf": None, "reason": "not_found_within_limits", "visited": len(visited)}
