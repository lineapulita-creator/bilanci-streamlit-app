
import streamlit as st
import pandas as pd

st.title("Bilanci Aziendali - Versione Parziale")

# File upload
uploaded_file = st.file_uploader("Carica il file Excel con ragioni sociali, P.IVA e gruppo", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file, engine="openpyxl")
        st.success("File caricato correttamente.")
        st.dataframe(df)
    except Exception as e:
        st.error(f"Errore nel caricamento del file: {e}")

# Input per anno e parole chiave
anno = st.text_input("Inserisci l'anno di bilancio")
parole_chiave = st.text_area("Inserisci le parole chiave (separate da virgola)")

if anno and parole_chiave:
    st.info(f"Anno selezionato: {anno}")
    st.info(f"Parole chiave: {[p.strip() for p in parole_chiave.split(',')]}")

st.warning("Questa è una versione parziale. La ricerca online e l'OCR saranno attivati nella versione completa.")
