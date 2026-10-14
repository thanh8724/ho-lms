import argparse
import base64
import builtins
from concurrent.futures import ThreadPoolExecutor, as_completed
import functools
import json
import re
import os
import threading
import time
import unicodedata
from datetime import date, datetime, time as dt_time
from html import unescape
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv

from lms_auth import (
    build_auth_headers,
    ensure_auth_token,
)

load_dotenv()

print = functools.partial(builtins.print, flush=True)

DEFAULT_AUTH_TOKEN = ""
AUTH_TOKEN = (os.getenv("AUTH_TOKEN") or os.getenv("TOKEN") or DEFAULT_AUTH_TOKEN).strip()
AUTH_HEADER_VALUE = AUTH_TOKEN[7:].strip() if AUTH_TOKEN.lower().startswith("bearer ") else AUTH_TOKEN

API_URL = "https://lms-api.mindx.edu.vn/"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC_TZ = ZoneInfo("UTC")

HEADERS = {
    "Authorization": AUTH_HEADER_VALUE,
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://lms.mindx.edu.vn",
    "Referer": "https://lms.mindx.edu.vn/",
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_CLASS_STATUSES = ("RUNNING", "FINISHED")
CLASS_STATUS_FILTER_CANDIDATES = ("RUNNING", "FINISHED", "PENDING", "OPENING", "CLOSED")
DEFAULT_SESSION_NUMBERS = (12, 13)
DEFAULT_START_DATE = "2026-06-01"


def int_env(name, default, minimum=1):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def float_env(name, default, minimum=0.0):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


ITEMS_PER_PAGE = int_env("PRODUCT_CLASSES_PER_PAGE", 80)
SLOT_SUMMARIES_PER_PAGE = int_env("PRODUCT_SLOT_SUMMARIES_PER_PAGE", 500)
CLASS_DETAIL_CHUNK_SIZE = int_env("PRODUCT_CLASS_DETAIL_CHUNK_SIZE", 25)
WORK_SLOT_BATCH_SIZE = int_env("PRODUCT_WORK_SLOT_BATCH_SIZE", 30)
CLASS_DETAIL_WORKERS = int_env("PRODUCT_CLASS_DETAIL_WORKERS", 4)
WORK_FETCH_WORKERS = int_env("PRODUCT_WORK_FETCH_WORKERS", 6)
REQUEST_POOL_SIZE = int_env(
    "PRODUCT_REQUEST_POOL_SIZE",
    max(CLASS_DETAIL_WORKERS, WORK_FETCH_WORKERS, 4) + 2,
)
REQUEST_DELAY_SECONDS = float_env("PRODUCT_REQUEST_DELAY_SECONDS", 0.0)
REQUEST_RETRIES = 5
RETRY_STATUS_CODES = {500, 502, 503, 504}
RETRY_GRAPHQL_CODES = {"UNAVAILABLE", "INTERNAL_SERVER_ERROR"}
PRODUCT_AREA_KEYWORDS = ("san pham", "sanpham", "demo", "project", "final", "file")
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
HTTP_LOCAL = threading.local()
KHOI_CODE_MAP = {
    "XART": "XART",
    "C4K": "C4K",
    "ROB": "ROB",
    "KIND": "ROB",
    "CSB": "C4K",
    "CSA": "C4K",
    "CSI": "C4K",
    "JSB": "C4K",
    "JSA": "C4K",
    "JSI": "C4K",
}

FIND_STUDENT_WORKS_QUERY = """
query findAllStudentWorks($studentId: String, $classSessionId: String, $classId: String, $classIds: [String]) {
  findAllStudentWorks(payload: {
    studentId_equals: $studentId,
    classSessionId_equals: $classSessionId,
    classId_equals: $classId,
    classId_in: $classIds
  }) {
    data {
      id
      status
      studentId
      classSessionId
      classId
      version
      displayOrder
      latestData {
        title
        thumbnail
        videoUrls
        imageUrl
        attachmentUrls
        comment
        rejectReason
        relatedUrls {
          name
          url
        }
      }
      createdBy {
        displayName
      }
      createdAt
      lastModifiedBy {
        displayName
      }
      lastModifiedAt
    }
  }
}
"""

STUDENT_WORK_FIELDS = """
id
status
studentId
classSessionId
classId
version
displayOrder
latestData {
  title
  thumbnail
  videoUrls
  imageUrl
  attachmentUrls
  comment
  rejectReason
  relatedUrls {
    name
    url
  }
}
createdBy {
  displayName
}
createdAt
lastModifiedBy {
  displayName
}
lastModifiedAt
"""

DETAIL_COLUMNS = [
    "Ngày xuất",
    "Ngày buổi học",
    "Giờ buổi học",
    "Buổi số",
    "Mã lớp",
    "Course",
    "Course line",
    "Khối",
    "Trạng thái lớp",
    "Cơ sở",
    "Slot ID",
    "Tên học viên",
    "Mã học viên",
    "Student ID nội bộ",
    "Trạng thái học viên trong lớp",
    "Trạng thái điểm danh",
    "Nhận xét học viên",
    "Có vùng sản phẩm/demo",
    "Vùng sản phẩm/demo",
    "Link trong nhận xét",
    "Trạng thái nộp sản phẩm",
    "Có sản phẩm",
    "Số thứ tự sản phẩm",
    "Trạng thái sản phẩm",
    "Tên sản phẩm",
    "Link sản phẩm",
    "Thumbnail",
    "Link ảnh",
    "Link video",
    "File đính kèm",
    "Link Canva",
    "Related URLs",
]

SUMMARY_COLUMNS = [
    "Ngày buổi học",
    "Buổi số",
    "Mã lớp",
    "Course",
    "Course line",
    "Khối",
    "Trạng thái lớp",
    "Cơ sở",
    "Tổng học viên",
    "Vắng buổi học",
    "Có sản phẩm",
    "Chưa có sản phẩm",
    "Vắng và chưa nộp",
    "Chưa nộp khác",
    "Tổng sản phẩm",
]

PRODUCT_EMPTY_FIELDS = {
    "Có sản phẩm": "Không",
    "Số thứ tự sản phẩm": "",
    "Trạng thái sản phẩm": "",
    "Tên sản phẩm": "",
    "Link sản phẩm": "",
    "Thumbnail": "",
    "Link ảnh": "",
    "Link video": "",
    "File đính kèm": "",
    "Link Canva": "",
    "Related URLs": "",
}
PRODUCT_FIELD_COLUMNS = frozenset(PRODUCT_EMPTY_FIELDS)


def refresh_auth_token(auto_login=False, force_refresh=False):
    global AUTH_TOKEN, AUTH_HEADER_VALUE, HEADERS

    AUTH_TOKEN = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    AUTH_HEADER_VALUE = AUTH_TOKEN[7:].strip() if AUTH_TOKEN.lower().startswith("bearer ") else AUTH_TOKEN
    HEADERS = build_auth_headers(AUTH_HEADER_VALUE)
    return AUTH_HEADER_VALUE


def ensure_valid_token(auto_login=False, force_refresh=False):
    refresh_auth_token(auto_login=auto_login, force_refresh=force_refresh)

    if not AUTH_TOKEN:
        raise ValueError("Thiếu AUTH_TOKEN. Hãy đặt biến môi trường AUTH_TOKEN hoặc TOKEN.")

    token = AUTH_TOKEN[7:].strip() if AUTH_TOKEN.lower().startswith("bearer ") else AUTH_TOKEN
    parts = token.split(".")
    if len(parts) < 2:
        return

    try:
        payload_part = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part))
    except Exception:
        return

    expires_at = payload.get("exp")
    if not expires_at:
        return

    if int(time.time()) >= int(expires_at):
        expires_vn = datetime.fromtimestamp(int(expires_at), tz=UTC_TZ).astimezone(VN_TZ)
        raise ValueError(
            "AUTH_TOKEN đã hết hạn hoặc không hợp lệ. "
            f"Token hiện tại hết hạn lúc {expires_vn.strftime('%Y-%m-%d %H:%M:%S')} VN."
        )


