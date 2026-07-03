import os
from io import BytesIO

import streamlit as st
import pandas as pd
import PyPDF2
from docx import Document
import openai

st.set_page_config(page_title="Doc to Lead", page_icon="📊", layout="wide")

st.title("📊 Doc to Lead Generator")
st.markdown("**Free Streamlit Cloud Optimized**")

# Sidebar
st.sidebar.header("🔑 API Configuration")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))

model_name = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-3.5-turbo"], index=0)
override_query = st.sidebar.text_input("Override Company Name", "")

# ====================== HELPERS ======================
def extract_text(file):
    try:
        if file.type == "application/pdf":
            reader = PyPDF2.PdfReader(file)
            return "\n".join([page.extract_text() or "" for page in reader.pages])
        elif file.type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            doc = Document(file)
            return "\n".join([p.text for p in doc.paragraphs])
        elif file.type == "text/plain":
            return file.getvalue().decode("utf-8", errors="replace")
        return ""
    except:
        return ""

def get_company_name(text: str):
    try:
        response = openai.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[{
                "role": "user",
                "content": f"Extract the main company or organization name from this text. Return only the name.\n\nText: {text[:5000]}"
            }]
        )
        return response.choices[0].message.content.strip()
    except:
        return "Unknown"

def get_lead_info(company: str):
    try:
        response = openai.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[{
                "role": "user",
                "content": f"""Find the official company name and best contact email for: {company}
Prefer general emails like info@, contact@, sales@.
Return in this format:
Company: 
Email: 
Website: """
            }]
        )
        text = response.choices[0].message.content
        
        company_name = email = website = "Not Found"
        for line in text.splitlines():
            if "Company:" in line:
                company_name = line.split(":", 1)[-1].strip()
            elif "Email:" in line:
                email = line.split(":", 1)[-1].strip()
            elif "Website:" in line:
                website = line.split(":", 1)[-1].strip()
        return {"company_name": company_name, "email": email, "website": website}
    except Exception as e:
        return {"company_name": "Error", "email": "Not Found", "website": str(e)}

# Session State
if "leads" not in st.session_state:
    st.session_state.leads = []

# Main UI
uploaded_files = st.file_uploader("Upload PDF, DOCX or TXT", 
                                 type=["pdf", "docx", "txt"], 
                                 accept_multiple_files=True)

manual_text = st.text_area("Or paste text", height=160)

if st.button("🚀 Process", type="primary", use_container_width=True):
    if not openai_key:
        st.error("Please enter your OpenAI API Key")
        st.stop()

    openai.api_key = openai_key

    documents = []
    for file in uploaded_files:
        text = extract_text(file)
        if text.strip():
            documents.append({"source": file.name, "text": text})

    if manual_text.strip():
        documents.append({"source": "Manual Input", "text": manual_text})

    if not documents:
        st.warning("No text found.")
        st.stop()

    progress = st.progress(0)

    for i, doc in enumerate(documents):
        st.info(f"Processing **{doc['source']}**")
        
        company = override_query or get_company_name(doc["text"])
        lead = get_lead_info(company)
        lead["source"] = doc["source"]
        lead["search_query"] = company
        st.session_state.leads.append(lead)

        progress.progress((i + 1) / len(documents))

    st.success("✅ Done!")

# Results
if st.session_state.leads:
    st.subheader("Results")
    df = pd.DataFrame(st.session_state.leads)
    st.dataframe(df, use_container_width=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    st.download_button("Download Excel", output.getvalue(), "leads.xlsx", 
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if st.button("Clear Results"):
        st.session_state.leads = []
        st.rerun()

st.caption("Ultra-light version for free Streamlit Cloud")
