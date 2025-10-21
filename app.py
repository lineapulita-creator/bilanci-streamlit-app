# [IMPORTS E CONFIGURAZIONE]
import streamlit as st
import pandas as pd
import requests
import io
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes
import re
from bs4 import BeautifulSoup

API_KEY = "AIzaSyD9vUeUeJEXAMPLEKEY"
CX = "cse-matteo-123456"

st.set_page_config(page_title="Ricerca Bilanci Aziendali", layout="centered")
st.title("Ricerca Bilanci Aziendali")

# [INPUT UTENTE]
uploaded_file = st.file_uploader("Carica il file Excel con Legal Entity Name e Parent/Group Company", type=["xlsx"])
anno_esercizio = st.selectbox("Seleziona l'anno di esercizio", options=[str(a) for a in range(2015, 2026)])
parole_chiave = st.text_area("Parole chiave obbligatorie (una per riga)")
parole_opzionali = st.text_area("Parole opzionali (una per riga)")

# [FUNZIONI DI SUPPORTO]
def pulisci_nome(nome):
    return re.sub(r"[^a-zA-Z0-9 ]", "", nome).strip()

def trova_pdf_in_html(url):
    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        return [a.get("href") for a in soup.find_all("a") if a.get("href") and ".pdf" in a.get("href").lower()]
    except:
        return []

def analizza_pdf_con_ocr(pdf_url, tutte_le_parole):
    try:
        pdf_resp = requests.get(pdf_url)
        if pdf_resp.status_code == 200:
            images = convert_from_bytes(pdf_resp.content)
            testo = ""
            for img in images:
                testo += pytesseract.image_to_string(img, config="--psm 6") + "\n"
            if all(k.lower() in testo.lower() for k in tutte_le_parole):
                return "Bilancio trovato e analizzato"
            else:
                return "PDF trovato ma parole non rilevate"
        else:
            return "PDF non scaricabile"
    except:
        return "Errore durante il download PDF"

# [LOGICA PRINCIPALE]
if uploaded_file:
    df = pd.read_excel(uploaded_file, engine="openpyxl")
    st.subheader("Anteprima del file caricato")
    st.dataframe(df.head())

if st.button("Avvia Ricerca"):
    if uploaded_file is None or parole_chiave.strip() == "":
        st.error("Carica un file Excel e inserisci almeno una parola chiave obbligatoria.")
    else:
        chiavi = [x.strip() for x in parole_chiave.split("\n") if x.strip()]
        opzionali = [x.strip() for x in parole_opzionali.split("\n") if x.strip()]
        tutte_le_parole = chiavi + opzionali
        risultati, query_finali, link_finali = [], [], []

        for _, row in df.iterrows():
            gruppo = pulisci_nome(str(row.get("Parent/Group Company", "")))
            query = f"{gruppo} bilancio {anno_esercizio}"
            url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={API_KEY}&cx={CX}"
            query_usata, pdf_link, risultato = query, "Nessun link disponibile", "Nessun PDF rilevante trovato"

            try:
                resp = requests.get(url)
                items = resp.json().get("items", [])
                for item in items:
                    pagina_url = item.get("link")
                    pdf_links = trova_pdf_in_html(pagina_url)
                    for pdf_url in pdf_links:
                        risultato = analizza_pdf_con_ocr(pdf_url, tutte_le_parole)
                        if risultato == "Bilancio trovato e analizzato":
                            pdf_link = pdf_url
                            break
                    if risultato == "Bilancio trovato e analizzato":
                        break
            except Exception as e:
                risultato = f"Errore: {str(e)}"
                pdf_link = "Errore durante la ricerca"

            risultati.append(risultato)
            query_finali.append(query_usata)
            link_finali.append(pdf_link)

        df["Risultato Ricerca"] = risultati
        df["Query Usata"] = query_finali
        df["Link Trovato"] = link_finali

        st.subheader("Anteprima dei risultati")
        st.dataframe(df[["Legal Entity Name", "Parent/Group Company", "Risultato Ricerca", "Query Usata", "Link Trovato"]])

        output_path = "risultati_bilanci.xlsx"
        df.to_excel(output_path, index=False)
        st.success("Ricerca completata. File aggiornato pronto per il download.")
        with open(output_path, "rb") as f:
            st.download_button("Scarica file aggiornato", f, file_name=output_path)