def get_today_vn():
    return datetime.now(VN_TZ).date()


def parse_vn_date(value, field_name="ngày"):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    value = str(value).strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"{field_name} không hợp lệ: {value}. Dùng YYYY-MM-DD hoặc DD/MM/YYYY.")


def resolve_date_range(args):
    supplied_periods = [value for value in (args.period, args.date) if value]
    if len(supplied_periods) > 1 or (supplied_periods and (args.start or args.end)):
        raise ValueError("Chỉ dùng một kiểu thời gian: period/--date hoặc --start/--end.")

    if args.start:
        start_date = parse_vn_date(args.start, "--start")
        end_date = parse_vn_date(args.end, "--end") if args.end else get_today_vn()
    elif args.end:
        raise ValueError("Khi dùng --end bạn cần truyền --start.")
    elif args.period or args.date:
        start_date = end_date = parse_vn_date(args.period or args.date, "--date")
    else:
        start_date = parse_vn_date(DEFAULT_START_DATE, "DEFAULT_START_DATE")
        end_date = get_today_vn()

    if start_date > end_date:
        raise ValueError("--start không được lớn hơn --end.")

    label = start_date.isoformat() if start_date == end_date else f"{start_date.isoformat()}_to_{end_date.isoformat()}"
    return start_date, end_date, label


def get_vn_datetime_range(start_date, end_date):
    start_vn = datetime.combine(start_date, dt_time.min).replace(tzinfo=VN_TZ)
    end_vn = datetime.combine(end_date, dt_time.max).replace(tzinfo=VN_TZ)
    return start_vn, end_vn


def vn_date_range_to_utc(start_date, end_date):
    start_vn, end_vn = get_vn_datetime_range(start_date, end_date)
    start_utc = start_vn.astimezone(UTC_TZ)
    end_utc = end_vn.astimezone(UTC_TZ)
    return (
        start_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        end_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )


def parse_api_datetime_to_vn(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        if value.isdigit():
            timestamp = int(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=UTC_TZ).astimezone(VN_TZ)

        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(VN_TZ)
    except (OverflowError, ValueError):
        return None


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_for_search(value):
    normalized = unicodedata.normalize("NFD", normalize_text(value))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").lower()


def strip_html(value):
    text = normalize_text(value)
    if not text:
        return ""

    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|li|h[1-6]|div)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def escape_graphql_string(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def gql_string_list(values):
    return "[" + ", ".join(f'"{escape_graphql_string(value)}"' for value in values) + "]"


def get_http_session():
    session = getattr(HTTP_LOCAL, "session", None)
    if session is not None:
        return session

    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=REQUEST_POOL_SIZE,
        pool_maxsize=REQUEST_POOL_SIZE,
        max_retries=0,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    HTTP_LOCAL.session = session
    return session


def post_graphql(query, variables=None, operation_name=None, timeout=35):
    request_payload = {"query": query}
    if variables is not None:
        request_payload["variables"] = variables
    if operation_name:
        request_payload["operationName"] = operation_name

    request_timeout = timeout if isinstance(timeout, tuple) else (10, timeout)
    last_error = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = get_http_session().post(API_URL, headers=HEADERS, json=request_payload, timeout=request_timeout)
            if response.status_code in RETRY_STATUS_CODES and attempt < REQUEST_RETRIES:
                wait_seconds = min(attempt * 2, 10)
                print(f"⚠️ API HTTP {response.status_code}, retry {attempt}/{REQUEST_RETRIES} sau {wait_seconds}s")
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            payload = response.json()
            errors = payload.get("errors")
            if errors and is_retryable_graphql_errors(errors) and attempt < REQUEST_RETRIES:
                wait_seconds = min(attempt * 2, 10)
                print(f"⚠️ API GraphQL tạm lỗi, retry {attempt}/{REQUEST_RETRIES} sau {wait_seconds}s: {errors}")
                time.sleep(wait_seconds)
                continue
            if errors:
                raise ValueError(errors)
            return payload
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt >= REQUEST_RETRIES:
                raise
            wait_seconds = min(attempt * 2, 10)
            print(f"⚠️ Lỗi request, retry {attempt}/{REQUEST_RETRIES} sau {wait_seconds}s: {exc}")
            time.sleep(wait_seconds)

    raise last_error


def is_retryable_graphql_errors(errors):
    error_text = str(errors)
    if is_auth_error(error_text):
        return False
    if "ECONNRESET" in error_text or "UNAVAILABLE" in error_text:
        return True

    for error in errors or []:
        code = ((error or {}).get("extensions") or {}).get("code")
        if code in RETRY_GRAPHQL_CODES:
            return True
    return False


def is_auth_error(error):
    return "Authentication failed" in str(error)


def build_slot_summaries_query(page_index, start_utc, end_utc, statuses, class_id=None):
    filters = [
        f"pageIndex: {page_index}",
        f"itemsPerPage: {SLOT_SUMMARIES_PER_PAGE}",
        f"classStatus_in: {gql_string_list(statuses)}",
        f'startTime_gte: "{escape_graphql_string(start_utc)}"',
        f'startTime_lte: "{escape_graphql_string(end_utc)}"',
    ]
    if class_id:
        filters.append(f'class_eq: "{escape_graphql_string(class_id)}"')

    return f"""
    {{
      classSlotSummaries(payload: {{ {", ".join(filters)} }}) {{
        data {{
          id
          class
          className
          slotId
          index
          startTime
          endTime
        }}
        pagination {{
          total
        }}
      }}
    }}
    """


def fetch_target_slot_summaries(start_date, end_date, statuses, session_numbers, class_ids=None, search_text=""):
    ensure_valid_token()
    start_utc, end_utc = vn_date_range_to_utc(start_date, end_date)
    print(f"🇻🇳 Khoảng ngày Việt Nam: {start_date.isoformat()} → {end_date.isoformat()}")
    print(f"🌍 Query UTC gửi API: {start_utc} → {end_utc}")

    target_slots = []
    seen_slot_ids = set()
    class_filters = list(class_ids or [None])
    search_normalized = normalize_for_search(search_text)

    for class_filter in class_filters:
        page_index = 0
        while True:
            query = build_slot_summaries_query(page_index, start_utc, end_utc, statuses, class_filter)
            try:
                payload = post_graphql(query, timeout=50)
            except requests.exceptions.RequestException as exc:
                raise ValueError(f"Lỗi request slot summaries trang {page_index}: {exc}") from exc
            except ValueError as exc:
                if is_auth_error(exc):
                    raise ValueError("AUTH_TOKEN đã hết hạn hoặc không hợp lệ. Hãy cập nhật token rồi chạy lại.")
                raise ValueError(f"API lỗi slot summaries trang {page_index}: {exc}") from exc

            page = payload.get("data", {}).get("classSlotSummaries", {})
            batch = page.get("data") or []
            total = page.get("pagination", {}).get("total", 0)
            print(f"✅ Slot summaries trang {page_index}: lấy {len(batch)} slot ({min((page_index + 1) * SLOT_SUMMARIES_PER_PAGE, total or 0)} / {total or '?'})")

            for item in batch:
                slot_id = normalize_text(item.get("slotId"))
                class_name = normalize_text(item.get("className"))
                slot_index = item.get("index")
                if not slot_id or slot_id in seen_slot_ids or not isinstance(slot_index, int):
                    continue
                if slot_index + 1 not in session_numbers:
                    continue
                if search_normalized and search_normalized not in normalize_for_search(class_name):
                    continue

                seen_slot_ids.add(slot_id)
                target_slots.append(item)

            if not batch or (total and (page_index + 1) * SLOT_SUMMARIES_PER_PAGE >= total):
                break
            page_index += 1
            time.sleep(0.05)

    print(f"🎯 Slot buổi {', '.join(map(str, session_numbers))}: {len(target_slots)} slot")
    return target_slots


def build_class_details_query(class_ids):
    return f"""
    {{
      classes(payload: {{
        pageIndex: 0,
        itemsPerPage: {len(class_ids)},
        id_in: {gql_string_list(class_ids)}
      }}) {{
        data {{
          id
          name
          status
          startDate
          endDate
          centre {{
            id
            shortName
            name
          }}
          course {{
            id
            shortName
            name
          }}
          students {{
            _id
            activeInClass
            student {{
              id
              fullName
              studentId
              email
              phoneNumber
            }}
          }}
          slots {{
            _id
            index
            startTime
            endTime
            studentAttendance {{
              _id
              status
              comment
              sendCommentStatus
              student {{
                id
                fullName
                studentId
                email
                phoneNumber
              }}
              commentStatus {{
                status
                feedback
                version
              }}
              commentByAreas {{
                commentAreaId
                grade
                content
                type
              }}
            }}
          }}
        }}
        pagination {{
          total
        }}
      }}
    }}
    """


def fetch_classes_by_ids(class_ids):
    classes = []
    sorted_class_ids = sorted(set(class_ids))
    class_batches = list(chunked(sorted_class_ids, CLASS_DETAIL_CHUNK_SIZE))
    total_batches = len(class_batches)

    def fetch_batch(batch_index, class_batch):
        query = build_class_details_query(class_batch)
        try:
            payload = post_graphql(query, timeout=80)
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Lỗi request class detail batch {batch_index}/{total_batches}: {exc}") from exc
        except ValueError as exc:
            if is_auth_error(exc):
                raise ValueError("AUTH_TOKEN đã hết hạn hoặc không hợp lệ. Hãy cập nhật token rồi chạy lại.")
            raise ValueError(f"API lỗi class detail batch {batch_index}/{total_batches}: {exc}") from exc

        batch = payload.get("data", {}).get("classes", {}).get("data") or []
        return batch_index, batch

    worker_count = min(CLASS_DETAIL_WORKERS, total_batches)
    if worker_count <= 1:
        for batch_index, class_batch in enumerate(class_batches, start=1):
            _, batch = fetch_batch(batch_index, class_batch)
            classes.extend(batch)
            print(f"✅ Class detail batch {batch_index}/{total_batches}: {len(batch)} lớp")
            if REQUEST_DELAY_SECONDS:
                time.sleep(REQUEST_DELAY_SECONDS)
        return dedupe_classes(classes)

    print(f"🚀 Lấy class detail song song: {total_batches} batch · {worker_count} workers")
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_batch, batch_index, class_batch): batch_index
            for batch_index, class_batch in enumerate(class_batches, start=1)
        }
        for future in as_completed(futures):
            batch_index, batch = future.result()
            classes.extend(batch)
            print(f"✅ Class detail batch {batch_index}/{total_batches}: {len(batch)} lớp")

    return dedupe_classes(classes)


