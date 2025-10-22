# semantic_crawler/matchers.py
import re
from urllib.parse import urlparse

YEAR_RE = re.compile(r"\b(2023|2024)\b")
# Parole chiave principali
KW_BIL = [
    "bilancio", "bilancio d'esercizio", "relazione finanziaria annuale",
    "relazione sulla gestione", "nota integrativa", "financial statements", "annual report"
]
KW_CONS = ["consolidato", "gruppo", "consolidated"]
KW_SUS = ["bilancio di sostenibilita", "sostenibilita", "dichiarazione non finanziaria", "dnf", "sustainability", "esg"]

def normalize(txt: str) -> str:
    return (txt or "").lower().replace("à","a").replace("è","e").replace("é","e").replace("ì","i").replace("ò","o").replace("ù","u")

def is_pdf(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf")

def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()

def score_link(href: str, anchor_text: str, path_hint: str = "") -> int:
    """
    Restituisce uno score 0-100 in base a parole chiave/anno nel link o nel testo ancora.
    """
    h = normalize(href)
    a = normalize(anchor_text)
    p = normalize(path_hint)

    score = 0
    # Anno target
    if YEAR_RE.search(h) or YEAR_RE.search(a):
        score += 25

    # Bilancio / RFA
    if any(k in h or k in a for k in KW_BIL):
        score += 35

    # Consolidato
    if any(k in h or k in a for k in KW_CONS):
        score += 15

    # Sostenibilità / DNF
    if any(k in h or k in a for k in KW_SUS):
        score += 20

    # Percorso "bilanci", "relazioni", "investor", "financial"
    for k in ["bilanci", "relazioni", "investor", "financial"]:
        if k in h or k in p:
            score += 10
            break
    # Bonus se è PDF
    if is_pdf(href):
        score += 10

    return min(score, 100)

def classify(href: str, anchor_text: str, allow_hosts: list[str]) -> tuple[str, int]:
    """
    Ritorna (categoria, confidenza)
    """
    s = score_link(href, anchor_text)
    host = host_of(href)
    pdf = is_pdf(href)

    if pdf and host not in allow_hosts:
        # PDF su host esterno (potrebbe essere il target, ma segnaliamolo)
        if s >= 50:
            return ("host_esterno_pdf", min(90, s))
        return ("host_esterno_altro", min(60, s))

    # PDF con forte segnale bilancio anno
    if pdf and s >= 70:
        if any(k in normalize(href) for k in ["sostenibil", "dnf", "sustain"]):
            return ("pdf_sostenibilita_target", s)
        return ("pdf_bilancio_target", s)

    # PDF generici con parole chiave ma senza anno
    if pdf and s >= 50:
        return ("pdf_bilancio_generico", s)

    # Sezione utile
    if s >= 50:
        return ("section_bilanci", s)

    # Non rilevante
    return ("non_rilevante", s)
