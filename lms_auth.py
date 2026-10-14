import base64
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
DEFAULT_APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "MindX PullData"
LEGACY_APP_DATA_DIR = SCRIPT_DIR
APP_DATA_DIR = Path(os.getenv("MINDX_PULLDATA_APP_DATA_DIR", str(DEFAULT_APP_DATA_DIR))).expanduser()
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC_TZ = ZoneInfo("UTC")

LMS_WEB_URL = os.getenv("LMS_WEB_URL", "https://lms.mindx.edu.vn")
LMS_API_URL = os.getenv("LMS_API_URL", "https://lms-api.mindx.edu.vn")
LMS_GRAPHQL_URL = os.getenv("LMS_GRAPHQL_URL", f"{LMS_API_URL}/graphql")
FIREBASE_PROJECT_ID = os.getenv("LMS_FIREBASE_PROJECT_ID", "mindx-edu-prod").strip()
BASE_API_URLS = tuple(
    url.strip()
    for url in os.getenv(
        "LMS_BASE_API_URLS",
        "https://base-api.mindx.edu.vn,https://base-api.mindx.edu.vn/graphql",
    ).split(",")
    if url.strip()
)
FIREBASE_API_KEY = os.getenv(
    "LMS_FIREBASE_API_KEY",
    "",
).strip()
_FIREBASE_API_KEY_CACHE = ""
_FIREBASE_API_KEY_CANDIDATES_CACHE: list[str] = []
_FIREBASE_API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_JWT_PATTERN = re.compile(r"eyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+")
_REFRESH_TOKEN_PATTERNS = (
    re.compile(r'''"refreshToken"\s*:\s*"([^"]+)"'''),
    re.compile(r'''\\"refreshToken\\"\s*:\s*\\"([^"\\]+)\\"'''),
)

TOKEN_CACHE_PATH = Path(
    os.getenv("LMS_TOKEN_CACHE", str(APP_DATA_DIR / ".lms_token_cache.json"))
).expanduser()
BROWSER_PROFILE_DIR = Path(
    os.getenv("LMS_BROWSER_PROFILE", str(APP_DATA_DIR / ".lms_browser"))
).expanduser()
LEGACY_TOKEN_CACHE_PATH = LEGACY_APP_DATA_DIR / ".lms_token_cache.json"
LEGACY_BROWSER_PROFILE_DIR = LEGACY_APP_DATA_DIR / ".lms_browser"
LOGIN_TIMEOUT_SECONDS = int(os.getenv("LMS_LOGIN_TIMEOUT_SECONDS", "900"))
TOKEN_STORAGE_WAIT_SECONDS = int(os.getenv("LMS_TOKEN_STORAGE_WAIT_SECONDS", "18"))
TOKEN_STORAGE_FALLBACK_WAIT_SECONDS = int(os.getenv("LMS_TOKEN_STORAGE_FALLBACK_WAIT_SECONDS", "45"))

AUTH_ENV_NAMES = ("LMS_AUTH_TOKEN", "AUTH_TOKEN", "TOKEN")
COOKIE_ENV_NAMES = ("LMS_BASE_COOKIE", "BASE_COOKIE", "LMS_COOKIE", "COOKIE")

GET_CUSTOM_TOKEN_PAYLOAD = {
    "operationName": "GetCustomToken",
    "variables": {},
    "query": "mutation GetCustomToken{users{getCustomToken{customToken}}}",
}
VERIFY_LMS_TOKEN_PAYLOAD = {
    "operationName": "VerifyPullDataToken",
    "variables": {
        "pageIndex": 0,
        "itemsPerPage": 1,
        "orderBy": "createdAt_desc",
    },
    "query": (
        "query VerifyPullDataToken($pageIndex: Int!, $itemsPerPage: Int!, $orderBy: String) {"
        " centres(payload: {pageIndex: $pageIndex, itemsPerPage: $itemsPerPage, orderBy: $orderBy}) {"
        " pagination { total __typename } __typename } }"
    ),
}

