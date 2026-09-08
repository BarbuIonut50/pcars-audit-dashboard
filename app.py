import os
import re
import sqlite3

import pandas as pd
import streamlit as st
from openai import OpenAI


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "pcards.db")

st.set_page_config(
    page_title="OSU P-Card Audit Dashboard",
    page_icon="🔎",
    layout="wide",
)


def open_database():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def available_years():
    with open_database() as connection:
        rows = connection.execute(
            "SELECT DISTINCT Year FROM pcards WHERE Year IS NOT NULL ORDER BY Year"
        ).fetchall()
    return [int(row[0]) for row in rows]


def run_query(sql, parameters=None):
    with open_database() as connection:
        return pd.read_sql_query(sql, connection, params=parameters or [])


def api_key():
    try:
        return st.secrets["OPENAI_API_KEY"]
    except (KeyError, FileNotFoundError):
        return os.getenv("OPENAI_API_KEY")


def validate_read_only_sql(sql):
    cleaned = sql.strip().strip("`").strip()
    cleaned = re.sub(r"^sql\s*", "", cleaned, flags=re.IGNORECASE).strip()
    if not re.match(r"^(SELECT|WITH)\b", cleaned, flags=re.IGNORECASE):
        raise ValueError("The generated statement was not a read-only query.")
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
        re.IGNORECASE,
    )
    if forbidden.search(cleaned):
        raise ValueError("The generated statement contained a prohibited operation.")
    if ";" in cleaned.rstrip(";"):
        raise ValueError("Only one SQL statement may be executed.")
    return cleaned.rstrip(";") + " LIMIT 500;"


def question_to_sql(question, year):
    key = api_key()
    if not key:
        raise RuntimeError(
            "The OpenAI API key has not been configured in the website secrets."
        )

    schema = """
Table: pcards
Columns:
Year INTEGER, Month INTEGER, FullName TEXT, ID INTEGER,
AgencyNumber INTEGER, AgencyName TEXT, CardholderLastName TEXT,
CardholderFirstInitial TEXT, Description TEXT, Amount REAL,
Vendor TEXT, TransactionDate TEXT, PostedDate TEXT, MCC TEXT
"""
    prompt = f"""
You translate an auditor's question into one SQLite SELECT query.

{schema}

Rules:
- Use only the pcards table.
- Use only SELECT or a WITH query followed by SELECT.
- Never modify the database and never use PRAGMA, ATTACH, or multiple statements.
- Restrict the analysis to Year = {int(year)} unless the question explicitly requests another year.
- Return useful identifying fields for transaction-level answers.
- Use SQLite syntax.
- Return SQL only, with no markdown or explanation.

Auditor question: {question}
"""
    client = OpenAI(api_key=key)
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        input=prompt,
    )
    return validate_read_only_sql(response.output_text)


st.title("OSU P-Card Audit Dashboard")
st.caption("Review 2014 purchasing-card activity and identify transactions for follow-up.")

if not os.path.exists(DB_PATH):
    st.error("pcards.db is missing from the application folder.")
    st.stop()

years = available_years()
if not years:
    st.error("No transaction years were found in the database.")
    st.stop()

ask_tab, dashboard_tab = st.tabs(["Ask the database", "Prohibited purchases"])

with ask_tab:
    st.subheader("Ask a question in everyday language")
    st.write(
        "Choose a year, enter an audit question, and review the generated SQL and results. "
        "The database is opened in read-only mode."
    )
    ask_year = st.selectbox("Year", years, index=len(years) - 1, key="ask_year")
    question = st.text_area(
        "Audit question",
        placeholder="Which employees spent more than $50,000 during the year?",
        height=100,
    )
    if st.button("Ask the database", type="primary", use_container_width=True):
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            try:
                with st.spinner("Preparing the audit query..."):
                    generated_sql = question_to_sql(question.strip(), ask_year)
                    results = run_query(generated_sql)
                st.success(f"Returned {len(results):,} rows.")
                with st.expander("Generated SQLite query", expanded=False):
                    st.code(generated_sql, language="sql")
                st.dataframe(results, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download results as CSV",
                    results.to_csv(index=False).encode("utf-8"),
                    "audit-question-results.csv",
                    "text/csv",
                )
            except Exception as error:
                st.error(f"The question could not be completed: {error}")

with dashboard_tab:
    st.subheader("Search for prohibited purchases")
    st.write(
        "Select a year, then search either the transaction description or vendor name. "
        "Matches are potential exceptions and require supporting-document review."
    )
    search_year = st.selectbox(
        "Year", years, index=len(years) - 1, key="dashboard_year"
    )
    prohibited_examples = [
        "alcohol", "cash", "decorations", "donation", "gasoline",
        "gift card", "insurance", "late fee", "postage", "moving",
        "personal", "membership", "salary", "award",
    ]
    st.caption("Example terms: " + ", ".join(prohibited_examples))

    description_col, vendor_col = st.columns(2)
    with description_col:
        description_term = st.text_input(
            "Description search",
            placeholder="Example: alcohol",
            help="Searches only the Description field.",
        )
        description_search = st.button(
            "Search descriptions", use_container_width=True
        )
    with vendor_col:
        vendor_term = st.text_input(
            "Vendor search",
            placeholder="Example: post office",
            help="Searches only the Vendor field.",
        )
        vendor_search = st.button("Search vendors", use_container_width=True)

    field = None
    term = None
    if description_search:
        field, term = "Description", description_term.strip()
    elif vendor_search:
        field, term = "Vendor", vendor_term.strip()

    if field is not None:
        if not term:
            st.warning("Enter a search term first.")
        else:
            sql = f"""
                SELECT FullName, Amount, Description, Vendor,
                       TransactionDate, PostedDate, MCC
                FROM pcards
                WHERE Year = ?
                  AND LOWER({field}) LIKE LOWER(?)
                ORDER BY ABS(Amount) DESC, TransactionDate ASC
                LIMIT 2000
            """
            matches = run_query(sql, [search_year, f"%{term}%"])
            total = matches["Amount"].sum() if not matches.empty else 0
            metric_a, metric_b = st.columns(2)
            metric_a.metric("Matching transactions", f"{len(matches):,}")
            metric_b.metric("Net amount", f"${total:,.2f}")
            if matches.empty:
                st.info("No matching transactions were found.")
            else:
                st.dataframe(matches, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download results as CSV",
                    matches.to_csv(index=False).encode("utf-8"),
                    f"{field.lower()}-search-results.csv",
                    "text/csv",
                )

st.divider()
st.caption(
    "A flagged transaction is a risk indicator, not proof of a policy violation or fraud."
)