def build_classes_query(page_index, start_utc, end_utc, statuses, class_ids=None, search_text=""):
    filters = [
        f"pageIndex: {page_index}",
        f"itemsPerPage: {ITEMS_PER_PAGE}",
        f"status_in: {gql_string_list(statuses)}",
        f'haveSlot_in: {{ from: "{escape_graphql_string(start_utc)}", to: "{escape_graphql_string(end_utc)}" }}',
    ]
    if class_ids:
        filters.append(f"id_in: {gql_string_list(class_ids)}")
    if search_text:
        filters.append(f'filter_textSearch: "{escape_graphql_string(search_text)}"')

    return f"""
    {{
      classes(payload: {{ {", ".join(filters)} }}) {{
        data {{
          id
          name
          status
          startDate
          endDate
          centre {{
            id
            shortName
            name
          }}
          course {{
            id
            shortName
            name
          }}
          students {{
            _id
            activeInClass
            student {{
              id
              fullName
              studentId
              email
              phoneNumber
            }}
          }}
          slots {{
            _id
            index
            startTime
            endTime
            studentAttendance {{
              _id
              status
              comment
              sendCommentStatus
              student {{
                id
                fullName
                studentId
                email
                phoneNumber
              }}
              commentStatus {{
                status
                feedback
                version
              }}
              commentByAreas {{
                commentAreaId
                grade
                content
                type
              }}
            }}
          }}
        }}
        pagination {{
          total
        }}
      }}
    }}
    """


def build_class_filter_options_query(
    page_index,
    start_utc,
    end_utc,
    statuses,
    class_ids=None,
    search_text="",
    items_per_page=None,
):
    filters = [
        f"pageIndex: {page_index}",
        f"itemsPerPage: {int(items_per_page or ITEMS_PER_PAGE)}",
        f"status_in: {gql_string_list(statuses)}",
        f'haveSlot_in: {{ from: "{escape_graphql_string(start_utc)}", to: "{escape_graphql_string(end_utc)}" }}',
    ]
    if class_ids:
        filters.append(f"id_in: {gql_string_list(class_ids)}")
    if search_text:
        filters.append(f'filter_textSearch: "{escape_graphql_string(search_text)}"')

    return f"""
    {{
      classes(payload: {{ {", ".join(filters)} }}) {{
        data {{
          id
          name
          status
          centre {{
            id
            shortName
            name
          }}
          course {{
            id
            code
            shortName
            name
            courseLine {{
              id
              name
            }}
          }}
        }}
        pagination {{
          total
        }}
      }}
    }}
    """


def build_class_status_probe_query(status, start_utc, end_utc):
    return f"""
    {{
      classes(payload: {{
        pageIndex: 0,
        itemsPerPage: 1,
        status_in: ["{escape_graphql_string(status)}"],
        haveSlot_in: {{
          from: "{escape_graphql_string(start_utc)}",
          to: "{escape_graphql_string(end_utc)}"
        }}
      }}) {{
        data {{
          status
        }}
        pagination {{
          total
        }}
      }}
    }}
    """


