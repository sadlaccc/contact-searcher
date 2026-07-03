import os
from io import BytesIO

import docx2txt
import pandas as pd
import pypdf
import streamlit as st
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

st.set_page_config(
    page_title="Doc to Lead Generator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📊 Document-Based Lead & Email Finder")
st.markdown(
    "Upload documents or paste text to **automatically identify companies** and find official contact emails. "
    "Powered by OpenAI + Tavily."
)

# ====================== SIDEBAR ======================
st.sidebar.header("🔑 API Configuration")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
tavily_key = st.sidebar.text_input("Tavily API Key", type="password", value=os.getenv("TAVILY_API_KEY", ""))

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Settings")
model_name = st.sidebar.selectbox(
    "LLM Model", 
    options=["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"], 
    index=0
)
max_results = st.sidebar.slider("Max Search Results", min_value=3, max_value=15, value=8)
search_query_override = st.sidebar.text_input("Override Search Query", value="", help="Leave empty to auto-generate from document")
use_structured_output = st.sidebar.checkbox("Use Structured Output (more reliable)", value=True)

st.sidebar.markdown("---")
st.sidebar.info(
    "💡 **Tip**: For best results use documents that mention a company, product, or organization name clearly."
)

# ====================== MAIN AREA ======================
col1, col2 = st.columns([2, 1])

with col1:
    uploaded_files = st.file_uploader(
        "Upload document(s) (PDF, TXT, DOCX)", 
        type=["pdf", "txt", "docx"],
        accept_multiple_files=True
    )

with col2:
    manual_text = st.text_area("Or paste text directly", height=200, placeholder="Paste document content here...")

# ====================== HELPER FUNCTIONS ======================
def get_api_key(provided: str, env_var: str) -> str:
    return (provided or os.getenv(env_var, "")).strip()

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = " ".join(text.split())  # normalize whitespace
    return text[:12000]  # safety limit

@st.cache_data(show_spinner=False)
def extract_text(file_bytes: bytes, content_type: str) -> str:
    try:
        if content_type == "text/plain":
            return file_bytes.decode("utf-8", errors="replace")
        elif content_type == "application/pdf":
            reader = pypdf.PdfReader(BytesIO(file_bytes))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        elif content_type.endswith("wordprocessingml.document"):
            return docx2txt.process(BytesIO(file_bytes))
        return ""
    except Exception as e:
        st.error(f"Extraction error: {e}")
        return ""

def build_search_query(raw_text: str, model: str) -> str:
    prompt = ChatPromptTemplate.from_template(
        """You are an expert at extracting company/organization names from documents.
Extract the **most relevant single company, organization, or product name** that would be best for searching official contact information.

Return only valid JSON with key `search_query`.

Text: {text}"""
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    result = chain.invoke({"text": raw_text[:6000]})
    return result.get("search_query", "").strip()

def fetch_search_results(query: str, max_res: int) -> list:
    try:
        search = TavilySearchResults(max_results=max_res, search_depth="advanced")
        results = search.invoke(f"{query} official contact email OR info@ OR sales@")
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        return results if isinstance(results, list) else []
    except Exception as e:
        st.error(f"Search failed: {e}")
        return []

def build_lead_details(search_query: str, context: str, model: str) -> dict:
    prompt = ChatPromptTemplate.from_template(
        """You are a professional lead researcher.
From the search results below, extract:

1. The official company name
2. The best general contact email (info@, contact@, sales@ preferred). If multiple, pick the most professional one.
3. The official website (if clearly present)

If no email is found, return "Not Found".

Return **only** valid JSON with keys: `company_name`, `email`, `website`.

Search Query: {query}
Search Results:
{context}"""
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    result = chain.invoke({"query": search_query, "context": context})
    return {
        "company_name": result.get("company_name", "Not Found"),
        "email": result.get("email", "Not Found"),
        "website": result.get("website", "Not Found")
    }

def make_excel_download(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    return output.getvalue()

# ====================== SESSION STATE ======================
if "leads" not in st.session_state:
    st.session_state.leads = []
if "processed_texts" not in st.session_state:
    st.session_state.processed_texts = {}

# ====================== PROCESSING LOGIC ======================
openai_key_final = get_api_key(openai_key, "OPENAI_API_KEY")
tavily_key_final = get_api_key(tavily_key, "TAVILY_API_KEY")

if (uploaded_files or manual_text.strip()) and st.button("🚀 Process Documents", type="primary", use_container_width=True):
    if not openai_key_final or not tavily_key_final:
        st.error("⚠️ Please provide both OpenAI and Tavily API keys.")
        st.stop()

    os.environ["OPENAI_API_KEY"] = openai_key_final
    os.environ["TAVILY_API_KEY"] = tavily_key_final

    documents_to_process = []

    # Handle uploaded files
    if uploaded_files:
        for file in uploaded_files:
            file_bytes = file.read()
            text = extract_text(file_bytes, file.type)
            if text.strip():
                documents_to_process.append({
                    "source": file.name,
                    "text": clean_text(text),
                    "type": "file"
                })
            else:
                st.warning(f"Could not extract text from {file.name}")

    # Handle manual text
    if manual_text.strip():
        documents_to_process.append({
            "source": "Manual Input",
            "text": clean_text(manual_text),
            "type": "manual"
        })

    if not documents_to_process:
        st.error("No valid text found in inputs.")
        st.stop()

    progress_bar = st.progress(0)
    status_text = st.empty()

    for idx, doc in enumerate(documents_to_process):
        status_text.info(f"Processing {doc['source']} ({idx+1}/{len(documents_to_process)})")

        search_query = search_query_override.strip() if search_query_override.strip() else build_search_query(doc["text"], model_name)

        with st.spinner(f"Searching web for: **{search_query}**"):
            search_results = fetch_search_results(search_query, max_results)

        if not search_results:
            st.warning(f"No results for {doc['source']}")
            continue

        context = "\n---\n".join(
            f"URL: {item.get('url', 'N/A')}\nSnippet: {item.get('content', '')[:500]}..." 
            for item in search_results[:max_results]
        )

        with st.spinner("Analyzing search results..."):
            lead = build_lead_details(search_query, context, model_name)

        lead["source"] = doc["source"]
        lead["search_query"] = search_query
        st.session_state.leads.append(lead)

        progress_bar.progress((idx + 1) / len(documents_to_process))

    status_text.success("✅ All documents processed!")
    st.balloons()

# ====================== RESULTS ======================
if st.session_state.leads:
    st.subheader("📋 Extracted Leads")
    
    df = pd.DataFrame(st.session_state.leads)
    # Reorder columns
    cols = ["source", "search_query", "company_name", "email", "website"]
    df = df[[c for c in cols if c in df.columns]]
    
    st.dataframe(df, use_container_width=True, hide_index=True)

    excel_bytes = make_excel_download(df)
    st.download_button(
        label="📥 Download as Excel",
        data=excel_bytes,
        file_name="leads_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    if st.button("🗑️ Clear Results"):
        st.session_state.leads = []
        st.rerun()

else:
    st.info("👆 Upload documents or paste text and click **Process Documents** to begin.")

st.caption("Made with ❤️ for Streamlit Community • Be respectful of websites and scraping policies.")
