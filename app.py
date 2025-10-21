import streamlit as st
import pandas as pd
import requests
import io
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes
import re

# API Key e CX forniti da Matteo
API_KEY = "AIzaSyD9vUeUeJEXAMPLEKEY"
CX = "cse-matteo-123456"

st.set_page_config(page_title="Ricerca Bilanci Aziendali", layout="centered")
st.title("Ricerca Bilanci Aziendali")

uploaded_file = st.file_uploader("Carica il file Excel con Legal Entity Name e Parent/Group Company", type=["xlsx"])
anno_esercizio = st.selectbox("Seleziona l'anno di esercizio", options=[str(a) for a in range(2015, 2026)])
parole_chiave = st.text_area("Parole chiave obbligatorie (una per riga)")
parole_opzionali = st.text_area("Parole opzionali (una per riga)")

# Funzione per pulire i nomi aziendali
def pulisci_nome(nome):
    nome = re.sub(r"[^a-zA-Z0-9 ]", "", nome)
    return nome.strip()

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
        risultati = []
        query_usate = []

        for _, row in df.iterrows():
            nome = pulisci_nome(str(row.get("Legal Entity Name", "")))
            gruppo = pulisci_nome(str(row.get("Parent/Group Company", "")))

            tentativi = []
            for chiave in chiavi:
                tentativi.append(f"{nome} bilancio {anno_esercizio} {chiave} filetype:pdf")
                tentativi.append(f"{gruppo} bilancio {anno_esercizio} {chiave} filetype:pdf")
                tentativi.append(f"{nome} {gruppo} bilancio {anno_esercizio} {chiave} filetype:pdf")
                for opz in opzionali:
                    tentativi.append(f"{nome} bilancio {anno_esercizio} {chiave} {opz} filetype:pdf")
                    tentativi.append(f"{gruppo} bilancio {anno_esercizio} {chiave} {opz} filetype:pdf")
                    tentativi.append(f"{nome} {gruppo} bilancio {anno_esercizio} {chiave} {opz} filetype:pdf")

            trovato = False
            for query in tentativi:
                url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={API_KEY}&cx={CX}"
                query_usate.append(query)
                try:
                    resp = requests.get(url)
                    items = resp.json().get("items", [])
                    pdf_url = next((i["link"] for i in items if ".pdf" in i["link"].lower()), None)
                    if pdf_url:
                        pdf_resp = requests.get(pdf_url)
                        if pdf_resp.status_code == 200:
                            images = convert_from_bytes(pdf_resp.content)
                            testo = ""
                            for img in images:
                                testo += pytesseract.image_to_string(img, config="--psm 6") + "\n"
                            if any(k.lower() in testo.lower() for k in chiavi):
                                risultati.append("Bilancio trovato e analizzato")
                            else:
                                risultati.append("PDF trovato ma dati non rilevabili")
                            trovato = True
                            break
                except Exception as e:
                    risultati.append(f"Errore: {str(e)}")
                    trovato = True
                    break
            if not trovato:
                risultati.append("Nessun PDF trovato")

        df["Risultato Ricerca"] = risultati
        df["Query Usata"] = query_usate

        st.subheader("Anteprima dei risultati")
        st.dataframe(df[["Legal Entity Name", "Parent/Group Company", "Risultato Ricerca", "Query Usata"]])

        output_path = "risultati_bilanci.xlsx"
        df.to_excel(output_path, index=False)
        st.success("Ricerca completata. File aggiornato pronto per il download.")
        with open(output_path, "rb") as f:
            st.download_button("Scarica file aggiornato", f, file_name=output_path)
