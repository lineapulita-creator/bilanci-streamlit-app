# Web App - Analisi Bilanci Aziendali

Questa applicazione consente di:
- Caricare un file Excel con aziende (Ragione Sociale, P.IVA, Gruppo)
- Selezionare l’anno di bilancio da cercare
- Inserire parole chiave da verificare nei bilanci
- Cercare online i PDF dei bilanci tramite Google Custom Search API
- Estrarre testo dai PDF tramite OCR
- Verificare la presenza delle parole chiave
- Scaricare un file Excel con i risultati

## Come usarla
1. Apri l’app su Streamlit Cloud.
2. Carica il file Excel.
3. Seleziona l’anno.
4. Inserisci le parole chiave.
5. Clicca “Avvia analisi”.
6. Scarica il file Excel con i risultati.

**Non è richiesta alcuna configurazione tecnica.**
**L’app usa la Google Custom Search API con un limite gratuito di 100 query/giorno.**

## 📄 Nuova funzione: Entrypoint → Crawl → PDF

Questa app ora include una pagina (multi‑page) che usa Google Programmable Search **solo** per trovare la
**pagina indice** (Investor Relations / Bilanci / Amministrazione Trasparente) nel dominio ufficiale di un’azienda,
poi esegue un **crawling mirato** dentro il dominio per individuare il **PDF** del bilancio dell’anno selezionato.

### Come si usa (Streamlit Community Cloud)
1. Assicurati che i pacchetti siano installati (vedi `requirements.txt`).
2. Imposta le secrets della tua app su **Streamlit Cloud**  
   (Dashboard app → **Settings** → **Secrets**), in formato TOML:
   ```toml
   [google]
   api_key = "YOUR_GOOGLE_API_KEY"
   cx      = "YOUR_CSE_CX"
