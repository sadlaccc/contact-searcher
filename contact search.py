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

st.set_page_config(page_title="Doc to Lead Generator", page_icon="📊", layout="wide")
st.title("📊 Document-Based Lead & Email Finder")
st.write(
    "Upload a document or paste text to automatically identify the subject, find the company contact email, "
    "and export the result as Excel."
)

st.sidebar.header("🔑 API Configuration")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", type="password")

st.sidebar.markdown(
    "Use environment variables `OPENAI_API_KEY` and `TAVILY_API_KEY` if you want to avoid re-entering keys. "
    "You can also override the generated search query below."
)

search_query_override = st.sidebar.text_input("Override Search Query", value="")
max_results = st.sidebar.slider("Search results to retrieve", min_value=3, max_value=10, value=5)
model_name = st.sidebar.selectbox("LLM Model", options=["gpt-4o-mini", "gpt-3.5-turbo"], index=0)

uploaded_file = st.file_uploader("Upload a document (PDF, TXT, DOCX)", type=["pdf", "txt", "docx"])
manual_text = st.text_area("Or paste text directly", height=160)


def get_api_key(provided_key: str, env_var: str) -> str:
    return provided_key.strip() or os.getenv(env_var, "").strip()


def clean_text(text: str) -> str:
    return text.strip().replace("\n", " ").replace("  ", " ")


@st.cache_data(show_spinner=False)
def extract_text(file_bytes: bytes, content_type: str) -> str:
    if content_type == "text/plain":
        return file_bytes.decode("utf-8", errors="replace")
    if content_type == "application/pdf":
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return docx2txt.process(BytesIO(file_bytes))
    raise ValueError(f"Unsupported file type: {content_type}")


def build_search_query(raw_text: str, model: str) -> str:
    prompt = ChatPromptTemplate.from_template(
        "You are a document intelligence assistant. Review the provided text and identify the most relevant company, organization, "
        "or product name to use as a search query for finding official contact and email information.\n\n"
        "Return only a JSON object with the key `search_query`.\n\n"
        "Text: {text}"
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    result = chain.invoke({"text": raw_text[:4000]})
    search_query = result.get("search_query", "")
    if not search_query:
        raise ValueError("Search query could not be extracted from the document.")
    return search_query.strip()


def build_lead_details(search_query: str, context: str, model: str) -> dict:
    prompt = ChatPromptTemplate.from_template(
        "You are a lead generation assistant. Review the following web search results for '{query}'. "
        "Extract the official company name and the best contact email address found. If several emails appear, prioritize general contact, sales, or info emails. "
        "If no email is present, return 'Not Found'.\n\n"
        "Return ONLY a JSON object with keys `company_name` and `email`.\n\n"
        "Search Results:\n{context}"
    )
    llm = ChatOpenAI(model=model, temperature=0)
    chain = prompt | llm | JsonOutputParser()
    result = chain.invoke({"query": search_query, "context": context})
    return {
        "company_name": result.get("company_name", "Not Found"),
        "email": result.get("email", "Not Found"),
    }


def fetch_search_results(query: str, max_results_count: int) -> list[dict]:
    search = TavilySearchResults(max_results=max_results_count)
    results = search.invoke(f"{query} official website contact email")
    if isinstance(results, dict) and "results" in results:
        results = results["results"]
    return results if isinstance(results, list) else []


def make_excel_download(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    return output.getvalue()


def render_preview_block(title: str, content: str) -> None:
    with st.expander(title, expanded=False):
        st.write(content)


openai_key_final = get_api_key(openai_key, "OPENAI_API_KEY")
tavily_key_final = get_api_key(tavily_key, "TAVILY_API_KEY")

if uploaded_file or manual_text.strip():
    if not openai_key_final or not tavily_key_final:
        st.warning("Please provide both OpenAI and Tavily API keys in the sidebar or via environment variables.")
    else:
        os.environ["OPENAI_API_KEY"] = openai_key_final
        os.environ["TAVILY_API_KEY"] = tavily_key_final

        raw_text = ""
        if manual_text.strip():
            raw_text = manual_text.strip()
        else:
            file_bytes = uploaded_file.read()
            try:
                raw_text = extract_text(file_bytes, uploaded_file.type)
            except Exception as err:
                st.error(f"Unable to extract text from the uploaded file: {err}")
                raw_text = ""

        if raw_text:
            raw_text = clean_text(raw_text)
            if not raw_text:
                st.error("The uploaded document contains no readable text.")
            else:
                st.info("📌 Text extracted successfully. You can override the query in the sidebar if needed.")

                if search_query_override.strip():
                    search_query = search_query_override.strip()
                    st.info(f"🔧 Using overridden search query: {search_query}")
                else:
                    try:
                        search_query = build_search_query(raw_text, model_name)
                    except Exception as error:
                        st.error(
                            "Failed to generate a search query from the document."
                            " Please enter a custom query or paste more descriptive text."
                        )
                        search_query = ""

                if search_query:
                    with st.spinner("Searching the web for relevant company contact details..."):
                        search_results = fetch_search_results(search_query, max_results)

                    if not search_results:
                        st.warning("No web search results were returned. Try a different query or increase the result count.")
                    else:
                        context = "\n---\n".join(
                            f"URL: {item.get('url', 'N/A')}\nContent: {item.get('content', '')}" for item in search_results
                        )
                        render_preview_block("Raw Search Results", context)

                        with st.spinner("Extracting company and email details from search results..."):
                            try:
                                final_lead = build_lead_details(search_query, context, model_name)
                            except Exception as error:
                                st.error(f"Lead extraction failed: {error}")
                                final_lead = {"company_name": "Not Found", "email": "Not Found"}

                        st.success("🎉 Processing complete!")
                        st.info(f"**Search Query:** {search_query}")

                        df = pd.DataFrame([
                            {
                                "Search Query Used": search_query,
                                "Identified Company": final_lead.get("company_name", "Not Found"),
                                "Contact Email": final_lead.get("email", "Not Found"),
                            }
                        ])

                        st.table(df)
                        download_bytes = make_excel_download(df)
                        st.download_button(
                            label="📥 Download Results as Excel",
                            data=download_bytes,
                            file_name="extracted_lead_info.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
        else:
            st.warning("Please upload a document or paste text to begin processing.")
else:
    st.info("Upload a document or paste text to start. Optionally provide API keys in the sidebar.")
