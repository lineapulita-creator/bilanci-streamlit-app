from __future__ import annotations
import re
from urllib.parse import urlencode
import httpx

def normalize_company(name: str) -> str:
    noise = [
        r"\bs\.?p\.?a\.?\b", r"\bs\.?r\.?l\.?\b",
        r"\bsociet[aà] (per azioni|a responsabilit[aà] limitata)\b",
        r"\bunipersonale\b", r"\ba socio unico\b", r"\bin liquidazione\b", r"\bholding\b"
    ]
    s = name
    for pat in noise:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _google_cse_search(q: str, api_key: str, cx: str, num=10, gl="it", hl="it", lr="lang_it") -> dict:
    params = {"key": api_key, "cx": cx, "q": q, "num": num, "gl": gl, "hl": hl, "lr": lr, "safe": "off"}
    url = "https://www.googleapis.com/customsearch/v1?" + urlencode(params)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        r = client.get(url); r.raise_for_status()
        return r.json()

def build_entrypoint_queries(company: str, year: int) -> list[str]:
    core = normalize_company(company)
    return [
        f'"{core}" (investor OR "investor relations" OR investitori OR bilanci OR relazioni) site:.it',
        f'"{core}" {year} (bilanci OR relazioni OR "financial statements" OR "annual report") site:.it',
        f'"{core}" (amministrazione trasparente OR trasparenza) {year} site:.it',
    ]

def pick_entrypoints(company: str, year: int, api_key: str, cx: str, max_sites=5) -> list[str]:
    queries = build_entrypoint_queries(company, year)
    entry, seen_domains = [], set()
    for q in queries:
        data = _google_cse_search(q, api_key, cx)
        for it in data.get("items", []):
            link = it.get("link", "")
            if not link or link.lower().endswith(".pdf"):
                continue
            if any(k in link.lower() for k in [
                "investor", "investitori", "relazioni", "bilanci",
                "financial", "report", "amministrazione-trasparente"
            ]):
                dom = re.sub(r"^https?://", "", link).split("/")[0]
                if dom not in seen_domains:
                    seen_domains.add(dom); entry.append(link)
            if len(entry) >= max_sites: break
        if len(entry) >= max_sites: break
    return entry
