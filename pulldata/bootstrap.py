from __future__ import annotations

import os
from typing import Any


SECRET_ENV_NAMES = (
    "LMS_WEB_URL",
    "LMS_API_URL",
    "LMS_GRAPHQL_URL",
    "LMS_FIREBASE_PROJECT_ID",
    "LMS_FIREBASE_API_KEY",
    "LMS_AUTH_TOKEN",
    "LMS_REFRESH_TOKEN",
)


def configure_from_streamlit_secrets(secrets: Any = None) -> None:
    """Expose non-UI secrets to the legacy exporters without logging values."""
    if secrets is None:
        try:
            import streamlit as st
            secrets = st.secrets
        except Exception:
            secrets = {}
    for name in SECRET_ENV_NAMES:
        try:
            value = secrets.get(name, "")
        except (AttributeError, KeyError, FileNotFoundError, RuntimeError):
            value = ""
        if value and not os.getenv(name):
            os.environ[name] = str(value)

