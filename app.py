import streamlit as st
import pandas as pd
import requests
import io
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes

# API Key e CX forniti da Matteo
API_KEY = "AIzaSyD9vUeUeJEXAMPLEKEY"
CX = "cse-matteo-123456"

st.set_page_config(page_title="Ricerca Bilanci Aziendali", layout="centered")
st.title("Ricerca Bilanci Aziendali")

uploaded_file = st.file_uploader("Carica il file Excel con Ragione Sociale, P.IVA e Gruppo", type=["xlsx"])
anno_esercizio = st.selectbox("Seleziona l'anno di esercizio", options=[str(a) for a in range(2015, 2026)])
parole_chiave = st.text_input("Inserisci parole chiave per la ricerca (separate da virgola)")
parole_opzionali = st.text_input("Parole opzionali (non obbligatorie) nella ricerca (separate da virgola)")

if st.button("Avvia Ricerca"):
    if uploaded_file is None:
        st.error("Devi caricare un file Excel prima di procedere.")
    elif parole_chiave.strip() == "":
        st.error("Inserisci almeno una parola chiave per la ricerca.")
    else:
        df = pd.read_excel(uploaded_file, engine="openpyxl")
        risultati = []

        for index, row in df.iterrows():
            ragione_sociale = str(row.get("Ragione Sociale", ""))
            partita_iva = str(row.get("P.IVA", ""))
            gruppo = str(row.get("Gruppo", ""))

            query = f"{ragione_sociale} bilancio {anno_esercizio} {parole_chiave}"
            if parole_opzionali.strip():
                query += f" {parole_opzionali}"
            query += " filetype:pdf"

            url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={API_KEY}&cx={CX}"

            try:
                search_response = requests.get(url)
                results = search_response.json().get("items", [])
                pdf_url = None
                for item in results:
                    link = item.get("link", "")
                    if link.lower().endswith(".pdf"):
                        pdf_url = link
                        break

                if pdf_url:
                    pdf_response = requests.get(pdf_url)
                    if pdf_response.status_code == 200:
                        images = convert_from_bytes(pdf_response.content)
                        testo_estratto = ""
                        for img in images:
                            ocr_result = pytesseract.image_to_string(img, config="--psm 6")
                            testo_estratto += ocr_result + "\n"

                        if "stato patrimoniale" in testo_estratto.lower():
                            risultati.append("Bilancio trovato e analizzato")
                        else:
                            risultati.append("PDF trovato ma dati non rilevabili")
                    else:
                        risultati.append("PDF non scaricabile")
                else:
                    risultati.append("Nessun PDF trovato")
            except Exception as e:
                risultati.append(f"Errore: {str(e)}")

        df["Risultato Ricerca"] = risultati
        output_path = "risultati_bilanci.xlsx"
        df.to_excel(output_path, index=False)
        st.success("Ricerca completata. File aggiornato pronto per il download.")
        with open(output_path, "rb") as f:
            st.download_button("Scarica file aggiornato", f, file_name=output_path)
