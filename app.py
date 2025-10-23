# app.py
# ============================================
# Streamlit App – Crawler semantico (Estra)
# Tutto-in-uno, pronto da incollare
# ============================================

import os
import re
import io
import json
import time
import math
import asyncio
from collections import deque
from urllib.parse import urljoin, urlparse
from typing import Optional, List, Dict, Any, Set

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


# --------------------------------------------
# Config generale
# --------------------------------------------
APP_TITLE = "Bilanci & DNF – Crawler semantico (Estra)"
APP_VERSION = "1.0.0"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

st.set_page_config(page_title=APP_TITLE, page_icon="🔎", layout="wide")


# --------------------------------------------
# Utilità
# --------------------------------------------
def _dep_missing() -> List[str]:
    """Ritorna lista di dipendenze mancanti per il fallback crawler."""
    missing: List[str] = []
    if httpx is None:
        missing.append("httpx")
    if BeautifulSoup is None:
        missing.append("beautifulsoup4")
    return missing


def _netloc(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""


def _is_pdf_url(url: str) -> bool:
    u = url.lower()
    return u.endswith(".pdf") or "application/pdf" in u  # fallback rudimentale


def _year_from_text(text: str, candidates=(2022, 2023, 2024, 2025)) -> Optional[int]:
    try:
        s = str(text)
    except Exception:
        return None
    for y in candidates:
        if str(y) in s:
            return y
    return None


def _norm_allowlist(seed_url: str, allowlist: Optional[List[str]]) -> List[str]:
    if allowlist:
        return [h.strip().lower() for h in allowlist if h.strip()]
    # default: usa il dominio della seed
    base = _netloc(seed_url).lower()
    return [base] if base else []


def _is_allowed(url: str, allowlist: List[str]) -> bool:
    host = _netloc(url).lower()
    if not host:
        return False
    # Permetti sottodomini: host == item o host finisce con "." + item
    for item in allowlist:
        item = item.lower()
        if host == item or host.endswith("." + item):
            return True
    return False


def _score_candidate(url: str, title: Optional[str], keywords: List[str], year: Optional[int]) -> float:
    """Semplice scoring basato su URL+title."""
    score = 0.0
    u = (url or "").lower()
    t = (title or "").lower()

    # Anno
    if year and str(year) in u:
        score += 1.2
    if year and str(year) in t:
        score += 0.8

    # Keywords
    for kw in keywords:
        kw_l = kw.lower()
        if kw_l and kw_l in u:
            score += 0.6
        if kw_l and kw_l in t:
            score += 0.4

    # Boost se path contiene bilanci/relazioni/investor/financial
    boost_terms = ("bilanci", "relazioni", "investor", "financial", "sostenibilit")
    if any(bt in u for bt in boost_terms):
        score += 0.5
    # Bonus se è PDF
    if _is_pdf_url(u):
        score += 0.4

    return round(score, 3)


# --------------------------------------------
# Fallback: crawl_and_classify (SYNC)
# Viene usato solo se il modulo esterno non è disponibile.
# --------------------------------------------
def _fallback_crawl_and_classify(
    seed_url: str,
    keywords: List[str],
    year: int,
    depth: int = 2,
    max_pages: int = 80,
    allowlist: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Crawler sincrono semplice (httpx + bs4).
    Ritorna lista di dict:
    {
        "url": str,
        "title": str|None,
        "is_pdf": bool,
        "host": str,
        "score": float,
        "year_detected": int|None,
        "matched_keywords": list[str],
        "source_page": str|None
    }
    """
    if httpx is None or BeautifulSoup is None:
        raise RuntimeError(
            "Dipendenze mancanti per il fallback crawler. Aggiungi a requirements.txt:\n"
            "httpx\nbeautifulsoup4"
        )

    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    results: List[Dict[str, Any]] = []
    visited: Set[str] = set()
    q = deque([(seed_url, 0, None)])  # (url, depth, source)
    pages_processed = 0

    allow = _norm_allowlist(seed_url, allowlist)

    with httpx.Client(follow_redirects=True, headers=headers, timeout=15.0) as client:
        while q and pages_processed < max_pages:
            url, d, source = q.popleft()
            if url in visited:
                continue
            visited.add(url)

            # Filtra host
            if not _is_allowed(url, allow):
                continue

            try:
                r = client.get(url)
            except Exception:
                continue
            ctype = r.headers.get("content-type", "").lower()

            # --- PDF diretto ---
            if _is_pdf_url(url) or "application/pdf" in ctype:
                title = url.split("/")[-1]
                ydet = _year_from_text(url) or _year_from_text(title)
                matched = [kw for kw in keywords if kw.lower() in url.lower()]
                score = _score_candidate(url, title, keywords, year)
                results.append({
                    "url": url,
                    "title": title,
                    "is_pdf": True,
                    "host": _netloc(url),
                    "score": score,
                    "year_detected": ydet,
                    "matched_keywords": matched,
                    "source_page": source,
                })
                # non conta come "pagina html" processata
                continue

            # --- Solo HTML considerato come pagina processata ---
            if "text/html" not in ctype:
                # ignora risorse non html
                continue

            pages_processed += 1

            # Parse
            try:
                soup = BeautifulSoup(r.text, "html.parser")
            except Exception:
                continue

            page_title = None
            t_tag = soup.find("title")
            if t_tag and t_tag.text:
                page_title = t_tag.text.strip()

            # Se la pagina è molto rilevante, registrala (non PDF)
            # ma solo se ha qualche segnali (keywords/anno) nel titolo o URL
            ydet = _year_from_text(url) or _year_from_text(page_title)
            s = _score_candidate(url, page_title, keywords, year)
            if s >= 1.0:
                matched = [kw for kw in keywords if (kw.lower() in (url.lower() + " " + (page_title or "").lower()))]
                results.append({
                    "url": url,
                    "title": page_title,
                    "is_pdf": False,
                    "host": _netloc(url),
                    "score": s,
                    "year_detected": ydet,
                    "matched_keywords": matched,
                    "source_page": source,
                })

            # Estrai link
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                nxt = urljoin(url, href)
                # Filtri rapidi
                if nxt.startswith("mailto:") or nxt.startswith("tel:"):
                    continue
                if not nxt.startswith("http"):
                    continue
                if nxt in visited:
                    continue
                # Restringi crawling
                if not _is_allowed(nxt, allow):
                    continue

                # Inserisci in coda
                if d < depth:
                    q.append((nxt, d + 1, url))

    # Deduplica per URL, tieni il migliore score
    best_by_url: Dict[str, Dict[str, Any]] = {}
    for rec in results:
        u = rec["url"]
        prev = best_by_url.get(u)
        if prev is None or rec.get("score", 0) > prev.get("score", 0):
            best_by_url[u] = rec

    final = list(best_by_url.values())
    # Ordina per score desc, poi PDF first
    final.sort(key=lambda r: (r.get("score", 0.0), 1 if not r.get("is_pdf") else 2), reverse=True)
    return final


# --------------------------------------------
# Adapter: decidi quale crawl_and_classify usare
# --------------------------------------------
def crawl_and_classify(
    seed_url: str,
    keywords: List[str],
    year: int,
    depth: int = 2,
    max_pages: int = 80,
    allowlist: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Usa il modulo esterno se disponibile, altrimenti il fallback."""
    if _CRAWLER_IMPORTED:
        return _external_crawl_and_classify(
            seed_url=seed_url,
            keywords=keywords,
            year=year,
            depth=depth,
            max_pages=max_pages,
            allowlist=allowlist,
        )
    return _fallback_crawl_and_classify(
        seed_url=seed_url,
        keywords=keywords,
        year=year,
        depth=depth,
        max_pages=max_pages,
        allowlist=allowlist,
    )


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

    missing = _dep_missing()
    if missing:
        st.error(
            "Mancano dipendenze per il fallback: **" + ", ".join(missing) + "**\n\n"
            "Aggiungi in `requirements.txt`:\n\n"
            "```\n" + "\n".join(missing) + "\n```"
        )
    st.divider()
    st.markdown("**Suggerimento**: usa come seed la pagina *Bilanci e DNF* o *Investor Relations*.")

# ==============================
# 🔎 CRAWLER SEMANTICO – ESTRA
# ==============================
with st.expander("🔎 Crawler semantico – Estra", expanded=True):
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
        "Parole chiave (una per riga)",
        value="\n".join(keywords_default),
        height=140,
        help="Verranno cercate nel titolo/percorso del PDF e nel contesto della pagina."
    )
    keywords = [k.strip() for k in keywords_raw.splitlines() if k.strip()]

    # --- Parametri crawler ---
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        depth_max = st.number_input("Profondità max", min_value=1, max_value=6, value=2, step=1)
    with c2:
        pages_max = st.number_input("Pagine max", min_value=10, max_value=500, value=80, step=10)
    with c3:
        allowlist_raw = st.text_input(
            "Domini/host consentiti (separati da virgola)",
            value="www.estra.it, estra.it, cdn.estra.it",
            help="Se vuoto, si usa il dominio della seed. I sottodomini sono ammessi automaticamente."
        )
    allowlist = [h.strip() for h in allowlist_raw.split(",") if h.strip()]

    fmt = st.radio("Formato esportazione", ["CSV", "JSON"], horizontal=True, index=0)

    run = st.button("▶️ Avvia crawler semantico", type="primary")
    status = st.empty()

    if run:
        if not seed_url or not seed_url.startswith("http"):
            st.error("Inserisci una Seed URL valida (deve iniziare con http/https).")
            st.stop()

        if not keywords:
            st.error("Inserisci almeno una parola chiave.")
            st.stop()

        # Se mancano deps e non hai il modulo esterno, blocca con messaggio chiaro
        if not _CRAWLER_IMPORTED:
            missing = _dep_missing()
            if missing:
                st.error(
                    "Per eseguire il crawler interno mancano: **" + ", ".join(missing) + "**\n\n"
                    "Aggiungi in `requirements.txt`:\n\n"
                    "```\n" + "\n".join(missing) + "\n```"
                )
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
            )

            if not results:
                status.warning("Nessun risultato utile trovato. Prova ad aumentare Profondità/Pagine o variare le keywords.")
            else:
                df = pd.DataFrame(results)

                # Ordinamento per score se presente
                if "score" in df.columns:
                    df = df.sort_values(by="score", ascending=False)

                st.subheader("Risultati")
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Download
                if fmt == "CSV":
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="⬇️ Scarica risultati (CSV)",
                        data=csv_bytes,
                        file_name=f"crawler_estra_{anno_target}.csv",
                        mime="text/csv"
                    )
                else:
                    json_bytes = df.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
                    st.download_button(
                        label="⬇️ Scarica risultati (JSON)",
                        data=json_bytes,
                        file_name=f"crawler_estra_{anno_target}.json",
                        mime="application/json"
                    )

                # Suggerimenti dinamici
                tips = []
                if "host" in df.columns:
                    ext = sorted(set(
                        h for h in df["host"].astype(str)
                        if h and "estra.it" not in h
                    ))
                    if ext:
                        tips.append(
                            "Host esterni rilevati (valuta di aggiungerli alla allowlist): "
                            + "**" + ", ".join(ext[:8]) + (" …" if len(ext) > 8 else "") + "**"
                        )
                if "is_pdf" in df.columns and df["is_pdf"].sum() == 0:
                    tips.append("Nessun PDF diretto. Aumenta **Profondità** o verifica PDF su CDN esterni.")
                if tips:
                    st.info("Suggerimenti:\n\n- " + "\n- ".join(tips))

                status.success("Crawler completato ✅")

        except Exception as e:
            status.error(f"Errore durante l’esecuzione del crawler: {e}")


# --------------------------------------------
# (Opzionale) Placeholder per altre funzioni della tua app
# Puoi lasciare così se non ti servono.
# --------------------------------------------
with st.expander("ℹ️ Informazioni / Note"):
    st.markdown(
        """
- Questa sezione esegue un crawler semantico partendo da una **Seed URL** (consigliato: *Bilanci e DNF* o *Investor Relations*).
- Puoi limitare la navigazione ai **domini consentiti** per evitare di uscire dal perimetro.
- Il punteggio di rilevanza considera **anno**, **keywords**, presenza di **PDF** e path con *bilanci/relazioni/investor/financial*.
- Se possiedi un modulo esterno `semantic_crawler`, la funzione `crawl_and_classify` verrà usata automaticamente.
- In assenza del modulo esterno, è attivo un **fallback** integrato (httpx+bs4).
        """
    )
