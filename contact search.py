import streamlit as str
import pandas as pd
import json
import os
from io import BytesIO
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

# 1. UI Setup
st.set_page_config(page_title="Doc to Lead Generator", page_icon="📊", layout="wide")
st.title("📊 Document-Based Lead & Email Finder")
st.write("Upload a document, and this app will identify the subject, search the web for their company name and contact email, and give you an Excel file.")

# Sidebar for API Keys
st.sidebar.header("🔑 API Configurations")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", type="password")

# 2. File Upload
uploaded_file = st.file_uploader("Upload a Document (PDF, TXT, or DOCX)", type=["pdf", "txt", "docx"])

def extract_text(file):
    """Extracts text based on file type."""
    if file.type == "text/plain":
        return str(file.read(), "utf-8")
    elif file.type == "application/pdf":
        import pypdf
        pdf_reader = pypdf.PdfReader(file)
        return "".join([page.extract_text() for page in pdf_reader.pages])
    elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        import docx2txt
        return docx2txt.process(file)
    return ""

if uploaded_file and openai_key and tavily_key:
    # Set environment variables for the session
    os.environ["OPENAI_API_KEY"] = openai_key
    os.environ["TAVILY_API_KEY"] = tavily_key

    with st.spinner("Processing document..."):
        raw_text = extract_text(uploaded_file)
        
        # 3. Step 1: Extract Main Entities/Keywords from Document using LLM
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        
        extraction_prompt = ChatPromptTemplate.from_template(
            "Analyze the following text and identify the main person, product, or organization it is about. "
            "Return a JSON object with a single key 'search_query' containing the best search term to find their company website and contact info.\n\n"
            "Text: {text}"
        )
        
        chain = extraction_prompt | llm | JsonOutputParser()
        extracted_data = chain.invoke({"text": raw_text[:4000]}) # Limit text to avoid token issues
        search_query = extracted_data.get("search_query", "")
        
    st.info(f"🔍 **Generated Search Query based on document:** '{search_query}'")
    
    # 4. Step 2: Search the Web
    with st.spinner("Searching the web for company details and emails..."):
        search = TavilySearchResults(max_results=5)
        # We explicitly ask for contact/email pages in the search
        search_results = search.invoke(f"{search_query} official website contact email")
        
        # Combine search results for the LLM to parse
        context = "\n---\n".join([f"URL: {res['url']}\nContent: {res['content']}" for res in search_results])

    # 5. Step 3: Parse Search Results for Company Name and Email
    with st.spinner("Extracting finalized lead details..."):
        synthesis_prompt = ChatPromptTemplate.from_template(
            "You are a lead generation assistant. Review the following web search results regarding '{query}'. "
            "Extract the official Company Name and the best Contact Email address found. "
            "If multiple emails exist, prioritize general info, sales, or contact emails. If not found, write 'Not Found'.\n\n"
            "Return ONLY a JSON object with the keys: 'company_name' and 'email'.\n\n"
            "Search Results:\n{context}"
        )
        
        synthesis_chain = synthesis_prompt | llm | JsonOutputParser()
        final_lead = synthesis_chain.invoke({"query": search_query, "context": context})
        
    # 6. Display Results
    st.success("🎉 Processing Complete!")
    
    # Create DataFrame
    df = pd.DataFrame([{
        "Search Query Used": search_query,
        "Identified Company": final_lead.get("company_name", "Not Found"),
        "Contact Email": final_lead.get("email", "Not Found")
    }])
    
    st.table(df)
    
    # 7. Step 4: Export to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Leads')
    processed_data = output.getvalue()
    
    st.download_button(
        label="📥 Download Results as Excel",
        data=processed_data,
        file_name="extracted_lead_info.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

elif uploaded_file and (not openai_key or not tavily_key):
    st.warning("Please provide both OpenAI and Tavily API keys in the sidebar.")