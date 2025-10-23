# app.py
# ============================================
# Streamlit App – Crawler semantico (Estra)
# Tutto-in-uno, pronto da incollare
# ============================================

import os
import io
import time
import math
import json
from collections import deque
from typing import Optional, List, Dict, Any, Set, Tuple
from urllib.parse import urljoin, urlparse

import streamlit as st
import pandas as pd

# Tentativo di import del crawler esterno (se lo hai come modulo)
_CRAWLER_IMPORTED = False
try:
    from semantic_crawler.crawler_semantic import crawl_and_classify as _external_crawl_and_classify
    _CRAWLER_IMPORTED = True
except Exception:
    _CRAWLER_IMPORTED = False

# Import "soft" per dipendenze usate nel fallback
try:
    import httpx
except Exception:
    httpx = None

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# PDF text extraction libs (optional)
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

# OCR libs (optional)
try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from pdf2image import convert_from_bytes
except Exception:
    convert_from_bytes = None

# toml config read: try built-in/more common libs
try:
    import tomllib  # py3.11+
except Exception:
    try:
        import tomli as tomllib  # pip install tomli
    except Exception:
        tomllib = None

# robots parser
from urllib import robotparser

# --------------------------------------------
# Config generale
# --------------------------------------------
APP_TITLE = "Bilanci & DNF – Crawler semantico (Estra)"
APP_VERSION = "1.0.1"
# User-Agent chiaro e con riferimento di contatto (aiuta a non essere bloccati)
DEFAULT_UA = (
    "BilanciCrawler/1.0 (+https://github.com/lineapulita-creator) "
    "Mozilla/5.0 (compatible;)"
)

st.set_page_config(page_title=APP_TITLE, page_icon="🔎", layout="wide")


# --------------------------------------------
# Helpers per leggere la config di ricerca
# (si aspetta streamlit/config.toml con google_api.key e google_api.cx)
# --------------------------------------------
def load_search_config() -> Dict[str, str]:
    cfg = {}
    cfg_path = os.path.join("streamlit", "config.toml")
    if os.path.exists(cfg_path):
        try:
            if tomllib:
                with open(cfg_path, "rb") as f:
                    data = tomllib.load(f)
            else:
                # semplice parser manuale: cerca le righe key = "value"
                data = {}
                with open(cfg_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            data[k] = v
            # support nested table like [google_api]
            if "google_api" in data and isinstance(data["google_api"], dict):
                cfg["api_key"] = data["google_api"].get("key") or data["google_api"].get("api_key") or data["google_api"].get("key")
                cfg["cx"] = data["google_api"].get("cx")
            else:
                # try direct keys
                cfg["api_key"] = data.get("google_api.key") or data.get("google_api_key") or data.get("api_key") or data.get("key")
                cfg["cx"] = data.get("google_api.cx") or data.get("google_cx") or data.get("cx")
        except Exception:
            cfg = {}
    return cfg


# --------------------------------------------
# Google CSE wrapper (usa httpx)
# --------------------------------------------
def search_google_cse(query: str, api_key: str, cx: str, num: int = 5, timeout: float = 15.0) -> List[Dict[str, Any]]:
    """
    Esegue una query su Google Custom Search API e ritorna la lista di result items.
    Richiede: api_key e cx.
    """
    if httpx is None:
        raise RuntimeError("httpx non disponibile")
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"q": query, "key": api_key, "cx": cx, "num": num}
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            return data.get("items", [])
    except Exception:
        return []


# --------------------------------------------
# Helpers per pdf: download e estrazione testo (include OCR)
# --------------------------------------------
def download_binary(url: str, timeout: float = 30.0) -> Optional[bytes]:
    if httpx is None:
        return None
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            r = client.get(url)
            if r.status_code == 200:
                return r.content
    except Exception:
        return None
    return None


