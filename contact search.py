import os
from io import BytesIO

import streamlit as st
import pandas as pd
from pypdf import PdfReader
from docx import Document

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults

st.set_page_config(page_title="Doc to Lead Generator", page_icon="📊", layout="wide")

st.title("📊 Document-Based Lead & Email Finder")
st.markdown("Upload documents or paste text → Find company + official email")

# ====================== SIDEBAR ======================
st.sidebar.header("🔑 API Keys")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
tavily_key = st.sidebar.text_input("Tavily API Key", type="password", value=os.getenv("TAVILY_API_KEY", ""))

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Settings")
model_name = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-3.5-turbo"], index=0)
max_results = st.sidebar.slider("Max Search Results", 3, 12, 6)
override_query = st.sidebar.text_input("Override Search Query", "")

# ====================== HELPERS ======================
def extract_text_from_file(file) -> str:
    """Extract text from PDF, DOCX, or TXT"""
    try:
        if file.type == "application/pdf":
            reader = PdfReader(file)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        
        elif file.type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", 
                          "application/msword"]:
            doc = Document(file)
            return "\n".join(para.text for para in doc.paragraphs)
        
        elif file.type == "text/plain":
            return file.getvalue().decode("utf-8", errors="replace")
        
        return ""
    except Exception as e:
        st.error(f"Error reading {file.name}: {e}")
        return ""

def clean_text(text: str) -> str:
    return " ".join(str(text).split())[:10000]

def build_search_query(text: str, model: str) -> str:
    prompt = ChatPromptTemplate.from_template(
        "Extract the most relevant company or organization name from this text for contact search.\n"
        "Return only JSON: {{\"search_query\": \"name\"}}\n\nText: {text}"
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    result = chain.invoke({"text": text[:5000]})
    return result.get("search_query", "").strip()

def search_web(query: str, max_res: int):
    try:
        tool = TavilySearchResults(max_results=max_res)
        results = tool.invoke(f"{query} official email OR contact OR info@ OR sales@")
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        return results if isinstance(results, list) else []
    except Exception as e:
        st.error(f"Search error: {e}")
        return []

def extract_lead(query: str, context: str, model: str):
    prompt = ChatPromptTemplate.from_template(
        "From the search results, extract company name and best contact email.\n"
        "Return only JSON with keys: company_name, email, website\n\n"
        "Query: {query}\nResults:\n{context}"
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    result = chain.invoke({"query": query, "context": context})
    return {
        "company_name": result.get("company_name", "Not Found"),
        "email": result.get("email", "Not Found"),
        "website": result.get("website", "Not Found")
    }

# ====================== SESSION STATE ======================
if "leads" not in st.session_state:
    st.session_state.leads = []

# ====================== MAIN APP ======================
uploaded_files = st.file_uploader(
    "Upload PDF, DOCX, or TXT", 
    type=["pdf", "docx", "txt"], 
    accept_multiple_files=True
)

manual_text = st.text_area("Or paste text here", height=180)

if st.button("🚀 Process Documents", type="primary", use_container_width=True):
    if not openai_key or not tavily_key:
        st.error("Please enter both API keys in the sidebar.")
        st.stop()

    os.environ["OPENAI_API_KEY"] = openai_key
    os.environ["TAVILY_API_KEY"] = tavily_key

    documents = []

    # Process uploaded files
    for file in uploaded_files:
        with st.spinner(f"Reading {file.name}..."):
            text = extract_text_from_file(file)
            if text.strip():
                documents.append({"source": file.name, "text": clean_text(text)})

    # Process manual input
    if manual_text.strip():
        documents.append({"source": "Manual Input", "text": clean_text(manual_text)})

    if not documents:
        st.warning("No text found.")
        st.stop()

    progress_bar = st.progress(0)

    for i, doc in enumerate(documents):
        st.info(f"Processing: **{doc['source']}**")
        
        query = override_query.strip() or build_search_query(doc["text"], model_name)
        
        with st.spinner("Searching web..."):
            results = search_web(query, max_results)
        
        if results:
            context = "\n\n".join([f"URL: {r.get('url')}\nContent: {r.get('content', '')[:400]}" 
                                 for r in results])
            
            with st.spinner("Extracting lead info..."):
                lead = extract_lead(query, context, model_name)
                lead["source"] = doc["source"]
                lead["search_query"] = query
                st.session_state.leads.append(lead)
        
        progress_bar.progress((i + 1) / len(documents))

    st.success("✅ Processing complete!")

# ====================== RESULTS ======================
if st.session_state.leads:
    st.subheader("📋 Results")
    df = pd.DataFrame(st.session_state.leads)
    
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    
    st.download_button(
        "📥 Download Excel",
        data=output.getvalue(),
        file_name="leads.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    if st.button("Clear Results"):
        st.session_state.leads = []
        st.rerun()
else:
    st.info("Upload files or paste text and click **Process Documents**")

st.caption("Optimized for Streamlit Community Cloud")
