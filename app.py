import streamlit as st
import requests
import pytesseract
from PIL import Image
from io import BytesIO
from pdf2image import convert_from_bytes

# Funzione per costruire la query di ricerca
def costruisci_query(nome_azienda, anno, parole_aggiuntive):
    parole_base = ["bilancio", "bilancio consolidato", "bilancio intermedio al", "financial statement"]
    if parole_aggiuntive:
        parole_extra = []
        for p in parole_aggiuntive.split(','):
            p = p.strip()
            if p:
                if p.startswith('"') and p.endswith('"'):
                    parole_extra.append(p.strip('"'))
                else:
                    parole_extra.append(p)
        parole_base.extend(parole_extra)
    query = " OR ".join([f'"{p}"' for p in parole_base])
    return f"site:{nome_azienda}.com filetype:pdf ({query}) {anno}"

# Funzione per cercare il PDF del bilancio usando Google Custom Search API
def cerca_pdf_bilancio(query, api_key, cx):
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={api_key}&cx={cx}"
    response = requests.get(url)
    if response.status_code == 200:
        results = response.json().get("items", [])
        for item in results:
            link = item.get("link", "")
            if link.endswith(".pdf"):
                return link
    return None

# Funzione per scaricare e convertire PDF in immagini
def estrai_testo_da_pdf(pdf_url):
    response = requests.get(pdf_url)
    if response.status_code == 200:
        images = convert_from_bytes(response.content)
        testo_completo = ""
        for img in images:
            testo = pytesseract.image_to_string(img, lang='eng')
            testo_completo += testo + "\n"
        return testo_completo
    return ""

# Interfaccia Streamlit
st.title("Analisi Bilanci Aziendali")

nome_azienda = st.text_input("Nome azienda (es. ferrari)")
anno = st.selectbox("Anno di bilancio", list(range(2010, 2029)))
parole_chiave = st.text_area("Parole chiave da cercare nel documento (una per riga)")
parole_aggiuntive = st.text_input("Parole aggiuntive per la ricerca del PDF (separate da virgole, opzionale)")
api_key = st.text_input("Google API Key")
cx = st.text_input("Google Custom Search CX")

if st.button("Avvia ricerca"):
    if nome_azienda and parole_chiave and api_key and cx:
        st.info("Ricerca del bilancio in corso...")
        query = costruisci_query(nome_azienda, anno, parole_aggiuntive)
        pdf_url = cerca_pdf_bilancio(query, api_key, cx)
        if pdf_url:
            st.success(f"Bilancio trovato: {pdf_url}")
            testo = estrai_testo_da_pdf(pdf_url)
            risultati = []
            for parola in parole_chiave.splitlines():
                trovato = parola in testo
                risultati.append({"Parola chiave": parola, "Presente": "✅" if trovato else "❌"})
            st.write("### Risultati")
            st.table(risultati)
        else:
            st.error("Nessun PDF trovato per il bilancio indicato.")
    else:
        st.warning("Compila tutti i campi obbligatori per procedere.")