def ocr_pdf_bytes(data: bytes, dpi: int = 200, lang: str = "ita") -> str:
    """
    Converte le pagine PDF in immagini (pdf2image) e esegue pytesseract OCR.
    Restituisce il testo concatenato. Richiede poppler (system) e tesseract disponibile.
    """
    if convert_from_bytes is None or pytesseract is None:
        return ""
    texts = []
    try:
        images = convert_from_bytes(data, dpi=dpi)
    except Exception:
        return ""
    for img in images:
        try:
            text = pytesseract.image_to_string(img, lang=lang)
            texts.append(text or "")
        except Exception:
            texts.append("")
    return "\n".join(texts)


def extract_text_from_pdf_bytes(data: bytes) -> Tuple[str, bool]:
    """
    Ritorna (text, needs_ocr_bool).
    Usa pdfplumber se disponibile, altrimenti PyPDF2 come fallback.
    Se non riesce a estrarre testo restituisce ('', True).
    Se OCR possibile, caller può usare ocr_pdf_bytes.
    """
    if not data:
        return "", False
    # Try pdfplumber
    if pdfplumber is not None:
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = []
                for p in pdf.pages:
                    try:
                        pages.append(p.extract_text() or "")
                    except Exception:
                        pages.append("")
                text = "\n".join(pages)
                if text and text.strip():
                    return text, False
        except Exception:
            pass
    # Try PyPDF2
    if PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for p in reader.pages:
                try:
                    pages.append(p.extract_text() or "")
                except Exception:
                    pages.append("")
            text = "\n".join(pages)
            if text and text.strip():
                return text, False
        except Exception:
            pass
    # Fall back: no text extracted -> needs OCR
    return "", True


# --------------------------------------------
# Utilità per trovare valori vicino alla keyword
# --------------------------------------------
import re

NUMBER_RE = re.compile(r"[-+]?\d[\d\.\,\s]*\d(?:\s*(?:€|EUR|eur)?)?")

def normalize_number_str(s: str) -> str:
    s = s.strip()
    s = s.replace("\u00a0", " ")
    # remove spaces in thousands, but keep decimal separators
    s = s.replace(" ", "")
    # If contains both comma and dot, guess thousand separator
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    s = re.sub(r"[^\d\.\-+]", "", s)
    return s

def find_value_near_keywords(text: str, keywords: List[str]) -> (Optional[str], Optional[str]):
    txt_low = text.lower()
    for kw in keywords:
        kw_l = kw.lower()
        idx = txt_low.find(kw_l)
        if idx >= 0:
            start = max(0, idx - 300)
            end = min(len(text), idx + len(kw_l) + 300)
            window = text[start:end]
            m = NUMBER_RE.search(window)
            if m:
                raw = m.group(0)
                norm = normalize_number_str(raw)
                return kw, norm
            else:
                start = max(0, idx - 800)
                end = min(len(text), idx + len(kw_l) + 800)
                window = text[start:end]
                m = NUMBER_RE.search(window)
                if m:
                    raw = m.group(0)
                    norm = normalize_number_str(raw)
                    return kw, norm
    return None, None


# --------------------------------------------
# Politeness + robots helpers
# --------------------------------------------
_robot_parsers: Dict[str, Optional[robotparser.RobotFileParser]] = {}
_last_request_time: Dict[str, float] = {}

