# Ho PullData Streamlit

Streamlit migration of the existing `pulldata-app-python` LMS export app.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Configure `.env` or `.streamlit/secrets.toml` locally. Do not commit either
file. The Cloud deployment uses the same keys in Streamlit Secrets, especially
`LMS_REFRESH_TOKEN` and `LMS_FIREBASE_API_KEY`.

## Deploy on Streamlit Community Cloud

Deploy `app.py` from this repository. Use the same Python version locally and
in Cloud, then paste the secrets into the app's Advanced settings. Keep the app
private when it accesses LMS data.

See `AGENTS.md` for the complete implementation plan, UI kit, compatibility
contract, and agent workflow.
