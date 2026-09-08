# OSU P-Card Audit Dashboard

This Streamlit website supports Part IV of the P-card assignment. It contains:

- an **Ask the database** tab that converts an auditor's natural-language question into a read-only SQLite query;
- a **Prohibited purchases** tab with year selection and separate Description and Vendor searches;
- CSV downloads for follow-up analysis.

## Required files

Keep these files together in the repository:

- `app.py`
- `pcards.db`
- `requirements.txt`
- `.gitignore`
- `.streamlit/config.toml`

## API key security

Never put an API key in `app.py`, the database, or any committed file.

For local testing, create `.streamlit/secrets.toml` and add:

```toml
OPENAI_API_KEY = "your-key-here"
```

The `.gitignore` file prevents this local secrets file from being committed.

For Streamlit Community Cloud, open the app's **Settings**, select **Secrets**, and add the same line there. Do not upload `secrets.toml` to GitHub.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Audit limitation

Search results and generated queries identify potential exceptions. They do not establish that a policy violation, processing error, or fraud occurred.