TOKEN_HELP = (
    "Không lấy được token LMS hợp lệ. Bấm Đăng nhập trong app để mở LMS, "
    "hoặc đặt LMS_AUTH_TOKEN / LMS_BASE_COOKIE."
)


class AuthError(RuntimeError):
    pass


def normalize_auth_token(token):
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def decode_jwt_payload(token):
    token = normalize_auth_token(token)
    parts = token.split(".")
    if len(parts) < 2:
        return {}

    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def account_email_from_token(token):
    payload = decode_jwt_payload(token)
    candidates = [
        payload.get("email"),
        payload.get("mail"),
        payload.get("preferred_username"),
    ]

    firebase_payload = payload.get("firebase") if isinstance(payload.get("firebase"), dict) else {}
    identities = firebase_payload.get("identities") if isinstance(firebase_payload.get("identities"), dict) else {}
    for key in ("email", "mail", "preferred_username"):
        value = identities.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        else:
            candidates.append(value)

    for value in candidates:
        text = str(value or "").strip()
        if "@" in text:
            return text
    return ""


def token_expires_at(token):
    payload = decode_jwt_payload(token)
    expires_at = payload.get("exp")
    try:
        return int(expires_at) if expires_at else None
    except (TypeError, ValueError):
        return None


def is_token_valid(token, skew_seconds=120):
    token = normalize_auth_token(token)
    if not token:
        return False

    expires_at = token_expires_at(token)
    if expires_at is None:
        return True

    return int(time.time()) + skew_seconds < expires_at


def is_lms_id_token(token):
    payload = decode_jwt_payload(token)
    audience = str(payload.get("aud") or "")
    issuer = str(payload.get("iss") or "")
    return audience == FIREBASE_PROJECT_ID or FIREBASE_PROJECT_ID in issuer


def find_lms_id_token(text):
    for token in _JWT_PATTERN.findall(str(text or "")):
        token = normalize_auth_token(token)
        if is_lms_id_token(token) and is_token_valid(token, skew_seconds=30):
            return token
    return ""


def find_refresh_token(text):
    for pattern in _REFRESH_TOKEN_PATTERNS:
        match = pattern.search(str(text or ""))
        if match:
            return match.group(1)
    return ""


def format_token_expiry(token):
    expires_at = token_expires_at(token)
    if not expires_at:
        return "không rõ hạn"
    return datetime.fromtimestamp(expires_at, tz=UTC_TZ).astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S VN")


def build_auth_headers(token=None):
    token = normalize_auth_token(token or get_auth_token())
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": LMS_WEB_URL,
        "Referer": f"{LMS_WEB_URL}/",
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }


