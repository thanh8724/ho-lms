from __future__ import annotations

import os
from dataclasses import dataclass

from pulldata.bootstrap import configure_from_streamlit_secrets


@dataclass
class AuthState:
    token: str = ""
    email: str = ""
    expiry: str = ""
    error: str = ""


class AuthService:
    def __init__(self, session_state):
        self.state = session_state.setdefault("auth_state", AuthState())

    def _module(self):
        import lms_auth
        return lms_auth

    def ensure_token(self, force_refresh: bool = False) -> str:
        configure_from_streamlit_secrets()
        auth = self._module()
        token = self.state.token
        if not force_refresh and token and auth.is_token_valid(token):
            os.environ["LMS_AUTH_TOKEN"] = token
            return token

        try:
            refresh_token = os.getenv("LMS_REFRESH_TOKEN", "").strip()
            if refresh_token:
                token = auth.refresh_id_token(refresh_token)
            else:
                token = auth.ensure_auth_token(auto_login=False, force_refresh=force_refresh)
            self.state.token = token
            self.state.email = auth.account_email_from_token(token) or auth.get_cached_account_email()
            self.state.expiry = auth.format_token_expiry(token)
            self.state.error = ""
            os.environ["LMS_AUTH_TOKEN"] = token
            return token
        except Exception as exc:
            self.state.error = str(exc)
            raise

    def check(self, force_refresh: bool = False) -> AuthState:
        self.ensure_token(force_refresh=force_refresh)
        return self.state

    def logout(self) -> None:
        self.state.token = ""
        self.state.email = ""
        self.state.expiry = ""
        self.state.error = ""
        os.environ.pop("LMS_AUTH_TOKEN", None)
