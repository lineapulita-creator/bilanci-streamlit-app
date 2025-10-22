import streamlit as st
from crawler import crawl_for_pdf
import httpx
from bs4 import BeautifulSoup

st.set_page_config(page_title="Test Crawler (Seed only)", page_icon="🧭", layout="centered")
st.title("🧭 Test Crawler (solo seed, senza CSE)")
st.caption("Inserisci direttamente l'URL della pagina 'Bilanci e relazioni' / 'Investor Relations' dell'anno.")

with st.form("params"):
    seed = st.text_input("URL seed", value="https://corporate.estra.it/bilanci-relazioni/2023")
    year = st.number_input("Anno", min_value=2005, max_value=2028, value=2023, step=1)
    max_depth = st.slider("Profondità massima", 1, 6, 4)
    max_pages = st.slider("Pagine max da visitare", 10, 120, 50, step=10)
    debug = st.toggle("Mostra primo HTML e primi 20 link estratti", value=False)
    go = st.form_submit_button("Cerca PDF")

if go:
    if not seed.strip():
        st.error("Inserisci un URL seed."); st.stop()

    # Debug: controlla che la pagina seed sia raggiungibile e contenga link
    if debug:
        try:
            r = httpx.get(seed.strip(), timeout=30, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (compatible; BilanciCrawler/1.0)"
            })
            st.write("GET seed:", r.status_code, r.headers.get("content-type"))
            if "text/html" in r.headers.get("content-type", "") and r.text:
                soup = BeautifulSoup(r.text, "html.parser")
                links = []
                for i, a in enumerate(soup.find_all("a", href=True)):
                    if i >= 20: break
                    links.append((a.get("href"), a.get_text(" ", strip=True)))
                st.write("Primi 20 link trovati sulla seed:", links)
        except Exception as e:
            st.error(f"Errore fetch seed: {e}")

    with st.spinner("Navigo nel dominio alla ricerca del PDF…"):
        res = crawl_for_pdf([seed.strip()], int(year), max_pages=max_pages, max_depth=max_depth)

    if res.get("pdf"):
        st.success(f"✅ PDF trovato ({res['score']:.2f}) via {res['via']} — pagine visitate: {res['visited']}")
        st.code(res["pdf"], language="text")
        st.caption("Copia l'URL: puoi usarlo nel tuo flusso OCR/Excel.")
    else:
        st.warning(f"⚠️ Nessun PDF trovato entro i limiti (visitato: {res.get('visited')}).")
        st.caption("Suggerimenti: usa un seed più specifico (pagina 'Bilanci e relazioni' dell'anno) o aumenta profondità/pagine.")