def verify_lms_token(token):
    if os.getenv("LMS_SKIP_TOKEN_VERIFY") == "1":
        return

    token = normalize_auth_token(token)
    if not is_lms_id_token(token):
        raise AuthError(f"Token không thuộc Firebase project {FIREBASE_PROJECT_ID}.")

    try:
        response = requests.post(
            f"{LMS_API_URL.rstrip('/')}/",
            headers=build_auth_headers(token),
            json=VERIFY_LMS_TOKEN_PAYLOAD,
            timeout=(8, 20),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise AuthError(f"Token không gọi được LMS API: {summarize_http_error(exc)}") from exc

    api_errors = payload.get("errors") if isinstance(payload, dict) else None
    if api_errors:
        raise AuthError(f"Token không gọi được LMS API: {summarize_graphql_errors(api_errors)}")


def summarize_graphql_errors(errors):
    summaries = []
    for error in errors or []:
        if not isinstance(error, dict):
            summaries.append(str(error))
            continue

        message = error.get("message") or "GraphQL error"
        code = (error.get("extensions") or {}).get("code")
        summaries.append(f"{message} ({code})" if code else message)

    return "; ".join(summaries)


def summarize_http_error(error):
    response = getattr(error, "response", None)
    if response is None:
        return str(error)

    message = ""
    try:
        payload = response.json()
        api_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(api_error, dict):
            message = str(api_error.get("message") or api_error.get("status") or "").strip()
    except Exception:
        message = response.text[:200].strip()

    if message == "TOKEN_EXPIRED":
        return "Refresh token đã hết hạn. Cần đăng nhập LMS lại để tạo phiên mới."
    if message:
        return f"HTTP {response.status_code}: {message}"
    return f"HTTP {response.status_code}: {error}"


def playwright_install_hint():
    python_cmd = f'"{sys.executable}"'
    return (
        "Chưa có Playwright/Chromium cho Python đang chạy "
        f"({sys.executable}). Cài một lần bằng: "
        f"`{python_cmd} -m pip install playwright && {python_cmd} -m playwright install chromium`."
    )


def _add_unique(items, value):
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


def _firebase_key_score(text, start_index):
    source = str(text or "")
    window = source[max(0, start_index - 4000): start_index + 4000]
    compact_window = window.replace("\\", "")
    lower_window = compact_window.lower()
    score = 0
    if FIREBASE_PROJECT_ID and FIREBASE_PROJECT_ID in compact_window:
        score += 120
    if "projectid" in lower_window:
        score += 60
    if "authdomain" in lower_window:
        score += 45
    if "firebase" in lower_window:
        score += 30
    if "apikey" in lower_window:
        score += 20
    if "messagingsenderid" in lower_window or "appid" in lower_window:
        score += 10
    if "maps.googleapis" in lower_window or "google maps" in lower_window:
        score -= 80
    return score


def extract_firebase_api_key_candidates(text):
    candidates = []
    seen = set()
    source = str(text or "")
    for match in _FIREBASE_API_KEY_PATTERN.finditer(source):
        key = match.group(0)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((_firebase_key_score(source, match.start()), match.start(), key))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [key for score, _, key in candidates if score > -50]


def extract_firebase_api_key(text):
    candidates = extract_firebase_api_key_candidates(text)
    return candidates[0] if candidates else ""


def fetch_firebase_api_key_candidates_from_lms_assets():
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        response = requests.get(LMS_WEB_URL, headers=headers, timeout=(5, 15))
        response.raise_for_status()
    except Exception:
        return []

    html = response.text
    weighted_candidates = []
    seen_candidates = set()

    def add_candidates(source_text, source_offset=0):
        for index, key in enumerate(extract_firebase_api_key_candidates(source_text)):
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            weighted_candidates.append((_firebase_key_score(source_text, source_text.find(key)), source_offset + index, key))

    add_candidates(html)

    asset_urls = []
    seen_urls = set()
    for asset_path in re.findall(r"""(?:src|href)=["']([^"']+\.js(?:\?[^"']*)?)["']""", html, flags=re.I):
        asset_url = urljoin(f"{LMS_WEB_URL}/", asset_path)
        if asset_url in seen_urls:
            continue
        seen_urls.add(asset_url)
        asset_urls.append(asset_url)

    asset_headers = {
        "Accept": "application/javascript,text/javascript,*/*;q=0.8",
        "Referer": f"{LMS_WEB_URL}/",
        "User-Agent": "Mozilla/5.0",
    }
    for asset_url in asset_urls[:25]:
        try:
            response = requests.get(asset_url, headers=asset_headers, timeout=(5, 20))
            response.raise_for_status()
        except Exception:
            continue

        add_candidates(response.text, len(weighted_candidates) + 1)

    weighted_candidates.sort(key=lambda item: (-item[0], item[1]))
    return [key for _, _, key in weighted_candidates]


def fetch_firebase_api_key_from_lms_assets():
    candidates = fetch_firebase_api_key_candidates_from_lms_assets()
    return candidates[0] if candidates else ""


def resolve_firebase_api_key_candidates(force_refresh=False, include_env=True):
    global FIREBASE_API_KEY, _FIREBASE_API_KEY_CACHE, _FIREBASE_API_KEY_CANDIDATES_CACHE

    keys = []

    env_key = os.getenv("LMS_FIREBASE_API_KEY", "").strip()
    if include_env and env_key:
        _add_unique(keys, env_key)
        FIREBASE_API_KEY = env_key

    if FIREBASE_API_KEY:
        _add_unique(keys, FIREBASE_API_KEY)

    if _FIREBASE_API_KEY_CACHE:
        _add_unique(keys, _FIREBASE_API_KEY_CACHE)

    if force_refresh or not _FIREBASE_API_KEY_CANDIDATES_CACHE:
        _FIREBASE_API_KEY_CANDIDATES_CACHE = fetch_firebase_api_key_candidates_from_lms_assets()

    for api_key in _FIREBASE_API_KEY_CANDIDATES_CACHE:
        _add_unique(keys, api_key)

    if keys:
        return keys

    raise AuthError(
        "Không tìm thấy Firebase API key của LMS. Kiểm tra kết nối mạng "
        "hoặc đặt LMS_FIREBASE_API_KEY trong file .env."
    )


def resolve_firebase_api_key():
    api_key = resolve_firebase_api_key_candidates()[0]
    remember_firebase_api_key(api_key)
    return api_key


def remember_firebase_api_key(api_key):
    global FIREBASE_API_KEY, _FIREBASE_API_KEY_CACHE
    api_key = str(api_key or "").strip()
    if not api_key:
        return
    FIREBASE_API_KEY = api_key
    _FIREBASE_API_KEY_CACHE = api_key


def load_token_cache():
    for cache_path in token_cache_candidates():
        if not cache_path.exists():
            continue

        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if cache_path != TOKEN_CACHE_PATH:
            save_token_cache(cache)
        return cache

    return {}


def token_cache_candidates():
    candidates = [TOKEN_CACHE_PATH]
    if LEGACY_TOKEN_CACHE_PATH != TOKEN_CACHE_PATH:
        candidates.append(LEGACY_TOKEN_CACHE_PATH)
    return candidates


def get_cached_account_email():
    cache = load_token_cache()
    email = str(cache.get("account_email") or "").strip()
    if email:
        return email
    return account_email_from_token(cache.get("id_token", ""))


def save_token_cache(cache):
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        TOKEN_CACHE_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def clear_saved_auth(remove_browser_profile=True):
    """Clear locally cached LMS credentials so another account can sign in."""

    removed = []
    for cache_path in token_cache_candidates():
        if cache_path.exists():
            cache_path.unlink()
            removed.append(cache_path)

    if remove_browser_profile:
        for profile_dir in browser_profile_candidates():
            if profile_dir.exists():
                if profile_dir.is_dir() and not profile_dir.is_symlink():
                    shutil.rmtree(profile_dir)
                else:
                    profile_dir.unlink()
                removed.append(profile_dir)

    return removed


def browser_profile_candidates():
    candidates = [BROWSER_PROFILE_DIR]
    if LEGACY_BROWSER_PROFILE_DIR != BROWSER_PROFILE_DIR:
        candidates.append(LEGACY_BROWSER_PROFILE_DIR)
    return candidates


def get_env_token():
    for env_name in AUTH_ENV_NAMES:
        token = normalize_auth_token(os.getenv(env_name, ""))
        if is_token_valid(token):
            return token
    return ""


def get_cookie_header_from_env():
    for env_name in COOKIE_ENV_NAMES:
        value = os.getenv(env_name, "").strip()
        if value:
            return value

    cookie_file = os.getenv("LMS_COOKIE_FILE", "").strip()
    if cookie_file:
        return read_cookie_file(cookie_file)

    return ""


def read_cookie_file(path):
    cookie_path = Path(path).expanduser()
    try:
        raw = cookie_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

    if not raw:
        return ""

    if "\t" not in raw:
        return raw

    now = int(time.time())
    pairs = []
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, _, _, _, expires_at, name, value = parts[:7]
        if "mindx.edu.vn" not in domain:
            continue

        try:
            if int(expires_at) and int(expires_at) < now:
                continue
        except ValueError:
            pass

        pairs.append(f"{name}={value}")

    return "; ".join(pairs)


def post_get_custom_token(cookie_header):
    if not cookie_header:
        raise AuthError("Thiếu session cookie của Base/LMS.")

    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": LMS_WEB_URL,
        "Referer": f"{LMS_WEB_URL}/",
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_header,
    }

    errors = []
    for url in BASE_API_URLS:
        try:
            response = requests.post(
                url,
                headers=headers,
                json=GET_CUSTOM_TOKEN_PAYLOAD,
                timeout=(10, 30),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        users_payload = (payload.get("data") or {}).get("users") or {}
        custom_token = (users_payload.get("getCustomToken") or {}).get("customToken")
        if custom_token:
            return custom_token

        if payload.get("errors"):
            errors.append(f"{url}: {summarize_graphql_errors(payload['errors'])}")

    raise AuthError("Không lấy được custom token từ Base API. " + " | ".join(errors[-2:]))


def _dedupe_error_messages(messages):
    result = []
    for message in messages:
        message = str(message or "").strip()
        if message and message not in result:
            result.append(message)
    return result


def _exchange_custom_token_with_key(custom_token, firebase_api_key):
    response = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={firebase_api_key}",
        json={"token": custom_token, "returnSecureToken": True},
        timeout=(10, 30),
    )
    response.raise_for_status()
    return response.json()


