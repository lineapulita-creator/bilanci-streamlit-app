import streamlit as st, sys, importlib, httpx

st.set_page_config(page_title="Diagnostics", page_icon="🩺", layout="centered")
st.title("🩺 Diagnostics")

st.subheader("Ambiente")
st.write("Python:", sys.version)

def has_pkg(name):
    try:
        m = importlib.import_module(name)
        ver = getattr(m, "__version__", "n/a")
        return True, ver
    except Exception as e:
        return False, str(e)

for pkg in ["streamlit", "httpx", "bs4"]:
    ok, info = has_pkg(pkg)
    st.write(f"**{pkg}** →", "✅ "+info if ok else "❌ "+info)

st.subheader("Secrets (presenza, non valori)")
g = st.secrets.get("google", {})
st.write("`google.api_key` presente? →", "✅" if "api_key" in g else "❌")
st.write("`google.cx` presente? →", "✅" if "cx" in g else "❌")

st.subheader("Test rete (GET semplice)")
try:
    r = httpx.get("https://www.google.com/robots.txt", timeout=10, follow_redirects=True)
    st.write("GET google.com:", "✅", r.status_code)
except Exception as e:
    st.write("GET google.com:", "❌", e)

st.caption("Se 'httpx' o 'bs4' sono ❌, aggiungili in requirements.txt e riavvia l'app.")
