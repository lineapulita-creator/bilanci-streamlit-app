import streamlit as st
from search_cse import pick_entrypoints
from crawler import crawl_for_pdf

st.set_page_config(page_title="Entrypoint → Crawl → PDF", page_icon="📄", layout="centered")
st.title("📄 Bilanci – Entrypoint → Crawl → PDF")
st.caption("Trova la pagina indice (IR/Bilanci/Trasparenza) e naviga nel dominio fino al PDF dell'anno.")

with st.form("param"):
    company = st.text_input("Ragione sociale", value="Estra")
    year = st.number_input("Anno", min_value=2005, max_value=2028, value=2023, step=1)
    manual_seed = st.text_input("URL seed (opzionale: pagina 'Bilanci e Relazioni' / 'Investor Relations')")
    max_depth = st.slider("Profondità massima crawl", 1, 6, 4)
    max_pages = st.slider("Pagine massime da visitare", 10, 120, 50, step=10)
    submitted = st.form_submit_button("Cerca PDF")

if submitted:
    st.info(f"Cerco PDF per **{company} – {int(year)}**…")

    # 1) Entrypoint
    if manual_seed.strip():
        entrypoints = [manual_seed.strip()]
        st.write("🔗 Entrypoint (manuale): ", entrypoints[0])
    else:
        try:
            api_key = st.secrets["google"]["api_key"]
            cx      = st.secrets["google"]["cx"]
        except Exception:
            st.error("Configura le secrets in Streamlit Cloud: [google.api_key] e [google.cx] — oppure usa un seed manuale.")
            st.stop()

        entrypoints = pick_entrypoints(company, int(year), api_key, cx, max_sites=5)
        if not entrypoints:
            st.error("La CSE non ha restituito entrypoint utili. Prova un seed manuale.")
            st.stop()
        with st.expander("🔎 Entrypoint trovati via CSE"):
            for u in entrypoints:
                st.write(u)

    # 2) Crawl interno al dominio
    with st.spinner("Navigo nel dominio alla ricerca del PDF…"):
        res = crawl_for_pdf(entrypoints, int(year), max_pages=max_pages, max_depth=max_depth)

    # 3) Esito
    if res.get("pdf"):
        st.success(f"✅ PDF trovato ({res['score']:.2f}) via {res['via']} — pagine visitate: {res['visited']}")
        st.code(res["pdf"], language="text")
        st.caption("Copia l'URL: puoi usarlo nel tuo flusso OCR/Excel.")
    else:
        st.warning(f"⚠️ Nessun PDF trovato entro i limiti (visitato: {res.get('visited')}).")
        st.caption("Suggerimenti: incolla la pagina 'Bilanci e Relazioni' come seed oppure aumenta profondità/pagine.")