def exchange_custom_token(custom_token):
    errors = []
    for firebase_api_key in resolve_firebase_api_key_candidates():
        try:
            payload = _exchange_custom_token_with_key(custom_token, firebase_api_key)
        except Exception as exc:
            errors.append(summarize_http_error(exc))
            continue

        id_token = normalize_auth_token(payload.get("idToken", ""))
        refresh_token = payload.get("refreshToken", "")
        if not id_token:
            errors.append("Firebase không trả idToken.")
            continue
        if not is_lms_id_token(id_token):
            errors.append(f"Firebase trả token không thuộc project {FIREBASE_PROJECT_ID}.")
            continue
        try:
            verify_lms_token(id_token)
        except AuthError as exc:
            errors.append(str(exc))
            continue

        remember_firebase_api_key(firebase_api_key)
        save_token_payload(id_token, refresh_token, "custom_token")
        return id_token

    refresh_errors = []
    if any("CREDENTIAL_MISMATCH" in error for error in errors):
        for firebase_api_key in resolve_firebase_api_key_candidates(force_refresh=True, include_env=False):
            try:
                payload = _exchange_custom_token_with_key(custom_token, firebase_api_key)
            except Exception as exc:
                refresh_errors.append(summarize_http_error(exc))
                continue

            id_token = normalize_auth_token(payload.get("idToken", ""))
            refresh_token = payload.get("refreshToken", "")
            if not id_token:
                refresh_errors.append("Firebase không trả idToken.")
                continue
            if not is_lms_id_token(id_token):
                refresh_errors.append(f"Firebase trả token không thuộc project {FIREBASE_PROJECT_ID}.")
                continue
            try:
                verify_lms_token(id_token)
            except AuthError as exc:
                refresh_errors.append(str(exc))
                continue
            remember_firebase_api_key(firebase_api_key)
            save_token_payload(id_token, refresh_token, "custom_token")
            return id_token

    details = " | ".join(_dedupe_error_messages(errors + refresh_errors)[-4:])
    raise AuthError(f"Không đổi được custom token Firebase: {details}")


