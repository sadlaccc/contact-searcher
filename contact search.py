import os
from io import BytesIO

import streamlit as st
import pandas as pd
import PyPDF2
from docx import Document
import openai
from tavily import TavilyClient

st.set_page_config(page_title="Doc to Lead Generator", page_icon="📊", layout="wide")

st.title("📊 Document to Lead Generator")
st.markdown("Upload documents or paste text to find company emails")

# Sidebar
st.sidebar.header("🔑 API Keys")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
tavily_key = st.sidebar.text_input("Tavily API Key", type="password", value=os.getenv("TAVILY_API_KEY", ""))

st.sidebar.markdown("---")
model_name = st.sidebar.selectbox("OpenAI Model", ["gpt-4o-mini", "gpt-3.5-turbo"])
max_results = st.sidebar.slider("Max Search Results", 3, 10, 5)
override_query = st.sidebar.text_input("Override Search Query", "")

# ====================== HELPERS ======================
def extract_text(file):
    try:
        if file.type == "application/pdf":
            reader = PyPDF2.PdfReader(file)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        elif file.type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            doc = Document(file)
            return "\n".join(paragraph.text for paragraph in doc.paragraphs)
        elif file.type == "text/plain":
            return file.getvalue().decode("utf-8", errors="replace")
        return ""
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return ""

def clean_text(text):
    return " ".join(str(text).split())[:8000]

def get_search_query(text: str):
    try:
        response = openai.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"""Extract the main company or organization name from this text for contact search.
Return only the name, nothing else.

Text: {text[:6000]}"""}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Query generation failed: {e}")
        return ""

def search_with_tavily(query: str):
    try:
        client = TavilyClient(api_key=tavily_key)
        results = client.search(
            query=query + " official contact email OR info@ OR sales@",
            max_results=max_results
        )
        return results.get("results", [])
    except Exception as e:
        st.error(f"Search failed: {e}")
        return []

def extract_lead_info(query: str, search_results):
    context = "\n\n".join([f"URL: {r.get('url')}\nContent: {r.get('content', '')[:400]}" for r in search_results])
    
    try:
        response = openai.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a lead generation expert."},
                {"role": "user", "content": f"""From the search results below, extract:
- Company Name
- Best contact email (info@, sales@, contact@ preferred)
- Website (if available)

Return in this exact format:
Company: 
Email: 
Website: 

Search Query: {query}

Results:
{context}"""}
            ]
        )
        text = response.choices[0].message.content
        company = "Not Found"
        email = "Not Found"
        website = "Not Found"
        
        for line in text.split("\n"):
            if line.lower().startswith("company"):
                company = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("email"):
                email = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("website"):
                website = line.split(":", 1)[-1].strip()
        
        return {"company_name": company, "email": email, "website": website}
    except Exception as e:
        st.error(f"Lead extraction failed: {e}")
        return {"company_name": "Error", "email": "Not Found", "website": ""}

# Session State
if "leads" not in st.session_state:
    st.session_state.leads = []

# Main Interface
uploaded_files = st.file_uploader("Upload PDF / DOCX / TXT", 
                                 type=["pdf", "docx", "txt"], 
                                 accept_multiple_files=True)

manual_text = st.text_area("Or paste text here", height=180)

if st.button("🚀 Process Documents", type="primary", use_container_width=True):
    if not openai_key or not tavily_key:
        st.error("Please enter both API keys in the sidebar.")
        st.stop()

    openai.api_key = openai_key

    documents = []
    for file in uploaded_files:
        text = extract_text(file)
        if text.strip():
            documents.append({"source": file.name, "text": clean_text(text)})

    if manual_text.strip():
        documents.append({"source": "Manual Input", "text": clean_text(manual_text)})

    if not documents:
        st.warning("No valid text found.")
        st.stop()

    progress_bar = st.progress(0)

    for i, doc in enumerate(documents):
        st.info(f"Processing: **{doc['source']}**")
        
        query = override_query.strip() or get_search_query(doc["text"])
        if not query:
            query = doc["source"]

        with st.spinner("Searching web..."):
            results = search_with_tavily(query)

        if results:
            with st.spinner("Extracting lead details..."):
                lead = extract_lead_info(query, results)
                lead["source"] = doc["source"]
                lead["search_query"] = query
                st.session_state.leads.append(lead)

        progress_bar.progress((i + 1) / len(documents))

    st.success("✅ Processing completed!")

# Results
if st.session_state.leads:
    st.subheader("📋 Extracted Leads")
    df = pd.DataFrame(st.session_state.leads)
    st.dataframe(df, use_container_width=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    
    st.download_button(
        label="📥 Download Excel",
        data=output.getvalue(),
        file_name="leads.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    if st.button("🗑️ Clear Results"):
        st.session_state.leads = []
        st.rerun()
else:
    st.info("Upload files or paste text then click **Process Documents**")

st.caption("Light version optimized for free Streamlit Cloud")