def _get_host(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""

def allowed_by_robots(url: str, user_agent: str = "*") -> bool:
    host = _get_host(url)
    if not host:
        return False
    rp = _robot_parsers.get(host)
    if rp is None:
        robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
        rp = robotparser.RobotFileParser()
        try:
            rp.set_url(robots_url)
            rp.read()
        except Exception:
            _robot_parsers[host] = None
            return True
        _robot_parsers[host] = rp
    if _robot_parsers.get(host) is None:
        return True
    try:
        return _robot_parsers[host].can_fetch(user_agent, url)
    except Exception:
        return True

def polite_get(client: "httpx.Client", url: str, min_delay: float = 0.8) -> "httpx.Response":
    host = _get_host(url)
    now = time.time()
    last = _last_request_time.get(host, 0.0)
    wait = max(0.0, min_delay - (now - last))
    if wait > 0:
        time.sleep(wait)
    resp = client.get(url)
    _last_request_time[host] = time.time()
    return resp


# --------------------------------------------
# Adapter / Fallback crawler (semplificato)
# --------------------------------------------
def _is_pdf_url(url: str) -> bool:
    u = url.lower()
    return u.endswith(".pdf") or "application/pdf" in u

def _year_from_text(text: str, candidates=(2022, 2023, 2024, 2025)) -> Optional[int]:
    try:
        s = str(text)
    except Exception:
        return None
    for y in candidates:
        if str(y) in s:
            return y
    return None

def _score_candidate(url: str, title: Optional[str], keywords: List[str], year: Optional[int]) -> float:
    score = 0.0
    u = (url or "").lower()
    t = (title or "").lower()
    if year and str(year) in u:
        score += 1.2
    if year and str(year) in t:
        score += 0.8
    for kw in keywords:
        kw_l = kw.lower()
        if kw_l and kw_l in u:
            score += 0.6
        if kw_l and kw_l in t:
            score += 0.4
    boost_terms = ("bilanci", "relazioni", "investor", "financial", "sostenibilit")
    if any(bt in u for bt in boost_terms):
        score += 0.5
    if _is_pdf_url(u):
        score += 0.4
    return round(score, 3)

def _is_allowed(url: str, allowlist: List[str]) -> bool:
    host = _get_host(url).lower()
    if not host:
        return False
    for item in allowlist:
        item = item.lower()
        if host == item or host.endswith("." + item):
            return True
    return False

def crawl_and_classify(
    seed_url: str,
    keywords: List[str],
    year: int,
    depth: int = 1,
    max_pages: int = 20,
    allowlist: Optional[List[str]] = None,
    polite_mode: bool = True,
    min_delay: float = 1.0,
) -> List[Dict[str, Any]]:
    if _CRAWLER_IMPORTED:
        try:
            return _external_crawl_and_classify(
                seed_url=seed_url,
                keywords=keywords,
                year=year,
                depth=depth,
                max_pages=max_pages,
                allowlist=allowlist,
                polite_mode=polite_mode,
                min_delay=min_delay,
            )
        except TypeError:
            return _external_crawl_and_classify(
                seed_url=seed_url,
                keywords=keywords,
                year=year,
                depth=depth,
                max_pages=max_pages,
                allowlist=allowlist,
            )
    results: List[Dict[str, Any]] = []
    if httpx is None or BeautifulSoup is None:
        return results

    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    visited: Set[str] = set()
    q = deque([(seed_url, 0, None)])  # (url, depth, source)
    pages_processed = 0
    allow = allowlist or [_get_host(seed_url).lower()] if seed_url else []
    with httpx.Client(follow_redirects=True, headers=headers, timeout=15.0) as client:
        global _last_request_time
        _last_request_time = {}
        while q and pages_processed < max_pages:
            url, d, source = q.popleft()
            if url in visited:
                continue
            visited.add(url)
            if not _is_allowed(url, [h.lower() for h in allow]):
                continue
            if polite_mode and not allowed_by_robots(url, DEFAULT_UA):
                continue
            try:
                if polite_mode:
                    r = polite_get(client, url, min_delay=min_delay)
                else:
                    r = client.get(url)
            except Exception:
                continue
            ctype = r.headers.get("content-type", "").lower()
            if _is_pdf_url(url) or "application/pdf" in ctype:
                title = url.split("/")[-1]
                ydet = _year_from_text(url) or _year_from_text(title)
                matched = [kw for kw in keywords if kw.lower() in url.lower()]
                score = _score_candidate(url, title, keywords, year)
                results.append({
                    "url": url,
                    "title": title,
                    "is_pdf": True,
                    "host": _get_host(url),
                    "score": score,
                    "year_detected": ydet,
                    "matched_keywords": matched,
                    "source_page": source,
                })
                continue
            if "text/html" not in ctype:
                continue
            pages_processed += 1
            try:
                soup = BeautifulSoup(r.text, "html.parser")
            except Exception:
                continue
            page_title = None
            t_tag = soup.find("title")
            if t_tag and t_tag.text:
                page_title = t_tag.text.strip()
            ydet = _year_from_text(url) or _year_from_text(page_title)
            s = _score_candidate(url, page_title, keywords, year)
            if s >= 1.0:
                matched = [kw for kw in keywords if (kw.lower() in (url.lower() + " " + (page_title or "").lower()))]
                results.append({
                    "url": url,
                    "title": page_title,
                    "is_pdf": False,
                    "host": _get_host(url),
                    "score": s,
                    "year_detected": ydet,
                    "matched_keywords": matched,
                    "source_page": source,
                })
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                try:
                    nxt = urljoin(url, href)
                except Exception:
                    continue
                if not nxt:
                    continue
                if nxt.startswith("mailto:") or nxt.startswith("tel:"):
                    continue
                if not nxt.startswith("http"):
                    continue
                if nxt in visited:
                    continue
                if not _is_allowed(nxt, [h.lower() for h in allow]):
                    continue
                if d < depth:
                    q.append((nxt, d + 1, url))
    best_by_url: Dict[str, Dict[str, Any]] = {}
    for rec in results:
        u = rec["url"]
        prev = best_by_url.get(u)
        if prev is None or rec.get("score", 0) > prev.get("score", 0):
            best_by_url[u] = rec
    final = list(best_by_url.values())
    final.sort(key=lambda r: (r.get("score", 0.0), 1 if not r.get("is_pdf") else 2), reverse=True)
    return final


# --------------------------------------------
# UI
# --------------------------------------------
st.title(APP_TITLE)
st.caption(f"Versione {APP_VERSION}")

with st.sidebar:
    st.markdown("### Stato dipendenze")
    if _CRAWLER_IMPORTED:
        st.success("Modulo esterno `semantic_crawler` rilevato ✅")
    else:
        st.info("Uso **fallback crawler** interno")

    missing = []
    if httpx is None:
        missing.append("httpx")
    if BeautifulSoup is None:
        missing.append("beautifulsoup4")
    if pdfplumber is None and PdfReader is None:
        missing.append("pdfplumber or PyPDF2 for PDF text extraction")
    if pytesseract is None or convert_from_bytes is None:
        # OCR libs optional: inform user if not installed
        missing.append("pytesseract and pdf2image (for OCR) - requires system packages")
    if missing:
        st.error("Mancano dipendenze: **" + ", ".join(missing) + "**")

    st.divider()
    st.markdown("**Suggerimento**: usa come seed la pagina *Bilanci e DNF* o *Investor Relations*.")


# ==============================
# 🔎 CRAWLER SEMANTICO – ESTRA (scan singolo)
# ==============================
with st.expander("🔎 Crawler semantico – Estra (scan singolo)", expanded=False):
    st.markdown("Configura i parametri e lancia la scansione per *Bilanci e DNF*.")

    # --- Parametri base ---
    col1, col2 = st.columns([2, 1])
    with col1:
        seed_url = st.text_input(
            "Seed URL (es. pagina Bilanci/Investor Relations)",
            value="https://www.estra.it/bilanci-relazioni",
            placeholder="https://www.esempio.it/bilanci-relazioni"
        )
    with col2:
        anno_target = st.selectbox("Anno target", options=[2025, 2024, 2023], index=1)

    keywords_default = [
        "bilancio d'esercizio",
        "bilancio consolidato",
        "relazione finanziaria annuale",
        "relazione sulla gestione",
        "nota integrativa",
        "DNF",
        "bilanci",
        "relazioni",
        "investor",
    ]
    keywords_raw = st.text_area(
        "Parole chiave (una per riga) per identificare il documento (scan singolo)",
        value="\n".join(keywords_default),
        height=140,
        help="Verranno cercate nel titolo/percorso del PDF e nel contesto della pagina."
    )
    keywords = [k.strip() for k in keywords_raw.splitlines() if k.strip()]

    # --- Parametri crawler ---
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        depth_max = st.number_input("Profondità max", min_value=1, max_value=6, value=1, step=1)
    with c2:
        pages_max = st.number_input("Pagine max", min_value=5, max_value=500, value=20, step=5)
    with c3:
        allowlist_raw = st.text_input(
            "Domini/host consentiti (separati da virgola)",
            value="www.estra.it, estra.it, cdn.estra.it",
            help="Se vuoto, si usa il dominio della seed. I sottodomini sono ammessi automaticamente."
        )
    allowlist = [h.strip() for h in allowlist_raw.split(",") if h.strip()]

    fmt = st.radio("Formato esportazione", ["CSV", "JSON"], horizontal=True, index=0)

    run = st.button("▶️ Avvia crawler semantico (singolo)", type="primary")
    status = st.empty()

    if run:
        if not seed_url or not seed_url.startswith("http"):
            st.error("Inserisci una Seed URL valida (deve iniziare con http/https).")
            st.stop()
        if not keywords:
            st.error("Inserisci almeno una parola chiave.")
            st.stop()
        status.info("In esecuzione… può richiedere alcuni minuti su siti complessi.")
        try:
            results = crawl_and_classify(
                seed_url=seed_url,
                keywords=keywords,
                year=int(anno_target),
                depth=int(depth_max),
                max_pages=int(pages_max),
                allowlist=allowlist if allowlist else None,
                polite_mode=True,
                min_delay=1.0,
            )
            if not results:
                status.warning("Nessun risultato utile trovato. Prova ad aumentare Profondità/Pagine o variare le keywords.")
            else:
                df = pd.DataFrame(results)
                if "score" in df.columns:
                    df = df.sort_values(by="score", ascending=False)
                st.subheader("Risultati")
                st.dataframe(df, use_container_width=True, hide_index=True)
                if fmt == "CSV":
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    st.download_button("⬇️ Scarica risultati (CSV)", data=csv_bytes, file_name=f"crawler_estra_{anno_target}.csv", mime="text/csv")
                else:
                    json_bytes = df.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
                    st.download_button("⬇️ Scarica risultati (JSON)", data=json_bytes, file_name=f"crawler_estra_{anno_target}.json", mime="application/json")
                status.success("Crawler completato ✅")
        except Exception as e:
            status.error(f"Errore durante l’esecuzione del crawler: {e}")


# ==============================
# Batch processing: Excel -> ricerca automatica -> estrazione valori (con OCR)
# ==============================
with st.expander("📁 Batch: carica Excel e processa elenco aziende", expanded=True):
    st.markdown(
        """
Carica un file Excel (.xlsx) con una colonna che contiene il NOME azienda (colonna chiamata idealmente 'name' o 'azienda').
Per ogni riga: il sistema esegue una query Google Custom Search del tipo `Nome Azienda bilancio <anno>` e cerca il PDF rilevante, quindi estrae il valore vicino alla keyword indicata.
"""
    )

    st.markdown("### 1) Carica file Excel")
    uploaded = st.file_uploader("Carica il tuo file .xlsx (nome azienda in colonna 'name' o 'azienda')", type=["xlsx"])

    st.markdown("### 2) Configura ricerca")
    ex_col_name = st.text_input("Nome colonna con il nome azienda", value="name", help="Inserisci esatto nome della colonna nel tuo Excel che contiene il nome dell'azienda")
    year_for_search = st.number_input("Anno documento (es. 2024)", min_value=2000, max_value=2100, value=2024)
    serp_results = st.number_input("Risultati SERP da interrogare per azienda", min_value=1, max_value=10, value=3)
    doc_keywords_raw = st.text_area("Parole chiave per identificare il documento (una per riga)", value="\n".join(["bilancio", "relazione finanziaria", "bilanci", "nota integrativa"]), height=120)
    doc_keywords = [k.strip() for k in doc_keywords_raw.splitlines() if k.strip()]
    extract_keywords_raw = st.text_area("Parole chiave da cercare nel documento per trovare il valore (una per riga)", value="somministrati\ninterinali\nlavoratori non dipendenti", height=120)
    extract_keywords = [k.strip() for k in extract_keywords_raw.splitlines() if k.strip()]

    st.markdown("### 3) Opzioni politeness e limiti")
    polite_mode_batch = st.checkbox("Modalità gentile (rispetta robots.txt e delay)", value=True)
    min_delay_batch = st.slider("Delay minimo (s) tra richieste allo stesso host", min_value=0.2, max_value=5.0, value=1.0, step=0.1)
    max_companies = st.number_input("Numero massimo di aziende da processare in questo run", min_value=1, max_value=1000, value=20, step=1)
    run_batch = st.button("▶️ Processa elenco e genera Excel aggiornato")

    # carica config google dal file streamlit/config.toml se presente
    search_cfg = load_search_config()
    api_key = search_cfg.get("api_key")
    cx = search_cfg.get("cx")
    if not api_key or not cx:
        st.warning("Google Custom Search API key o CX non trovati in streamlit/config.toml. Inseriscili o verifica il file. Senza questi il batch non può cercare automaticamente i risultati SERP.")
    else:
        st.info("Google Custom Search configurato (usa valori in streamlit/config.toml). Quota giornaliera: ricorda il limite di query.")

    if run_batch:
        if uploaded is None:
            st.error("Carica prima il file Excel.")
            st.stop()
        try:
            df_in = pd.read_excel(uploaded)
        except Exception as e:
            st.error(f"Impossibile leggere il file Excel: {e}")
            st.stop()
        if ex_col_name not in df_in.columns:
            st.error(f"Colonna '{ex_col_name}' non trovata nel file Excel. Colonne disponibili: {', '.join(df_in.columns.astype(str))}")
            st.stop()
        # Limita il numero di righe processate in questo run
        df_proc = df_in.copy()
        n_rows = min(int(max_companies), len(df_proc))
        st.info(f"Avvio processamento su {n_rows} aziende (limite impostato).")
        progress = st.progress(0)
        status_text = st.empty()

        # Prepara colonne di output
        out_cols = {
            "found_document_url": [],
            "matched_doc_keyword": [],
            "matched_value": [],
            "needs_ocr": [],
            "notes": []
        }
        for c in out_cols.keys():
            if c not in df_proc.columns:
                df_proc[c] = ""

        queries_used = 0

        for i in range(n_rows):
            row_name = str(df_proc.iloc[i][ex_col_name])
            status_text.info(f"({i+1}/{n_rows}) Processing: {row_name}")
            best_doc_url = None
            best_doc_score = -1.0
            matched_keyword = None
            matched_value = None
            needs_ocr_flag = False
            notes = ""

            # 1) Search via Google CSE
            query = f"{row_name} bilancio {int(year_for_search)}"
            serp_items = []
            if api_key and cx:
                serp_items = search_google_cse(query, api_key, cx, num=int(serp_results))
                queries_used += 1
            else:
                notes = "No Google API key; nessuna ricerca SERP automatica eseguita."

            candidate_urls = []
            for it in serp_items:
                link = it.get("link")
                if link:
                    candidate_urls.append(link)

            # 2) Per ogni candidate url, usa crawl_and_classify per trovare PDF rilevanti
            found = False
            for link in candidate_urls:
                status_text.info(f"  -> scanning candidate {link}")
                try:
                    results = crawl_and_classify(
                        seed_url=link,
                        keywords=doc_keywords,
                        year=int(year_for_search),
                        depth=1,
                        max_pages=20,
                        allowlist=None,
                        polite_mode=polite_mode_batch,
                        min_delay=min_delay_batch,
                    )
                except Exception:
                    results = []
                for r in results:
                    if r.get("is_pdf"):
                        score = r.get("score", 0.0)
                        if score > best_doc_score:
                            best_doc_score = score
                            best_doc_url = r.get("url")
                if best_doc_url:
                    found = True

            # 3) Se non trovato tramite crawl, verifica direttamente i candidate_urls se contengono pdf
            if not best_doc_url:
                for link in candidate_urls:
                    if _is_pdf_url(link):
                        best_doc_url = link
                        found = True
                        break

            # 4) Se trovato documento PDF, scarica ed estrai testo (con fallback OCR)
            if best_doc_url:
                status_text.info(f"  -> scarico documento {best_doc_url}")
                data = download_binary(best_doc_url)
                if data:
                    text, needs_ocr_flag = extract_text_from_pdf_bytes(data)
                    # se non estrae testo, prova OCR se possibile
                    if needs_ocr_flag and pytesseract is not None and convert_from_bytes is not None:
                        status_text.info("  -> OCR in corso (pytesseract)...")
                        try:
                            ocr_text = ocr_pdf_bytes(data, dpi=200, lang="ita")
                            if ocr_text and ocr_text.strip():
                                text = ocr_text
                                needs_ocr_flag = False
                        except Exception:
                            pass
                    if not needs_ocr_flag and text:
                        kw, val = find_value_near_keywords(text, extract_keywords)
                        matched_keyword = kw
                        matched_value = val
                        if not kw:
                            notes = "Nessuna keyword trovata nel testo"
                    else:
                        needs_ocr_flag = True
                        if not notes:
                            notes = "Documento probabilmente scannerizzato o testo non estraibile (needs OCR)"
                else:
                    notes = "Download documento fallito"
            else:
                notes = "Nessun documento PDF trovato dai risultati SERP"

            # scrivi risultati nella riga
            df_proc.at[df_proc.index[i], "found_document_url"] = best_doc_url or ""
            df_proc.at[df_proc.index[i], "matched_doc_keyword"] = matched_keyword or ""
            df_proc.at[df_proc.index[i], "matched_value"] = matched_value or ""
            df_proc.at[df_proc.index[i], "needs_ocr"] = bool(needs_ocr_flag)
            df_proc.at[df_proc.index[i], "notes"] = notes or ""

            progress.progress(int(((i+1)/n_rows)*100))
            time.sleep(0.25)

        status_text.success("Elaborazione completata.")
        st.dataframe(df_proc.head(200), use_container_width=True)

        # Download Excel aggiornato
        out_buffer = io.BytesIO()
        try:
            df_proc.to_excel(out_buffer, index=False)
            out_buffer.seek(0)
            st.download_button("⬇️ Scarica Excel aggiornato", data=out_buffer, file_name=f"risultati_crawl_{year_for_search}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(f"Errore generazione Excel: {e}")

        st.info(f"Query SERP effettuate in questo run: {queries_used} (quota giornaliera da monitorare!)")


# --------------------------------------------
# (Opzionale) Informazioni / Note
# --------------------------------------------
with st.expander("ℹ️ Informazioni / Note"):
    st.markdown(
        """
- Questa app utilizza Google Custom Search API per ottenere i primi link SERP; assicurati di avere inserito la API key e CX in streamlit/config.toml o nei Secrets di Streamlit.
- Per PDF testuali viene usato pdfplumber o PyPDF2 per estrarre testo; per PDF scannerizzati viene usato pytesseract+pdf2image (OCR). OCR richiede pacchetti di sistema: `tesseract-ocr` e `poppler-utils`.
- Mantieni la Modalità Gentile attiva per evitare blocchi (robots.txt e delay).
- Per grandi volumi considera caching delle SERP e esecuzione in batch più piccoli.
        """
    )