def _refresh_id_token_with_key(refresh_token, firebase_api_key):
    response = requests.post(
        f"https://securetoken.googleapis.com/v1/token?key={firebase_api_key}",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=(10, 30),
    )
    response.raise_for_status()
    return response.json()


def refresh_id_token(refresh_token):
    errors = []
    for firebase_api_key in resolve_firebase_api_key_candidates():
        try:
            payload = _refresh_id_token_with_key(refresh_token, firebase_api_key)
        except Exception as exc:
            errors.append(summarize_http_error(exc))
            continue

        id_token = normalize_auth_token(payload.get("id_token", ""))
        if not id_token:
            errors.append("Firebase không trả id_token khi refresh.")
            continue
        if not is_lms_id_token(id_token):
            errors.append(f"Firebase trả token không thuộc project {FIREBASE_PROJECT_ID}.")
            continue
        try:
            verify_lms_token(id_token)
        except AuthError as exc:
            errors.append(str(exc))
            continue

        remember_firebase_api_key(firebase_api_key)
        save_token_payload(
            id_token,
            payload.get("refresh_token") or refresh_token,
            "refresh_token",
        )
        return id_token

    details = " | ".join(_dedupe_error_messages(errors)[-4:])
    raise AuthError(f"Không refresh được Firebase token: {details}")