def fetch_product_status_filter_options(
    start_date,
    end_date,
    statuses=None,
    auto_login=False,
    force_refresh=False,
    skip_auth=False,
):
    started_at = time.perf_counter()
    if not skip_auth:
        ensure_valid_token(auto_login=auto_login, force_refresh=force_refresh)

    start_utc, end_utc = vn_date_range_to_utc(start_date, end_date)
    candidates = unique_keep_order([
        *(parse_csv_values(statuses, upper=True) if isinstance(statuses, str) else (statuses or [])),
        *CLASS_STATUS_FILTER_CANDIDATES,
        *DEFAULT_CLASS_STATUSES,
    ])
    available = []
    for status in candidates:
        normalized_status = normalize_text(status).upper()
        if not normalized_status:
            continue
        payload = post_graphql(
            build_class_status_probe_query(normalized_status, start_utc, end_utc),
            timeout=30,
        )
        page = payload.get("data", {}).get("classes", {})
        total = (page.get("pagination") or {}).get("total") or 0
        if total:
            sample = (page.get("data") or [{}])[0]
            available.append(normalize_text(sample.get("status")).upper() or normalized_status)

    options = build_status_filter_options(available or DEFAULT_CLASS_STATUSES)
    print(
        f"✅ Tải {len(options)} trạng thái lớp từ classes API trong "
        f"{time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return options


def fetch_classes_by_date(start_date, end_date, statuses, class_ids=None, search_text=""):
    ensure_valid_token()
    classes = []
    page_index = 0
    start_utc, end_utc = vn_date_range_to_utc(start_date, end_date)
    print(f"🇻🇳 Khoảng ngày Việt Nam: {start_date.isoformat()} → {end_date.isoformat()}")
    print(f"🌍 Query UTC gửi API: {start_utc} → {end_utc}")

    while True:
        query = build_classes_query(page_index, start_utc, end_utc, statuses, class_ids, search_text)
        try:
            payload = post_graphql(query, timeout=80)
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Lỗi request classes trang {page_index}: {exc}") from exc
        except ValueError as exc:
            if is_auth_error(exc):
                raise ValueError("AUTH_TOKEN đã hết hạn hoặc không hợp lệ. Hãy cập nhật token rồi chạy lại.")
            raise ValueError(f"API lỗi classes trang {page_index}: {exc}") from exc

        page = payload.get("data", {}).get("classes", {})
        batch = page.get("data") or []
        total = page.get("pagination", {}).get("total", 0)
        classes.extend(batch)

        print(f"✅ Trang {page_index}: lấy {len(batch)} lớp ({len(classes)} / {total or '?'})")

        if not batch or (total and (page_index + 1) * ITEMS_PER_PAGE >= total):
            break

        page_index += 1
        time.sleep(0.1)

    return dedupe_classes(classes)


def fetch_product_class_filter_options(
    start_date,
    end_date,
    statuses,
    sessions=None,
    class_ids=None,
    search_text="",
    course_lines=None,
    courses=None,
    centres=None,
    class_limit=100,
    auto_login=False,
    force_refresh=False,
):
    ensure_valid_token(auto_login=auto_login, force_refresh=force_refresh)
    selected_statuses = parse_csv_values(statuses, upper=True) if isinstance(statuses, str) else tuple(statuses or [])
    selected_statuses = tuple(normalize_text(status).upper() for status in selected_statuses if normalize_text(status))
    if not selected_statuses:
        return {"classes": []}

    selected_class_ids = parse_filter_values(class_ids) if isinstance(class_ids, str) else tuple(class_ids or [])
    search = normalize_text(search_text)
    limit = max(1, int(class_limit or 100))
    per_page = ITEMS_PER_PAGE
    start_utc, end_utc = vn_date_range_to_utc(start_date, end_date)
    started_at = time.perf_counter()
    print(f"🇻🇳 Khoảng ngày Việt Nam: {start_date.isoformat()} → {end_date.isoformat()}")
    print(f"🌍 Query UTC gửi API classes: {start_utc} → {end_utc}")

    classes = []
    page_index = 0
    scanned = 0
    while len(classes) < limit:
        query = build_class_filter_options_query(
            page_index,
            start_utc,
            end_utc,
            selected_statuses,
            selected_class_ids,
            search,
            items_per_page=per_page,
        )
        try:
            payload = post_graphql(query, timeout=40)
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Lỗi request classes filter trang {page_index}: {exc}") from exc
        except ValueError as exc:
            if is_auth_error(exc):
                raise ValueError("AUTH_TOKEN đã hết hạn hoặc không hợp lệ. Hãy cập nhật token rồi chạy lại.")
            raise ValueError(f"API lỗi classes filter trang {page_index}: {exc}") from exc

        page = payload.get("data", {}).get("classes", {})
        batch = page.get("data") or []
        total = page.get("pagination", {}).get("total", 0)
        scanned += len(batch)
        filtered_batch = filter_classes_by_product_filters(
            batch,
            course_lines=course_lines,
            courses=courses,
            centres=centres,
        )
        classes.extend(filtered_batch)
        print(
            f"✅ Classes filter trang {page_index}: lấy {len(batch)} lớp, "
            f"khớp {len(filtered_batch)} ({scanned} / {total or '?'})"
        )

        if not batch or (total and scanned >= total):
            break
        page_index += 1
        time.sleep(0.03)

    result = build_product_filter_options(dedupe_classes(classes[:limit]))
    print(
        f"🎯 Tải {len(result.get('classes') or [])} mã lớp từ classes API "
        f"trong {time.perf_counter() - started_at:.1f}s."
    )
    return {"classes": result.get("classes") or []}


def fetch_product_filter_options(
    start_date,
    end_date,
    sessions,
    statuses,
    class_ids=None,
    search_text="",
    course_lines=None,
    courses=None,
    centres=None,
    auto_login=False,
    force_refresh=False,
):
    ensure_valid_token(auto_login=auto_login, force_refresh=force_refresh)
    target_slot_summaries = fetch_target_slot_summaries(
        start_date,
        end_date,
        statuses,
        sessions,
        class_ids,
        search_text,
    )
    target_class_ids = sorted({
        normalize_text(item.get("class"))
        for item in target_slot_summaries
        if normalize_text(item.get("class"))
    })
    if not target_class_ids:
        return build_product_filter_options([])

    classes = fetch_classes_by_ids(target_class_ids)
    classes = filter_classes_by_product_filters(
        classes,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
    )
    return build_product_filter_options(classes)


def dedupe_classes(classes):
    seen = set()
    result = []
    for item in classes:
        key = item.get("id") or item.get("name")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def format_vn_datetime(value):
    dt = parse_api_datetime_to_vn(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def format_vn_date(value):
    dt = parse_api_datetime_to_vn(value)
    return dt.strftime("%Y-%m-%d") if dt else ""


def format_vn_time_range(slot):
    start_time = parse_api_datetime_to_vn(slot.get("startTime"))
    end_time = parse_api_datetime_to_vn(slot.get("endTime"))
    if start_time and end_time:
        return f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"
    if start_time:
        return start_time.strftime("%H:%M")
    return ""


def parse_csv_values(value, upper=False):
    items = [item.strip() for item in re.split(r"[,\s]+", normalize_text(value)) if item.strip()]
    return tuple(item.upper() if upper else item for item in items)


def parse_filter_values(value, upper=False):
    if isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(parse_filter_values(item, upper=upper))
        return tuple(raw_items)

    items = [
        item.strip()
        for item in normalize_text(value).replace("\n", ",").split(",")
        if item.strip()
    ]
    return tuple(item.upper() if upper else item for item in items)


def parse_session_numbers(value):
    numbers = []
    for item in parse_csv_values(value):
        try:
            number = int(item)
        except ValueError as exc:
            raise ValueError(f"Buổi học không hợp lệ: {item}") from exc
        if number <= 0:
            raise ValueError("Buổi học phải lớn hơn 0.")
        numbers.append(number)
    return tuple(sorted(set(numbers)))


def is_target_slot(slot, session_numbers, start_vn, end_vn):
    slot_index = slot.get("index")
    if not isinstance(slot_index, int):
        return False

    session_number = slot_index + 1
    if session_number not in session_numbers:
        return False

    start_time = parse_api_datetime_to_vn(slot.get("startTime"))
    return bool(start_time and start_vn <= start_time <= end_vn)


def get_centre_name(cls):
    centre = cls.get("centre") or {}
    name = normalize_text(centre.get("name"))
    short_name = normalize_text(centre.get("shortName"))
    centre_id = normalize_text(centre.get("id"))
    if name:
        return name
    if short_name:
        return short_name
    return f"ID: {centre_id}" if centre_id else ""


def infer_khoi_from_texts(*values):
    tokens = []
    for value in values:
        tokens.extend(re.findall(r"[A-Z0-9]+", normalize_text(value).upper()))

    for token in tokens:
        for prefix, khoi in KHOI_CODE_MAP.items():
            if token.startswith(prefix):
                return khoi

    return ""


def infer_khoi_from_class(cls):
    course = cls.get("course") or {}
    return infer_khoi_from_texts(
        cls.get("name"),
        course.get("shortName"),
        course.get("name"),
    )


def entity_values(entity, keys=("id", "code", "shortName", "name", "label", "value")):
    values = []
    if isinstance(entity, dict):
        for key in keys:
            values.append(entity.get(key))
    else:
        values.append(entity)
    return [normalize_text(value) for value in values if normalize_text(value)]


def first_entity_value(entity, keys=("id", "code", "shortName", "name", "label", "value")):
    values = entity_values(entity, keys)
    return values[0] if values else ""


def course_entity(cls):
    return (cls or {}).get("course") or {}


def course_display(cls):
    course = course_entity(cls)
    if not isinstance(course, dict):
        return normalize_text(course)

    code = normalize_text(course.get("shortName") or course.get("code"))
    name = normalize_text(course.get("name"))
    if code and name and normalize_for_search(code) not in normalize_for_search(name):
        return f"{code} - {name}"
    return code or name or normalize_text(course.get("id"))


def course_line_entity(cls):
    cls = cls or {}
    course = course_entity(cls)
    for value in (
        cls.get("courseLine"),
        cls.get("course_line"),
        cls.get("line"),
        course.get("courseLine") if isinstance(course, dict) else None,
        course.get("course_line") if isinstance(course, dict) else None,
        course.get("line") if isinstance(course, dict) else None,
    ):
        if value:
            return value
    return {}


def course_line_display(cls):
    line = course_line_entity(cls)
    value = first_entity_value(line, ("shortName", "code", "name", "label", "value", "id"))
    return value or infer_khoi_from_class(cls)


def filter_match_key(value):
    return normalize_for_search(value)


def normalized_filter_set(values):
    return {
        filter_match_key(value)
        for value in (values or [])
        if filter_match_key(value)
    }


def matches_selected_filter(selected_values, candidates):
    if not selected_values:
        return True
    return any(filter_match_key(candidate) in selected_values for candidate in candidates)


def course_candidates(cls):
    course = course_entity(cls)
    return unique_keep_order(entity_values(course) + [course_display(cls)])


def course_line_candidates(cls):
    line = course_line_entity(cls)
    return unique_keep_order(entity_values(line) + [course_line_display(cls), infer_khoi_from_class(cls)])


def centre_candidates(cls):
    centre = (cls or {}).get("centre") or {}
    return unique_keep_order(entity_values(centre) + [get_centre_name(cls)])


def class_matches_product_filters(cls, course_lines=None, courses=None, centres=None):
    selected_course_lines = normalized_filter_set(course_lines)
    selected_courses = normalized_filter_set(courses)
    selected_centres = normalized_filter_set(centres)
    return (
        matches_selected_filter(selected_course_lines, course_line_candidates(cls))
        and matches_selected_filter(selected_courses, course_candidates(cls))
        and matches_selected_filter(selected_centres, centre_candidates(cls))
    )


def filter_classes_by_product_filters(classes, course_lines=None, courses=None, centres=None):
    if not any((course_lines, courses, centres)):
        return list(classes or [])
    return [
        cls for cls in classes or []
        if class_matches_product_filters(cls, course_lines, courses, centres)
    ]


def add_filter_option(options, seen, value, label=None, name=None):
    value = normalize_text(value)
    label = normalize_text(label) or value
    name = normalize_text(name)
    if not value or value in seen:
        return
    seen.add(value)
    options.append({"value": value, "label": label, "name": name})


def option_sort_key(option):
    return (normalize_for_search(option.get("label")), normalize_for_search(option.get("name")))


def build_product_filter_options(classes):
    course_lines = []
    courses = []
    centres = []
    class_options = []
    seen_course_lines = set()
    seen_courses = set()
    seen_centres = set()
    seen_classes = set()

    for cls in classes or []:
        course = course_entity(cls)
        line = course_line_entity(cls)
        centre = (cls or {}).get("centre") or {}
        class_id = normalize_text((cls or {}).get("id"))
        class_name = normalize_text((cls or {}).get("name"))

        line_value = first_entity_value(line) or course_line_display(cls)
        line_label = first_entity_value(line, ("shortName", "code", "name", "label", "value")) or line_value
        add_filter_option(course_lines, seen_course_lines, line_value, line_label)

        course_value = first_entity_value(course)
        course_label = first_entity_value(course, ("shortName", "code", "name", "label", "value")) or course_display(cls)
        add_filter_option(courses, seen_courses, course_value, course_label, course_display(cls))

        centre_value = first_entity_value(centre)
        centre_label = get_centre_name(cls) or first_entity_value(centre, ("shortName", "name", "label", "value"))
        add_filter_option(centres, seen_centres, centre_value, centre_label, get_centre_name(cls))

        if class_id and class_name and class_id not in seen_classes:
            seen_classes.add(class_id)
            class_options.append({
                "id": class_id,
                "name": class_name,
                "subject": course_line_display(cls),
                "course": course_display(cls),
                "centre": get_centre_name(cls),
            })

    return {
        "course_lines": sorted(course_lines, key=option_sort_key),
        "courses": sorted(courses, key=option_sort_key),
        "centres": sorted(centres, key=option_sort_key),
        "classes": sorted(class_options, key=lambda item: normalize_for_search(item["name"])),
    }


def build_status_filter_options(statuses=None):
    options = []
    seen = set()
    for status in statuses or DEFAULT_CLASS_STATUSES:
        value = normalize_text(status).upper()
        if not value or value in seen:
            continue
        seen.add(value)
        options.append({
            "value": value,
            "label": value.replace("_", " ").title(),
            "name": "classStatus",
        })
    return options


def unique_keep_order(values):
    result = []
    seen = set()
    for value in values:
        text = normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def join_values(values):
    return " | ".join(unique_keep_order(values))


def extract_urls_from_text(*values):
    urls = []
    for value in values:
        for url in URL_PATTERN.findall(normalize_text(value)):
            urls.append(url.rstrip(").,;]"))
    return join_values(urls)


def build_comment_area_query(page_index, limit=100):
    return f"""
    {{
      studentCommentAreas(payload: {{
        pagination: {{ page: {page_index}, limit: {limit} }},
        orderBy: "sortOrder_asc"
      }}) {{
        data {{
          id
          name
          fieldName
          type
        }}
        pagination {{
          total
        }}
      }}
    }}
    """


def fetch_comment_area_map():
    area_map = {}
    page_index = 0
    limit = 100

    while True:
        payload = post_graphql(build_comment_area_query(page_index, limit), timeout=40)
        page = payload.get("data", {}).get("studentCommentAreas", {})
        batch = page.get("data") or []
        total = page.get("pagination", {}).get("total", 0)

        for area in batch:
            area_id = area.get("id")
            if area_id:
                area_map[area_id] = area

        if not batch or (total and len(area_map) >= total):
            break

        page_index += 1
        time.sleep(0.05)

    return area_map


def is_product_area(area_item, area_map):
    area_id = area_item.get("commentAreaId")
    area = area_map.get(area_id) or {}
    area_type = normalize_text(area.get("type") or area_item.get("type")).upper()
    if area_type == "DEMO":
        return True

    search_text = normalize_for_search(
        " ".join([
            normalize_text(area.get("name")),
            normalize_text(area.get("fieldName")),
            normalize_text(area_type),
        ])
    )
    return any(keyword in search_text for keyword in PRODUCT_AREA_KEYWORDS)


def format_comment_areas(comment_by_areas, area_map, product_only=False):
    entries = []
    for item in comment_by_areas or []:
        if product_only and not is_product_area(item, area_map):
            continue

        area = area_map.get(item.get("commentAreaId")) or {}
        area_name = normalize_text(area.get("name")) or normalize_text(item.get("commentAreaId")) or "Không rõ vùng"
        area_type = normalize_text(area.get("type") or item.get("type"))
        content = strip_html(item.get("content"))
        grade = item.get("grade")

        if not content and grade is None:
            continue

        parts = [area_name]
        if area_type:
            parts.append(f"type={area_type}")
        if grade is not None:
            parts.append(f"điểm={grade}")
        if content:
            parts.append(content)
        entries.append(": ".join(parts))

    return " | ".join(entries)


def has_comment(attendance):
    if not attendance:
        return False
    if strip_html(attendance.get("comment")):
        return True
    for area in attendance.get("commentByAreas") or []:
        if strip_html(area.get("content")) or area.get("grade") is not None:
            return True
    return False


def chunked(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def build_student_work_batch_query(slot_batch):
    aliases = []
    for index, (slot_id, context) in enumerate(slot_batch):
        cls = context.get("class") or {}
        class_id = normalize_text(cls.get("id"))
        aliases.append(f"""
        slot_{index}: findAllStudentWorks(payload: {{
          classSessionId_equals: "{escape_graphql_string(slot_id)}",
          classId_equals: "{escape_graphql_string(class_id)}"
        }}) {{
          data {{
            {STUDENT_WORK_FIELDS}
          }}
        }}
        """)

    return f"""
    query findAllStudentWorksBatch {{
      {" ".join(aliases)}
    }}
    """


def fetch_student_works(target_slots_by_id):
    works = []
    target_slots = [
        (slot_id, context)
        for slot_id, context in target_slots_by_id.items()
        if normalize_text((context.get("class") or {}).get("id"))
    ]
    slot_batches = list(chunked(target_slots, WORK_SLOT_BATCH_SIZE))
    total_batches = len(slot_batches)

    def fetch_batch(batch_index, slot_batch):
        query = build_student_work_batch_query(slot_batch)

        try:
            payload = post_graphql(query, operation_name="findAllStudentWorksBatch", timeout=80)
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Lỗi request sản phẩm batch {batch_index}/{total_batches}: {exc}") from exc
        except ValueError as exc:
            if is_auth_error(exc):
                raise ValueError("AUTH_TOKEN đã hết hạn hoặc không hợp lệ. Hãy cập nhật token rồi chạy lại.")
            raise ValueError(f"API lỗi sản phẩm batch {batch_index}/{total_batches}: {exc}") from exc

        batch_total = 0
        batch_works = []
        data = payload.get("data") or {}
        for index, _ in enumerate(slot_batch):
            items = data.get(f"slot_{index}", {}).get("data") or []
            batch_works.extend(items)
            batch_total += len(items)

        return batch_index, len(slot_batch), batch_total, batch_works

    worker_count = min(WORK_FETCH_WORKERS, total_batches)
    if worker_count <= 1:
        for batch_index, slot_batch in enumerate(slot_batches, start=1):
            _, slot_count, batch_total, batch_works = fetch_batch(batch_index, slot_batch)
            works.extend(batch_works)
            print(
                f"✅ Sản phẩm batch {batch_index}/{total_batches}: "
                f"{slot_count} slot → {batch_total} bản ghi"
            )
            if REQUEST_DELAY_SECONDS:
                time.sleep(REQUEST_DELAY_SECONDS)
        return works

    print(f"🚀 Lấy sản phẩm song song: {total_batches} batch · {worker_count} workers")
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_batch, batch_index, slot_batch): batch_index
            for batch_index, slot_batch in enumerate(slot_batches, start=1)
        }
        for future in as_completed(futures):
            batch_index, slot_count, batch_total, batch_works = future.result()
            works.extend(batch_works)
            print(
                f"✅ Sản phẩm batch {batch_index}/{total_batches}: "
                f"{slot_count} slot → {batch_total} bản ghi"
            )

    return works


def select_work_data(work):
    return work.get("publishedData") or work.get("latestData") or {}


def format_related_urls(related_urls):
    values = []
    for item in related_urls or []:
        name = normalize_text(item.get("name"))
        url = normalize_text(item.get("url"))
        if name and url:
            values.append(f"{name}: {url}")
        elif url:
            values.append(url)
    return join_values(values)


def format_canva_urls(related_urls):
    values = []
    for item in related_urls or []:
        name = normalize_for_search(item.get("name"))
        url = normalize_text(item.get("url"))
        searchable_url = normalize_for_search(url)
        if url and ("canva" in name or "canva" in searchable_url):
            values.append(url)
    return join_values(values)


def work_has_product(work):
    data = select_work_data(work)
    related_urls = [item.get("url") for item in data.get("relatedUrls") or [] if item.get("url")]
    urls = (
        [data.get("thumbnail")]
        + (data.get("imageUrl") or [])
        + (data.get("videoUrls") or [])
        + (data.get("attachmentUrls") or [])
        + related_urls
    )
    return bool(normalize_text(data.get("title")) or normalize_text(data.get("comment")) or unique_keep_order(urls))


def is_absent_attendance_status(value):
    return normalize_text(value).upper() in {"ABSENT", "ABSENT_WITH_NOTICE"}


def class_student_status_label(student):
    active_in_class = student.get("_activeInClass")
    if active_in_class is True:
        return "Đang học"
    if active_in_class is False:
        return "Không active"
    return ""


def submission_status_label(base, has_product):
    attendance_status = normalize_text(base.get("Trạng thái điểm danh"))
    if is_absent_attendance_status(attendance_status):
        return "Vắng - không thể nộp sản phẩm"
    if has_product:
        return "Đã nộp sản phẩm"
    if not attendance_status:
        return "Chưa có điểm danh"
    return "Chưa nộp sản phẩm"


def is_valid_submitted_product(base, work):
    if is_absent_attendance_status(base.get("Trạng thái điểm danh")):
        return False
    return work_has_product(work)


def format_product_links(data):
    related_urls = [item.get("url") for item in data.get("relatedUrls") or [] if item.get("url")]
    return join_values(
        (data.get("attachmentUrls") or [])
        + (data.get("imageUrl") or [])
        + (data.get("videoUrls") or [])
        + related_urls
        + ([data.get("thumbnail")] if data.get("thumbnail") else [])
    )


def make_base_record(cls, slot, student, attendance, area_map, note=""):
    comment_status = attendance.get("commentStatus") if attendance else {}
    comment_by_areas = attendance.get("commentByAreas") if attendance else []
    product_area_text = format_comment_areas(comment_by_areas, area_map, product_only=True)
    all_area_text = format_comment_areas(comment_by_areas, area_map)
    comment_text = strip_html(attendance.get("comment")) if attendance else ""
    student_id = normalize_text(student.get("id"))
    slot_id = normalize_text(slot.get("_id"))
    class_id = normalize_text(cls.get("id"))
    class_name = normalize_text(cls.get("name"))
    start_time = parse_api_datetime_to_vn(slot.get("startTime"))

    return {
        "Ngày xuất": get_today_vn().isoformat(),
        "Ngày buổi học": format_vn_date(slot.get("startTime")),
        "Giờ buổi học": format_vn_time_range(slot),
        "Buổi số": (slot.get("index") + 1) if isinstance(slot.get("index"), int) else "",
        "Mã lớp": class_name,
        "Course": course_display(cls),
        "Course line": course_line_display(cls),
        "Khối": infer_khoi_from_class(cls),
        "Trạng thái lớp": normalize_text(cls.get("status")),
        "Cơ sở": get_centre_name(cls),
        "Slot ID": slot_id,
        "Tên học viên": normalize_text(student.get("fullName")),
        "Mã học viên": normalize_text(student.get("studentId")),
        "Student ID nội bộ": student_id,
        "Trạng thái học viên trong lớp": class_student_status_label(student),
        "Trạng thái điểm danh": normalize_text(attendance.get("status")) if attendance else "",
        "Trạng thái nhận xét": normalize_text(comment_status.get("status")) if comment_status else "",
        "Có nhận xét": "Có" if has_comment(attendance) else "Không",
        "Nhận xét học viên": comment_text,
        "Có vùng sản phẩm/demo": "Có" if product_area_text else "Không",
        "Vùng sản phẩm/demo": product_area_text,
        "Toàn bộ vùng nhận xét": all_area_text,
        "Link trong nhận xét": extract_urls_from_text(comment_text, all_area_text),
        "Ghi chú theo dõi": note,
        "_key": (class_id, slot_id, student_id or f"slot:{slot_id}"),
        "_class_id": class_id,
        "_slot_id": slot_id,
        "_student_id": student_id,
        "_has_student": bool(student_id or normalize_text(student.get("fullName"))),
        "_sort_time": start_time or datetime.max.replace(tzinfo=VN_TZ),
    }


def build_base_records(classes, session_numbers, start_date, end_date, area_map, target_slot_ids=None):
    start_vn, end_vn = get_vn_datetime_range(start_date, end_date)
    target_slot_ids = set(target_slot_ids or [])
    base_records = []
    base_by_key = {}
    target_slots_by_id = {}
    classes_by_id = {}
    students_by_class = {}

    for cls in classes:
        class_id = normalize_text(cls.get("id"))
        if not class_id:
            continue

        classes_by_id[class_id] = cls
        students_by_class[class_id] = {}

        roster_students = []
        for class_student in cls.get("students") or []:
            student = dict(class_student.get("student") or {})
            student["_activeInClass"] = class_student.get("activeInClass")
            student_id = normalize_text(student.get("id"))
            if student_id:
                students_by_class[class_id][student_id] = student
            roster_students.append(student)

        for slot in cls.get("slots") or []:
            slot_id = normalize_text(slot.get("_id"))
            if not slot_id:
                continue
            if target_slot_ids:
                if slot_id not in target_slot_ids:
                    continue
            elif not is_target_slot(slot, session_numbers, start_vn, end_vn):
                continue

            target_slots_by_id[slot_id] = {"class": cls, "slot": slot}
            attendance_by_student = {}
            attendance_without_student = []

            for attendance in slot.get("studentAttendance") or []:
                student = attendance.get("student") or {}
                student_id = normalize_text(student.get("id"))
                if student_id:
                    attendance_by_student[student_id] = attendance
                    students_by_class[class_id].setdefault(student_id, student)
                else:
                    attendance_without_student.append(attendance)

            seen_student_ids = set()
            for student in roster_students:
                student_id = normalize_text(student.get("id"))
                attendance = attendance_by_student.get(student_id)
                record = make_base_record(cls, slot, student, attendance, area_map)
                base_records.append(record)
                base_by_key[record["_key"]] = record
                if student_id:
                    seen_student_ids.add(student_id)

            for student_id, attendance in attendance_by_student.items():
                if student_id in seen_student_ids:
                    continue
                student = attendance.get("student") or students_by_class[class_id].get(student_id) or {"id": student_id}
                record = make_base_record(cls, slot, student, attendance, area_map)
                base_records.append(record)
                base_by_key[record["_key"]] = record

            for attendance in attendance_without_student:
                student = attendance.get("student") or {}
                note = "Attendance không có student id"
                record = make_base_record(cls, slot, student, attendance, area_map, note)
                base_records.append(record)
                base_by_key[record["_key"]] = record

            if not roster_students and not attendance_by_student and not attendance_without_student:
                note = "Chưa có dữ liệu học viên/attendance trong slot"
                record = make_base_record(cls, slot, {}, {}, area_map, note)
                base_records.append(record)
                base_by_key[record["_key"]] = record

    return base_records, base_by_key, target_slots_by_id, classes_by_id, students_by_class


def build_work_map(works, target_slots_by_id):
    target_slot_ids = set(target_slots_by_id)
    works_by_key = {}
    for work in works:
        class_id = normalize_text(work.get("classId"))
        slot_id = normalize_text(work.get("classSessionId"))
        student_id = normalize_text(work.get("studentId"))
        if slot_id not in target_slot_ids or not class_id or not student_id:
            continue
        key = (class_id, slot_id, student_id)
        works_by_key.setdefault(key, []).append(work)
    return works_by_key


def ensure_work_base_records(base_records, base_by_key, works_by_key, target_slots_by_id, students_by_class, area_map):
    for key in works_by_key:
        if key in base_by_key:
            continue

        class_id, slot_id, student_id = key
        slot_context = target_slots_by_id.get(slot_id)
        if not slot_context:
            continue

        student = students_by_class.get(class_id, {}).get(student_id) or {"id": student_id}
        note = "Có sản phẩm nhưng không thấy roster/attendance trong slot"
        record = make_base_record(slot_context["class"], slot_context["slot"], student, {}, area_map, note)
        base_records.append(record)
        base_by_key[record["_key"]] = record


def product_fields(work, product_index, product_count):
    if not work:
        return PRODUCT_EMPTY_FIELDS.copy()

    data = select_work_data(work)
    return {
        "Có sản phẩm": "Có" if work_has_product(work) else "Không",
        "Số thứ tự sản phẩm": f"{product_index}/{product_count}",
        "Trạng thái sản phẩm": normalize_text(work.get("status")),
        "Tên sản phẩm": normalize_text(data.get("title")),
        "Link sản phẩm": format_product_links(data),
        "Thumbnail": normalize_text(data.get("thumbnail")),
        "Link ảnh": join_values(data.get("imageUrl") or []),
        "Link video": join_values(data.get("videoUrls") or []),
        "File đính kèm": join_values(data.get("attachmentUrls") or []),
        "Link Canva": format_canva_urls(data.get("relatedUrls") or []),
        "Related URLs": format_related_urls(data.get("relatedUrls") or []),
    }


def build_detail_rows(base_records, works_by_key):
    rows = []
    for base in sorted(base_records, key=lambda item: (item["_sort_time"], item["Mã lớp"], item["Buổi số"], item["Tên học viên"])):
        public_base = {column: base.get(column, "") for column in DETAIL_COLUMNS if column not in PRODUCT_FIELD_COLUMNS}
        works = works_by_key.get(base["_key"]) or []
        if not works:
            row = {**public_base, **product_fields(None, "", "")}
            row["Trạng thái nộp sản phẩm"] = submission_status_label(base, False)
            rows.append(row)
            continue

        for index, work in enumerate(works, start=1):
            row = {**public_base, **product_fields(work, index, len(works))}
            has_valid_product = is_valid_submitted_product(base, work)
            row["Có sản phẩm"] = "Có" if has_valid_product else "Không"
            row["Trạng thái nộp sản phẩm"] = submission_status_label(base, has_valid_product)
            rows.append(row)

    return rows


def build_summary_rows(base_records, works_by_key):
    groups = {}
    for base in base_records:
        group_key = (base["_slot_id"], base["Mã lớp"], base["Buổi số"])
        group = groups.setdefault(group_key, {
            "Ngày buổi học": base["Ngày buổi học"],
            "Buổi số": base["Buổi số"],
            "Mã lớp": base["Mã lớp"],
            "Course": base["Course"],
            "Course line": base["Course line"],
            "Khối": base["Khối"],
            "Trạng thái lớp": base["Trạng thái lớp"],
            "Cơ sở": base["Cơ sở"],
            "student_keys": set(),
            "absent_keys": set(),
            "product_keys": set(),
            "products": [],
        })

        if base["_has_student"]:
            group["student_keys"].add(base["_key"])
            if is_absent_attendance_status(base.get("Trạng thái điểm danh")):
                group["absent_keys"].add(base["_key"])
            valid_works = [
                work
                for work in works_by_key.get(base["_key"], [])
                if is_valid_submitted_product(base, work)
            ]
            if valid_works:
                group["product_keys"].add(base["_key"])
                group["products"].extend(valid_works)

    rows = []
    for group in sorted(groups.values(), key=lambda item: (item["Ngày buổi học"], item["Mã lớp"], item["Buổi số"])):
        total_students = len(group["student_keys"])
        absent_count = len(group["absent_keys"])
        product_student_count = len(group["product_keys"])
        absent_without_product = len(group["absent_keys"] - group["product_keys"])
        without_product = max(total_students - product_student_count, 0)
        rows.append({
            "Ngày buổi học": group["Ngày buổi học"],
            "Buổi số": group["Buổi số"],
            "Mã lớp": group["Mã lớp"],
            "Course": group["Course"],
            "Course line": group["Course line"],
            "Khối": group["Khối"],
            "Trạng thái lớp": group["Trạng thái lớp"],
            "Cơ sở": group["Cơ sở"],
            "Tổng học viên": total_students,
            "Vắng buổi học": absent_count,
            "Có sản phẩm": product_student_count,
            "Chưa có sản phẩm": without_product,
            "Vắng và chưa nộp": absent_without_product,
            "Chưa nộp khác": max(without_product - absent_without_product, 0),
            "Tổng sản phẩm": len(group["products"]),
        })

    return rows


def build_output_paths(label, sessions, output=None, summary_output=None):
    session_label = "_".join(f"b{session}" for session in sessions)
    detail_file = output or f"student_products_{session_label}_{label}_VN.csv"
    summary_file = summary_output or f"student_products_{session_label}_summary_{label}_VN.csv"
    return detail_file, summary_file


def export_products(
    start_date,
    end_date,
    sessions,
    statuses,
    output=None,
    summary_output=None,
    class_ids=None,
    search_text="",
    course_lines=None,
    courses=None,
    centres=None,
    auto_login=False,
    force_refresh=False,
):
    started_at = time.perf_counter()
    ensure_valid_token(auto_login=auto_login, force_refresh=force_refresh)

    stage_started = time.perf_counter()
    target_slot_summaries = fetch_target_slot_summaries(
        start_date,
        end_date,
        statuses,
        sessions,
        class_ids,
        search_text,
    )

    if not target_slot_summaries:
        session_text = ", ".join(map(str, sessions))
        print(f"⚠️ Không có lớp nào có buổi {session_text} trong khoảng ngày đã chọn.")
        return None, None
    print(f"⏱️ Slot summaries: {time.perf_counter() - stage_started:.1f}s")

    target_class_ids = sorted({
        normalize_text(item.get("class"))
        for item in target_slot_summaries
        if normalize_text(item.get("class"))
    })
    target_slot_ids = {
        normalize_text(item.get("slotId"))
        for item in target_slot_summaries
        if normalize_text(item.get("slotId"))
    }
    print(f"🎯 Lớp có slot mục tiêu: {len(target_class_ids)} lớp")
    print(f"🎯 Slot ID mục tiêu: {len(target_slot_ids)} slot")

    stage_started = time.perf_counter()
    classes = fetch_classes_by_ids(target_class_ids)
    print(f"⏱️ Class detail: {time.perf_counter() - stage_started:.1f}s")

    filtered_classes = filter_classes_by_product_filters(
        classes,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
    )
    if any((course_lines, courses, centres)):
        print(
            "🔎 Bộ lọc class detail: "
            f"course line={', '.join(course_lines or []) or 'tất cả'} · "
            f"course={', '.join(courses or []) or 'tất cả'} · "
            f"cơ sở={', '.join(centres or []) or 'tất cả'}"
        )
        print(f"🎯 Lớp sau bộ lọc: {len(filtered_classes)}/{len(classes)} lớp")
    classes = filtered_classes
    filtered_class_ids = {
        normalize_text(item.get("id"))
        for item in classes
        if normalize_text(item.get("id"))
    }
    target_slot_ids = {
        normalize_text(item.get("slotId"))
        for item in target_slot_summaries
        if normalize_text(item.get("slotId")) and normalize_text(item.get("class")) in filtered_class_ids
    }
    if not classes or not target_slot_ids:
        print("⚠️ Không có lớp nào phù hợp với bộ lọc course/course line/cơ sở đã chọn.")
        return None, None

    try:
        stage_started = time.perf_counter()
        area_map = fetch_comment_area_map()
        print(f"✅ Đã lấy {len(area_map)} vùng nhận xét ({time.perf_counter() - stage_started:.1f}s)")
    except Exception as exc:
        area_map = {}
        print(f"⚠️ Không lấy được danh sách vùng nhận xét, vẫn tiếp tục export: {exc}")

    stage_started = time.perf_counter()
    base_records, base_by_key, target_slots_by_id, _, students_by_class = build_base_records(
        classes,
        sessions,
        start_date,
        end_date,
        area_map,
        target_slot_ids=target_slot_ids,
    )
    print(f"⏱️ Tạo base records: {len(base_records)} dòng nền · {time.perf_counter() - stage_started:.1f}s")

    if not target_slots_by_id:
        session_text = ", ".join(map(str, sessions))
        print(f"⚠️ Không có lớp nào có buổi {session_text} trong khoảng ngày đã chọn.")
        return None, None

    stage_started = time.perf_counter()
    works = fetch_student_works(target_slots_by_id)
    print(f"⏱️ Student works: {len(works)} bản ghi · {time.perf_counter() - stage_started:.1f}s")

    stage_started = time.perf_counter()
    works_by_key = build_work_map(works, target_slots_by_id)
    ensure_work_base_records(base_records, base_by_key, works_by_key, target_slots_by_id, students_by_class, area_map)

    detail_rows = build_detail_rows(base_records, works_by_key)
    summary_rows = build_summary_rows(base_records, works_by_key)
    print(f"⏱️ Build rows: chi tiết {len(detail_rows)} dòng · thống kê {len(summary_rows)} dòng · {time.perf_counter() - stage_started:.1f}s")

    label = start_date.isoformat() if start_date == end_date else f"{start_date.isoformat()}_to_{end_date.isoformat()}"
    detail_file, summary_file = build_output_paths(label, sessions, output, summary_output)

    stage_started = time.perf_counter()
    detail_df = pd.DataFrame(detail_rows).reindex(columns=DETAIL_COLUMNS)
    summary_df = pd.DataFrame(summary_rows).reindex(columns=SUMMARY_COLUMNS)
    detail_df.to_csv(detail_file, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_file, index=False, encoding="utf-8-sig")
    print(f"⏱️ Ghi CSV: {time.perf_counter() - stage_started:.1f}s")

    total_students = sum(row["Tổng học viên"] for row in summary_rows)
    total_products = sum(row["Tổng sản phẩm"] for row in summary_rows)
    print(f"\n📚 Tổng slot buổi {', '.join(map(str, sessions))}: {len(target_slots_by_id)}")
    print(f"👤 Tổng học viên: {total_students}")
    print(f"🧩 Tổng sản phẩm: {total_products}")
    print(f"📁 Đã lưu chi tiết {len(detail_df)} dòng vào '{detail_file}'")
    print(f"📊 Đã lưu thống kê {len(summary_df)} dòng vào '{summary_file}'")
    print(f"⏱️ Tổng thời gian export: {time.perf_counter() - started_at:.1f}s")

    return detail_df, summary_df


def build_parser():
    parser = argparse.ArgumentParser(
        description=f"Xuất sản phẩm/nhận xét học viên buổi 12 và 13, mặc định lấy từ {DEFAULT_START_DATE} đến hôm nay."
    )
    parser.add_argument("period", nargs="?", help="Ngày cần lấy, format YYYY-MM-DD hoặc DD/MM/YYYY")
    parser.add_argument("--date", help="Ngày cần lấy, format YYYY-MM-DD hoặc DD/MM/YYYY")
    parser.add_argument("--start", help="Ngày bắt đầu, format YYYY-MM-DD hoặc DD/MM/YYYY; nếu không có --end thì lấy đến hôm nay")
    parser.add_argument("--end", help="Ngày kết thúc, format YYYY-MM-DD hoặc DD/MM/YYYY")
    parser.add_argument("--sessions", default=",".join(map(str, DEFAULT_SESSION_NUMBERS)), help="Danh sách buổi, ví dụ 12,13")
    parser.add_argument("--statuses", default=",".join(DEFAULT_CLASS_STATUSES), help="Trạng thái lớp, ví dụ RUNNING,FINISHED")
    parser.add_argument("--class-id", help="Lọc theo một hoặc nhiều class id, cách nhau bằng dấu phẩy")
    parser.add_argument("--search", default="", help="Lọc mã lớp/tên lớp giống filter_textSearch trên LMS")
    parser.add_argument("--course-line", dest="course_lines", help="Lọc course line/khối, ví dụ C4K,ROB")
    parser.add_argument("--course", dest="courses", help="Lọc course id/code/shortName, cách nhau bằng dấu phẩy")
    parser.add_argument("--centre", "--center", dest="centres", help="Lọc cơ sở theo id/shortName/tên, cách nhau bằng dấu phẩy")
    parser.add_argument("--output", help="Tên file CSV chi tiết")
    parser.add_argument("--summary-output", help="Tên file CSV thống kê")
    parser.add_argument("--login", action="store_true", help="Mở web LMS để đăng nhập/lấy token nếu cache chưa có")
    parser.add_argument("--force-refresh", action="store_true", help="Bỏ qua id token hiện tại và refresh/lấy token mới")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        start_date, end_date, _ = resolve_date_range(args)
        sessions = parse_session_numbers(args.sessions)
        statuses = parse_csv_values(args.statuses, upper=True)
        class_ids = parse_csv_values(args.class_id) if args.class_id else None
        export_products(
            start_date,
            end_date,
            sessions,
            statuses,
            args.output,
            args.summary_output,
            class_ids,
            args.search,
            course_lines=parse_filter_values(args.course_lines, upper=True),
            courses=parse_filter_values(args.courses),
            centres=parse_filter_values(args.centres),
            auto_login=args.login,
            force_refresh=args.force_refresh,
        )
    except Exception as exc:
        print(f"❌ {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
