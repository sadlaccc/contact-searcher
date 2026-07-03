import os
from io import BytesIO

import streamlit as st
import pandas as pd
import PyPDF2
from docx import Document

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults

st.set_page_config(page_title="Doc to Lead Generator", page_icon="📊", layout="wide")

st.title("📊 Document-Based Lead & Email Finder")
st.markdown("Find company contacts from documents")

# Sidebar
st.sidebar.header("🔑 API Keys")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", type="password")

st.sidebar.markdown("---")
model_name = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-3.5-turbo"])
max_results = st.sidebar.slider("Max Search Results", 3, 10, 5)
override_query = st.sidebar.text_input("Override Search Query", "")

# ====================== HELPERS ======================
def extract_text(file) -> str:
    try:
        if file.type == "application/pdf":
            reader = PyPDF2.PdfReader(file)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        
        elif file.type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            doc = Document(file)
            return "\n".join(p.text for p in doc.paragraphs)
        
        elif file.type == "text/plain":
            return file.getvalue().decode("utf-8", errors="replace")
        return ""
    except Exception as e:
        st.error(f"Failed to read {file.name}: {e}")
        return ""

def clean_text(text):
    return " ".join(str(text).split())[:8000]

def build_search_query(text: str, model: str):
    prompt = ChatPromptTemplate.from_template(
        "Extract the main company/organization name.\nReturn only JSON: {{\"search_query\": \"...\"}}\n\nText: {text}"
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    try:
        result = chain.invoke({"text": text})
        return result.get("search_query", "").strip()
    except:
        return ""

def search_web(query: str):
    try:
        tool = TavilySearchResults(max_results=max_results)
        results = tool.invoke(query + " official contact email")
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        return results if isinstance(results, list) else []
    except:
        return []

def extract_lead(query: str, context: str, model: str):
    prompt = ChatPromptTemplate.from_template(
        "Extract company name and best contact email from results.\n"
        "Return only JSON: {{\"company_name\": \"\", \"email\": \"\", \"website\": \"\"}}\n\n"
        "Query: {query}\n\nResults:\n{context}"
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    try:
        result = chain.invoke({"query": query, "context": context})
        return {
            "company_name": result.get("company_name", "Not Found"),
            "email": result.get("email", "Not Found"),
            "website": result.get("website", "Not Found")
        }
    except:
        return {"company_name": "Error", "email": "Not Found", "website": ""}

# Session State
if "leads" not in st.session_state:
    st.session_state.leads = []

# Main UI
uploaded_files = st.file_uploader("Upload files (PDF, DOCX, TXT)", 
                                 type=["pdf", "docx", "txt"], 
                                 accept_multiple_files=True)

manual_text = st.text_area("Or paste text", height=150)

if st.button("🚀 Process", type="primary", use_container_width=True):
    if not openai_key or not tavily_key:
        st.error("Please provide both API keys.")
        st.stop()

    os.environ["OPENAI_API_KEY"] = openai_key
    os.environ["TAVILY_API_KEY"] = tavily_key

    docs = []
    for file in uploaded_files:
        text = extract_text(file)
        if text.strip():
            docs.append({"source": file.name, "text": clean_text(text)})

    if manual_text.strip():
        docs.append({"source": "Manual", "text": clean_text(manual_text)})

    if not docs:
        st.warning("No text found.")
        st.stop()

    progress = st.progress(0)
    for i, doc in enumerate(docs):
        st.write(f"Processing: **{doc['source']}**")
        
        query = override_query or build_search_query(doc["text"], model_name)
        if not query:
            query = doc["source"]

        results = search_web(query)
        if results:
            context = "\n---\n".join([f"{r.get('url')}: {r.get('content', '')[:300]}" for r in results])
            lead = extract_lead(query, context, model_name)
            lead.update({"source": doc["source"], "search_query": query})
            st.session_state.leads.append(lead)

        progress.progress((i+1)/len(docs))

    st.success("Done!")

# Show Results
if st.session_state.leads:
    df = pd.DataFrame(st.session_state.leads)
    st.dataframe(df, use_container_width=True)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    st.download_button("Download Excel", buf.getvalue(), "leads.xlsx", 
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    if st.button("Clear"):
        st.session_state.leads = []
        st.rerun()

st.caption("Streamlit Cloud Optimized Version")