def save_token_payload(id_token, refresh_token="", source="unknown"):
    account_email = account_email_from_token(id_token)
    cache = {
        "id_token": normalize_auth_token(id_token),
        "refresh_token": refresh_token,
        "expires_at": token_expires_at(id_token),
        "source": source,
        "updated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }
    if account_email:
        cache["account_email"] = account_email
    save_token_cache(cache)


def get_token_from_cache(force_refresh=False):
    return get_token_from_cache_with_errors(force_refresh=force_refresh)[0]


def get_token_from_cache_with_errors(force_refresh=False):
    errors = []
    cache = load_token_cache()
    id_token = normalize_auth_token(cache.get("id_token", ""))
    if not force_refresh and is_token_valid(id_token):
        return id_token, errors

    if id_token and not is_token_valid(id_token):
        errors.append(f"Token cache đã hết hạn lúc {format_token_expiry(id_token)}.")

    refresh_token = cache.get("refresh_token")
    if refresh_token:
        try:
            return refresh_id_token(refresh_token), errors
        except Exception as exc:
            errors.append(f"Không refresh được token: {summarize_http_error(exc)}")
            return "", errors

    if cache:
        errors.append("Cache không có refresh token để gia hạn.")

    return "", errors


def get_token_from_cookie():
    cookie_header = get_cookie_header_from_env()
    if not cookie_header:
        return ""

    custom_token = post_get_custom_token(cookie_header)
    return exchange_custom_token(custom_token)


def configure_playwright_browser_path():
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return

    if IS_FROZEN:
        bundled_browsers = Path(sys.executable).resolve().parents[1] / "Resources" / "ms-playwright"
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)
        return

    playwright_spec = importlib.util.find_spec("playwright")
    if not playwright_spec or not playwright_spec.origin:
        return

    local_browsers = Path(playwright_spec.origin).parent / "driver" / "package" / ".local-browsers"
    if local_browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"


def get_custom_token_from_playwright_context(context):
    errors = []
    cookie_header = get_cookie_header_from_playwright_context(context)
    for url in BASE_API_URLS:
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Origin": LMS_WEB_URL,
                "Referer": f"{LMS_WEB_URL}/",
            }
            if cookie_header:
                headers["Cookie"] = cookie_header
            response = context.request.post(
                url,
                headers=headers,
                data=json.dumps(GET_CUSTOM_TOKEN_PAYLOAD),
                timeout=30000,
            )
            payload = response.json()
            users_payload = (payload.get("data") or {}).get("users") or {}
            custom_token = (users_payload.get("getCustomToken") or {}).get("customToken")
            if custom_token:
                return custom_token, []

            api_errors = payload.get("errors")
            error_text = summarize_graphql_errors(api_errors) if api_errors else response.status
            errors.append(f"{url}: {error_text}")
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    return None, errors


