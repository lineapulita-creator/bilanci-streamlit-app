
import streamlit as st
import pandas as pd
import requests
import fitz  # PyMuPDF
import pytesseract
from pdf2image import convert_from_path
import os
from PIL import Image

API_KEY = "AIzaSyDM2R4GN2NsxKXAKAk-wjq87yB0YgJeSQj4"
CX_CODE = "869644a1dedc5462c"

st.set_page_config(page_title="Analisi Bilanci Aziendali", layout="wide")
st.title("Analisi automatica dei bilanci aziendali")

uploaded_file = st.file_uploader("Carica il file Excel con le aziende", type=["xlsx"])

if uploaded_file:
    df = pd.read_excel(uploaded_file, engine="openpyxl")
    st.success("File caricato correttamente. Ecco un'anteprima:")
    st.dataframe(df)

    anno = st.selectbox("Seleziona l'anno di bilancio da cercare", options=["2022", "2021", "2020", "2019"])
    parole_chiave = st.text_area("Inserisci le parole chiave da cercare nel bilancio (separate da virgola)")
    parole_chiave = [p.strip().lower() for p in parole_chiave.split(",") if p.strip()]

    if st.button("Avvia analisi"):
        risultati = []
        for index, row in df.iterrows():
            ragione_sociale = str(row.get("Ragione Sociale", ""))
            partita_iva = str(row.get("P.IVA", ""))
            gruppo = str(row.get("Gruppo", ""))
            esito = ""
            parole_trovate = ""
            note = ""
            try:
                query = f"{ragione_sociale} bilancio {anno} filetype:pdf"
                search_url = "https://www.googleapis.com/customsearch/v1"
                params = {"key": API_KEY, "cx": CX_CODE, "q": query}
                response = requests.get(search_url, params=params)
                data = response.json()
                link_pdf = None
                for item in data.get("items", []):
                    link = item.get("link", "")
                    if link.lower().endswith(".pdf"):
                        link_pdf = link
                        break
                if link_pdf:
                    pdf_path = f"temp_{index}.pdf"
                    pdf_response = requests.get(link_pdf)
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_response.content)
                    immagini = convert_from_path(pdf_path)
                    testo_estratto = ""
                    for img in immagini:
                        testo_estratto += pytesseract.image_to_string(img)
                    testo_estratto = testo_estratto.lower()
                    trovate = [p for p in parole_chiave if p in testo_estratto]
                    esito = "Bilancio trovato"
                    parole_trovate = ", ".join(trovate) if trovate else "Nessuna parola chiave trovata"
                    note = link_pdf
                    os.remove(pdf_path)
                else:
                    esito = "Bilancio non trovato"
                    note = "Nessun PDF trovato nei risultati di ricerca"
            except Exception as e:
                esito = "Errore"
                note = str(e)
            risultati.append({
                "Ragione Sociale": ragione_sociale,
                "P.IVA": partita_iva,
                "Gruppo": gruppo,
                "Esito Ricerca": esito,
                "Parole Chiave Trovate": parole_trovate,
                "Note": note
            })
        df_risultati = pd.DataFrame(risultati)
        st.success("Analisi completata. Ecco i risultati:")
        st.dataframe(df_risultati)
        output_file = "risultati_bilanci.xlsx"
        df_risultati.to_excel(output_file, index=False)
        with open(output_file, "rb") as f:
            st.download_button("Scarica risultati in Excel", data=f, file_name=output_file)
        os.remove(output_file)