def get_cookie_header_from_playwright_context(context):
    cookies = []
    seen_names = set()
    for url in (LMS_WEB_URL, "https://base.mindx.edu.vn", "https://base-api.mindx.edu.vn"):
        try:
            cookies.extend(context.cookies(url))
        except Exception:
            continue

    pairs = []
    for cookie in cookies:
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if not name or not value or name in seen_names:
            continue
        seen_names.add(name)
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def get_lms_token_from_playwright_storage(context):
    storage_script = """
    async () => {
      const values = [];
      const pushValue = (value) => {
        if (value === undefined || value === null) return;
        try {
          const text = typeof value === "string" ? value : JSON.stringify(value);
          if (text) values.push(text.slice(0, 12000));
        } catch (_) {}
      };

      try {
        for (let i = 0; i < localStorage.length; i += 1) {
          const key = localStorage.key(i);
          pushValue(key);
          pushValue(localStorage.getItem(key));
        }
      } catch (_) {}

      try {
        for (let i = 0; i < sessionStorage.length; i += 1) {
          const key = sessionStorage.key(i);
          pushValue(key);
          pushValue(sessionStorage.getItem(key));
        }
      } catch (_) {}

      const openDb = (name) => new Promise((resolve) => {
        try {
          const request = indexedDB.open(name);
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => resolve(null);
          request.onblocked = () => resolve(null);
        } catch (_) {
          resolve(null);
        }
      });

      const readStore = (db, storeName) => new Promise((resolve) => {
        try {
          const tx = db.transaction(storeName, "readonly");
          const store = tx.objectStore(storeName);
          const request = store.getAll();
          request.onsuccess = () => resolve(request.result || []);
          request.onerror = () => resolve([]);
        } catch (_) {
          resolve([]);
        }
      });

      try {
        if (indexedDB && indexedDB.databases) {
          const databases = await indexedDB.databases();
          for (const info of databases || []) {
            if (!info || !info.name) continue;
            const db = await openDb(info.name);
            if (!db) continue;
            for (const storeName of Array.from(db.objectStoreNames || [])) {
              const rows = await readStore(db, storeName);
              for (const row of rows || []) pushValue(row);
            }
            db.close();
          }
        }
      } catch (_) {}

      return values.slice(0, 250);
    }
    """

    errors = []
    for page in list(context.pages):
        try:
            values = page.evaluate(storage_script)
        except Exception as exc:
            errors.append(str(exc))
            continue

        for value in values or []:
            text = str(value or "")
            id_token = find_lms_id_token(text)
            if id_token:
                return id_token, find_refresh_token(text), []

    return "", "", errors


def get_token_from_web_login():
    configure_playwright_browser_path()

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AuthError(playwright_install_hint()) from exc

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print("Đang mở LMS. Nếu thấy màn hình login, hãy đăng nhập như trên web bình thường.")
    print("Tool sẽ tự nhận diện khi đăng nhập xong và lưu token.")

    id_token = ""
    refresh_token = ""
    custom_token = None
    custom_token_seen_at = None
    captured_request_tokens = []
    exchange_attempted = False
    exchange_error = ""
    fallback_wait_until = None
    token_already_saved = False
    errors = []

    try:
        with sync_playwright() as playwright:
            context = None
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(BROWSER_PROFILE_DIR),
                    headless=False,
                )

                def capture_request_token(request):
                    try:
                        host = getattr(request, "url", "")
                        if "mindx.edu.vn" not in host:
                            return
                        headers = request.headers
                        auth_header = headers.get("authorization") or headers.get("Authorization") or ""
                        token = normalize_auth_token(auth_header)
                        if token and is_lms_id_token(token) and is_token_valid(token, skew_seconds=30):
                            _add_unique(captured_request_tokens, token)
                    except Exception:
                        return

                context.on("request", capture_request_token)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(f"{LMS_WEB_URL}/admin", wait_until="domcontentloaded")

                deadline = time.time() + LOGIN_TIMEOUT_SECONDS
                while time.time() < deadline:
                    if captured_request_tokens:
                        id_token = captured_request_tokens[-1]
                        _, refresh_token, _ = get_lms_token_from_playwright_storage(context)
                        print("Đã bắt được token LMS từ request web.")
                        break

                    id_token, refresh_token, storage_errors = get_lms_token_from_playwright_storage(context)
                    if id_token:
                        break
                    if storage_errors:
                        errors.extend(storage_errors[-2:])

                    if not custom_token:
                        custom_token, custom_errors = get_custom_token_from_playwright_context(context)
                        if custom_errors:
                            errors.extend(custom_errors[-2:])
                        if custom_token:
                            custom_token_seen_at = time.time()
                            print("Đã nhận phiên LMS. Đang chờ LMS lưu token xác thực...")

                    if custom_token and custom_token_seen_at:
                        if (
                            not exchange_attempted
                            and time.time() - custom_token_seen_at >= TOKEN_STORAGE_WAIT_SECONDS
                        ):
                            exchange_attempted = True
                            try:
                                id_token = exchange_custom_token(custom_token)
                                token_already_saved = True
                                break
                            except AuthError as exc:
                                exchange_error = str(exc)
                                errors.append(exchange_error)
                                fallback_wait_until = time.time() + TOKEN_STORAGE_FALLBACK_WAIT_SECONDS
                                print("Custom token chưa đổi được. Tiếp tục chờ token từ phiên web LMS...")

                        if fallback_wait_until and time.time() >= fallback_wait_until:
                            break

                    time.sleep(2)
            finally:
                if context is not None:
                    context.close()
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message.lower():
            raise AuthError(playwright_install_hint()) from exc
        raise AuthError(f"Không mở được trình duyệt đăng nhập LMS: {message[:500]}") from exc

    if id_token:
        if not token_already_saved:
            verify_lms_token(id_token)
            save_token_payload(id_token, refresh_token, "web_login")
        return id_token

    if exchange_error:
        raise AuthError(exchange_error)

    if not custom_token:
        raise AuthError("Không lấy được custom token từ phiên web. " + " | ".join(errors[-2:]))

    return exchange_custom_token(custom_token)


def get_auth_token(auto_login=False, force_refresh=False):
    if not force_refresh:
        env_token = get_env_token()
        if env_token:
            return env_token

    cache_token, cache_errors = get_token_from_cache_with_errors(force_refresh=force_refresh)
    if cache_token:
        return cache_token

    cookie_error = None
    try:
        cookie_token = get_token_from_cookie()
    except Exception as exc:
        cookie_error = exc
        cookie_token = ""

    if cookie_token:
        return cookie_token

    if auto_login:
        return get_token_from_web_login()

    if cache_errors:
        raise AuthError("\n".join(cache_errors + [TOKEN_HELP]))

    if cookie_error:
        raise AuthError(f"{cookie_error}\n{TOKEN_HELP}")

    raise AuthError(TOKEN_HELP)


def ensure_auth_token(auto_login=False, force_refresh=False):
    token = get_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    if not is_token_valid(token):
        raise AuthError(TOKEN_HELP)
    return token


def auth_debug_lines():
    cache = load_token_cache()
    id_token = normalize_auth_token(cache.get("id_token", ""))
    refresh_token = cache.get("refresh_token", "")
    lines = [
        f"APP_DATA_DIR: {APP_DATA_DIR}",
        f"TOKEN_CACHE_PATH: {TOKEN_CACHE_PATH} · exists={TOKEN_CACHE_PATH.exists()}",
        f"LEGACY_TOKEN_CACHE_PATH: {LEGACY_TOKEN_CACHE_PATH} · exists={LEGACY_TOKEN_CACHE_PATH.exists()}",
        f"BROWSER_PROFILE_DIR: {BROWSER_PROFILE_DIR} · exists={BROWSER_PROFILE_DIR.exists()}",
        f"LEGACY_BROWSER_PROFILE_DIR: {LEGACY_BROWSER_PROFILE_DIR} · exists={LEGACY_BROWSER_PROFILE_DIR.exists()}",
    ]
    for name in AUTH_ENV_NAMES:
        lines.append(f"{name}: {'set' if os.getenv(name, '') else 'empty'}")
    for name in COOKIE_ENV_NAMES:
        lines.append(f"{name}: {'set' if os.getenv(name, '') else 'empty'}")
    lines.extend([
        f"cache_loaded: {bool(cache)}",
        f"cache_source: {cache.get('source') or ''}",
        f"cache_updated_at: {cache.get('updated_at') or ''}",
        f"cache_account_email: {cache.get('account_email') or account_email_from_token(id_token) or ''}",
        f"id_token_present: {bool(id_token)}",
        f"id_token_valid: {is_token_valid(id_token)}",
        f"id_token_expiry: {format_token_expiry(id_token) if id_token else ''}",
        f"refresh_token_present: {bool(refresh_token)}",
    ])
    return lines
