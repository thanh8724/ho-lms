import os
import csv
import time
import argparse
import base64
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time, date
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter, Retry

from lms_auth import (
    TOKEN_HELP as SHARED_TOKEN_HELP,
    build_auth_headers,
    ensure_auth_token,
)

load_dotenv()

AUTH_TOKEN = ""

AUTH_TOKEN = (os.getenv("LMS_AUTH_TOKEN") or os.getenv("AUTH_TOKEN") or AUTH_TOKEN).strip()

API_URL = "https://lms-api.mindx.edu.vn/graphql"
API_ROOT_URL = "https://lms-api.mindx.edu.vn/"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = SCRIPT_DIR
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC_TZ = ZoneInfo("UTC")

DEFAULT_START_DATE = "2026-07-01"
DEFAULT_END_DATE = "2026-07-17"
DEFAULT_LIMIT = 100
COURSES_PER_PAGE = 100
COURSE_LINES_PER_PAGE = int(os.getenv("COURSE_LINES_PER_PAGE", "100"))
CENTRES_PER_PAGE = int(os.getenv("CENTRES_PER_PAGE", "100"))
DEFAULT_CENTER_IDS = []
DEFAULT_TYPES = []
DEFAULT_STATUSES = []
DEFAULT_IS_SATISFIED = None
DEFAULT_SUBJECT_CODES = []
DEFAULT_SUBJECT_OPTIONS = ("PTB", "PREB", "DAFB", "VTB", "GAB", "CMB", "AM-VCO")
DEFAULT_DATE_FIELD = "startDate"
DEFAULT_REQUEST_TEACHER_WORKERS = int(os.getenv("REQUEST_TEACHER_WORKERS", "12"))
DEFAULT_REQUEST_TEACHER_BULK_LIMIT = int(os.getenv("REQUEST_TEACHER_BULK_LIMIT", "500"))
REQUEST_TEACHER_FILTER_CLASS_LIMIT = int(os.getenv("REQUEST_TEACHER_FILTER_CLASS_LIMIT", str(DEFAULT_LIMIT)))
REQUEST_TEACHER_FILTER_FACET_PAGES = int(os.getenv("REQUEST_TEACHER_FILTER_FACET_PAGES", "4"))
REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES = int(os.getenv("REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES", "3"))
REQUEST_TEACHER_PROGRESS_EVERY = int(os.getenv("REQUEST_TEACHER_PROGRESS_EVERY", "50"))
CLASS_SEARCH_MIN_CHARS = int(os.getenv("CLASS_SEARCH_MIN_CHARS", "2"))
DATE_FIELD_LABELS = {
    "startDate": "class.startDate",
    "endDate": "class.endDate",
}
PROGRAM_GROUP_ORDER = {
    "Coding": 0,
    "Robotics": 1,
    "Digital Art": 2,
}

HEADERS = {
    "Authorization": AUTH_TOKEN,
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://lms.mindx.edu.vn",
    "Referer": "https://lms.mindx.edu.vn/",
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

TOKEN_HELP = (
    "Token LMS đã hết hạn hoặc không hợp lệ. "
    "Hãy lấy token mới rồi đặt vào biến môi trường LMS_AUTH_TOKEN hoặc AUTH_TOKEN."
)
TOKEN_HELP = SHARED_TOKEN_HELP

CSV_COLUMNS = [
    "program.group",
    "id",
    "type",
    "class.name",
    "mã lớp basic",
    "Course",
    "Course line",
    "class.studentCount",
    "class.startDate.VN",
    "class.endDate.VN",
    "class.status",
    "center.shortName",
    "center.name",
    "class.centre.shortName",
    "class.centre.name",
    "classSite.name",
    "requestTeacherClassSite.name",
    "sessions.startTime.min.VN",
    "sessions.startTime.all.VN",
    "sessions.teachers",
    "status",
    "isSatisfied",
    "exceptionalReason",
    "createdBy.displayName",
    "createdBy.username",
    "createdBy.email",
    "createdAt.VN",
    "lastModifiedBy.displayName",
    "lastModifiedBy.username",
    "lastModifiedBy.email",
    "lastModifiedAt.VN",
]

REQUEST_TEACHER_QUERY = """
query FindRequestTeacher($payload: FindPaginateRequestTeacherPayload) {
  findRequestTeacher(payload: $payload) {
    total
    data {
      id
      status
      type
      isSatisfied
      exceptionalReason
      createdAt
      lastModifiedAt
      center { id shortName name }
      createdBy { id username email displayName }
      lastModifiedBy { id username email displayName }
      class {
        id
        name
        startDate
        endDate
        status
        centre { id shortName name }
        course { id code shortName name }
      }
      classSite { _id name }
      requestTeacherClassSite {
        id
        name
        center { id name }
      }
      sessions {
        id
        startTime
        teachers {
          teacher { id code fullName username email }
        }
      }
    }
  }
}
"""

CLASS_QUERY = """
query Classes($payload: ClassQuery) {
  classes(payload: $payload) {
    data {
      id
      name
      startDate
      endDate
      status
      centre { id shortName name }
      course { id code shortName name }
    }
    pagination {
      total
      type
      nextCursor
      prevCursor
    }
  }
}
"""

GET_CLASSES_FILTER_QUERY = """
query GetClasses($search: String, $centres: [String], $courses: [String], $courseLines: [String], $pageIndex: Int!, $itemsPerPage: Int!, $orderBy: String) {
  classes(payload: {filter_textSearch: $search, centre_in: $centres, course_in: $courses, courseLine_in: $courseLines, pageIndex: $pageIndex, itemsPerPage: $itemsPerPage, orderBy: $orderBy}) {
    data {
      id
      name
    }
    pagination {
      type
      total
    }
  }
}
"""

CENTRES_QUERY = """
query getCentres($search: String, $isActive: Boolean, $pageIndex: Int!, $itemsPerPage: Int!, $orderBy: String) {
  centres(payload: {filter_textSearch: $search, isActive_eq: $isActive, pageIndex: $pageIndex, itemsPerPage: $itemsPerPage, orderBy: $orderBy}) {
    data {
      id
      shortName
      name
      hotline
      email
      address
      isActive
    }
    pagination {
      type
      total
    }
  }
}
"""

COURSES_QUERY = """
query getCourses($search: String, $isActive: Boolean, $courseLine: String, $courseTopic: String, $pageIndex: Int!, $itemsPerPage: Int!, $orderBy: String, $listIds: [String], $idNotIn: [String]) {
  courses(payload: {searchString_wordSearch: $search, isActive_eq: $isActive, courseLine_eq: $courseLine, courseTopic_eq: $courseTopic, pageIndex: $pageIndex, itemsPerPage: $itemsPerPage, orderBy: $orderBy, id_in: $listIds, id_nin: $idNotIn}) {
    data {
      id
      name
      shortName
      isActive
      isReady
      courseLine {
        id
        name
      }
      courseTopic {
        id
        name
      }
    }
    pagination {
      type
      total
    }
  }
}
"""

COURSE_LINES_QUERY = """
query getCourseLines($search: String, $isActive: Boolean, $pageIndex: Int!, $itemsPerPage: Int!, $orderBy: String) {
  courseLines(payload: {searchString_wordSearch: $search, isActive_eq: $isActive, pageIndex: $pageIndex, itemsPerPage: $itemsPerPage, orderBy: $orderBy}) {
    data {
      id
      name
      description
      isActive
      category
      createdAt
      createdBy
      lastModifiedAt
      lastModifiedBy
    }
    pagination {
      type
      total
    }
  }
}
"""

def build_courses_query(page_index, limit=COURSES_PER_PAGE, text_search=""):
    filters = [
        f"pageIndex: {page_index}",
        f"itemsPerPage: {limit}",
    ]
    if text_search:
        filters.append(f'filter_textSearch: "{escape_graphql_string(text_search)}"')

    return f"""
    {{
      courses(payload: {{ {", ".join(filters)} }}) {{
        data {{
          id
          name
          shortName
          isActive
          isReady
        }}
        pagination {{
          total
          type
          nextCursor
          prevCursor
        }}
      }}
    }}
    """


def create_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def decode_jwt_payload(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def refresh_auth_token(auto_login=False, force_refresh=False):
    global AUTH_TOKEN, HEADERS

    AUTH_TOKEN = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    HEADERS = build_auth_headers(AUTH_TOKEN)
    return AUTH_TOKEN


def validate_auth_token(auto_login=False, force_refresh=False):
    refresh_auth_token(auto_login=auto_login, force_refresh=force_refresh)

    if not AUTH_TOKEN:
        raise RuntimeError(TOKEN_HELP)

    payload = decode_jwt_payload(AUTH_TOKEN)
    expires_at = payload.get("exp")

    if not expires_at:
        return

    if int(time.time()) >= int(expires_at):
        expires_at_vn = datetime.fromtimestamp(int(expires_at), tz=UTC_TZ).astimezone(VN_TZ)
        raise RuntimeError(
            f"{TOKEN_HELP}\n"
            f"Token hiện tại đã hết hạn lúc {expires_at_vn.strftime('%Y-%m-%d %H:%M:%S')} VN."
        )


def is_auth_error(errors):
    return "Authentication failed" in str(errors)


def parse_vn_date(value):
    if isinstance(value, date):
        return value

    value = str(value).strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Ngày không hợp lệ: {value}. Dùng YYYY-MM-DD hoặc DD/MM/YYYY.")


def vn_date_range_to_epoch_ms(start_date, end_date):
    start = parse_vn_date(start_date)
    end = parse_vn_date(end_date)

    if start > end:
        raise ValueError("start_date phải nhỏ hơn hoặc bằng end_date")

    start_vn = datetime.combine(start, dt_time.min).replace(tzinfo=VN_TZ)
    end_vn = datetime.combine(end, dt_time.max).replace(tzinfo=VN_TZ)

    return int(start_vn.timestamp() * 1000), int(end_vn.timestamp() * 1000)


def parse_api_datetime(value):
    if value in (None, ""):
        return None

    value = str(value).strip()

    try:
        if value.isdigit():
            timestamp = int(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=UTC_TZ)

        if "GMT" in value:
            cleaned = value.split(" (", 1)[0]
            return datetime.strptime(cleaned, "%a %b %d %Y %H:%M:%S GMT%z")

        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC_TZ)
        return parsed
    except Exception:
        return None


def api_datetime_to_epoch_ms(value):
    parsed = parse_api_datetime(value)
    if not parsed:
        return None
    return int(parsed.timestamp() * 1000)


def format_datetime_vn(value):
    parsed = parse_api_datetime(value)
    if not parsed:
        return value or None
    return parsed.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def normalize_for_search(value):
    normalized = unicodedata.normalize("NFD", str(value or "").strip().lower())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.replace("đ", "d")
    return "".join(ch for ch in normalized if ch.isalnum())


def compact_join(values):
    return " | ".join(str(value) for value in values if value not in (None, ""))


def resolve_output_path(path, base_dir=SCRIPT_DIR):
    if os.path.isabs(path):
        return path
    return os.path.join(base_dir, path)


def normalize_date_field(value):
    cleaned = str(value or DEFAULT_DATE_FIELD).strip()
    if cleaned in DATE_FIELD_LABELS:
        return cleaned
    lowered = cleaned.lower()
    aliases = {
        "start": "startDate",
        "startdate": "startDate",
        "start_date": "startDate",
        "start-day": "startDate",
        "startday": "startDate",
        "end": "endDate",
        "enddate": "endDate",
        "end_date": "endDate",
        "end-day": "endDate",
        "endday": "endDate",
    }
    if lowered in aliases:
        return aliases[lowered]
    raise ValueError("date_field phải là startDate hoặc endDate.")


def build_output_file(start_date, end_date, date_field=DEFAULT_DATE_FIELD):
    start = parse_vn_date(start_date).isoformat()
    end = parse_vn_date(end_date).isoformat()
    field_label = DATE_FIELD_LABELS[normalize_date_field(date_field)].replace(".", "")
    return resolve_output_path(f"request_teacher_{field_label}_{start}_to_{end}_VN.csv")


def epoch_ms_to_utc_iso(value):
    return datetime.fromtimestamp(value / 1000, tz=UTC_TZ).isoformat().replace("+00:00", "Z")


def build_class_payload(
    page_index,
    limit=DEFAULT_LIMIT,
    start_date=DEFAULT_START_DATE,
    end_date=DEFAULT_END_DATE,
    center_ids=None,
    class_ids=None,
    text_search="",
    date_field=DEFAULT_DATE_FIELD,
):
    start_ms, end_ms = vn_date_range_to_epoch_ms(start_date, end_date)
    field = normalize_date_field(date_field)

    payload = {
        f"{field}_gt": epoch_ms_to_utc_iso(start_ms - 1),
        f"{field}_lt": epoch_ms_to_utc_iso(end_ms + 1),
        "orderBy": f"{field}_desc",
        "paginationType": "OFFSET",
        "pageIndex": page_index,
        "itemsPerPage": limit,
    }

    if center_ids:
        payload["centre_in"] = center_ids
    if class_ids:
        payload["id_in"] = class_ids
    if text_search:
        payload["filter_textSearch"] = text_search

    return {
        "operationName": "Classes",
        "variables": {"payload": payload},
        "query": CLASS_QUERY,
    }


def build_request_teacher_payload(
    page_index,
    limit=DEFAULT_LIMIT,
    center_ids=None,
    request_types=None,
    statuses=None,
    is_satisfied=None,
    text_search="",
):
    filter_payload = {}

    if text_search:
        filter_payload["search_textSearch"] = text_search
    if center_ids:
        filter_payload["center_in"] = center_ids
    if request_types:
        filter_payload["type_in"] = request_types
    if statuses:
        filter_payload["status_in"] = statuses
    if is_satisfied is not None:
        filter_payload["isSatisfied_equals"] = is_satisfied

    return {
        "operationName": "FindRequestTeacher",
        "variables": {
            "payload": {
                "filter": filter_payload,
                "pagination": {
                    "page": page_index,
                    "limit": limit,
                    "paginationType": "OFFSET",
                },
                "orderBy": "createdAt_desc",
            }
        },
        "query": REQUEST_TEACHER_QUERY,
    }


def format_teacher(teacher):
    if not teacher:
        return None

    code = teacher.get("code")
    name = teacher.get("fullName") or teacher.get("username") or teacher.get("email")

    if code and name:
        return f"{code} - {name}"

    return code or name or teacher.get("id")


def collect_teachers(sessions):
    teachers = []
    seen = set()

    for session_item in sessions or []:
        for teacher_item in (session_item or {}).get("teachers") or []:
            teacher = (teacher_item or {}).get("teacher") or {}
            value = format_teacher(teacher)
            key = teacher.get("id") or value

            if value and key not in seen:
                teachers.append(value)
                seen.add(key)

    return compact_join(teachers)


def session_start_time_ms_values(request_teacher):
    start_times = []

    for session_item in request_teacher.get("sessions") or []:
        start_time_ms = api_datetime_to_epoch_ms((session_item or {}).get("startTime"))
        if start_time_ms is not None:
            start_times.append(start_time_ms)

    return start_times


def request_teacher_start_date_ms(request_teacher):
    start_times = session_start_time_ms_values(request_teacher)
    return min(start_times) if start_times else None


def format_epoch_ms_vn(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC_TZ).astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def format_epoch_ms_values_vn(values):
    return compact_join(format_epoch_ms_vn(value) for value in values)


def class_start_date_ms(class_info):
    return api_datetime_to_epoch_ms((class_info or {}).get("startDate"))


def class_date_ms(class_info, date_field=DEFAULT_DATE_FIELD):
    return api_datetime_to_epoch_ms((class_info or {}).get(normalize_date_field(date_field)))


def class_student_count(class_info):
    students = (class_info or {}).get("students")
    if not isinstance(students, list):
        return None
    active_students = [
        student
        for student in students
        if not isinstance(student, dict) or student.get("activeInClass", True)
    ]
    return len(active_students)


def course_matches_subjects(class_info, subject_codes=None):
    subject_set = set()
    for value in subject_codes or []:
        normalized = str(value).strip().upper()
        if not normalized:
            continue
        subject_set.add(normalized)
        compact = "".join(ch for ch in normalized if ch.isalnum())
        if compact:
            subject_set.add(compact)
    if not subject_set:
        return True

    candidates = subject_code_candidates(class_info)
    return any(candidate in subject_set for candidate in candidates)


def entity_values(entity, keys=("id", "code", "shortName", "name", "label", "value")):
    values = []
    if isinstance(entity, dict):
        for key in keys:
            values.append(entity.get(key))
    else:
        values.append(entity)
    return [str(value).strip() for value in values if str(value or "").strip()]


def first_entity_value(entity, keys=("id", "code", "shortName", "name", "label", "value")):
    values = entity_values(entity, keys)
    return values[0] if values else ""


def unique_keep_order(values):
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def course_display(class_info):
    course = (class_info or {}).get("course") or {}
    code = str(course.get("shortName") or course.get("code") or "").strip()
    name = str(course.get("name") or "").strip()
    if code and name and normalize_for_search(code) not in normalize_for_search(name):
        return f"{code} - {name}"
    return code or name or str(course.get("id") or "").strip()


def course_line_entity(class_info):
    class_info = class_info or {}
    course = class_info.get("course") or {}
    for value in (
        class_info.get("courseLine"),
        class_info.get("course_line"),
        class_info.get("line"),
        course.get("courseLine") if isinstance(course, dict) else None,
        course.get("course_line") if isinstance(course, dict) else None,
        course.get("line") if isinstance(course, dict) else None,
    ):
        if value:
            return value
    return {}


def infer_course_line_from_class(class_info):
    text = class_search_text(class_info)
    tokens = re.findall(r"[A-Z0-9]+", text.upper())
    compact = "".join(tokens)
    known_lines = (
        "C4K", "ROB", "XART", "C4P", "C4E", "C4T", "WRO", "PTB", "PREB",
        "VTB", "GAB", "CMB", "DAFB", "AMVCO", "AM-VCO",
    )
    for line in known_lines:
        compact_line = compact_subject_code(line)
        if line in tokens or compact_line in compact:
            return line
    return ""


def course_line_display(class_info):
    line = course_line_entity(class_info)
    value = first_entity_value(line, ("shortName", "code", "name", "label", "value", "id"))
    return value or infer_course_line_from_class(class_info) or class_program_group(class_info)


def get_centre_name(class_info):
    centre = (class_info or {}).get("centre") or {}
    return (
        str(centre.get("name") or "").strip()
        or str(centre.get("shortName") or "").strip()
        or str(centre.get("id") or "").strip()
    )


def normalized_filter_set(values):
    return {
        normalize_for_search(value)
        for value in (values or [])
        if normalize_for_search(value)
    }


def matches_selected_filter(selected_values, candidates):
    if not selected_values:
        return True
    return any(normalize_for_search(candidate) in selected_values for candidate in candidates)


def course_candidates(class_info):
    course = (class_info or {}).get("course") or {}
    return unique_keep_order(entity_values(course) + [course_display(class_info)])


def course_line_candidates(class_info):
    line = course_line_entity(class_info)
    return unique_keep_order(entity_values(line) + [course_line_display(class_info), class_program_group(class_info)])


def centre_candidates(class_info):
    centre = (class_info or {}).get("centre") or {}
    return unique_keep_order(entity_values(centre) + [get_centre_name(class_info)])


def class_matches_extra_filters(class_info, course_lines=None, courses=None, centres=None):
    return (
        matches_selected_filter(normalized_filter_set(course_lines), course_line_candidates(class_info))
        and matches_selected_filter(normalized_filter_set(courses), course_candidates(class_info))
        and matches_selected_filter(normalized_filter_set(centres), centre_candidates(class_info))
    )


def add_filter_option(options, seen, value, label=None, name=None):
    value = str(value or "").strip()
    label = str(label or value).strip()
    name = str(name or "").strip()
    if not value or value in seen:
        return
    seen.add(value)
    options.append({"value": value, "label": label, "name": name})


def option_sort_key(option):
    return (str(option.get("label") or "").lower(), str(option.get("name") or "").lower())


def build_class_filter_options_from_classes(classes):
    course_lines = []
    courses = []
    centres = []
    subjects = set()
    class_options = []
    seen_course_lines = set()
    seen_courses = set()
    seen_centres = set()
    seen_classes = set()

    for class_info in classes or []:
        class_id = str((class_info or {}).get("id") or "").strip()
        class_name = str((class_info or {}).get("name") or "").strip()
        course = (class_info or {}).get("course") or {}
        centre = (class_info or {}).get("centre") or {}
        line = course_line_entity(class_info)
        subject = preferred_subject_code(class_info)

        if subject:
            subjects.add(subject)

        line_value = first_entity_value(line) or course_line_display(class_info)
        line_label = first_entity_value(line, ("shortName", "code", "name", "label", "value")) or line_value
        add_filter_option(course_lines, seen_course_lines, line_value, line_label)

        course_value = first_entity_value(course)
        course_label = first_entity_value(course, ("shortName", "code", "name", "label", "value")) or course_display(class_info)
        add_filter_option(courses, seen_courses, course_value, course_label, course_display(class_info))

        centre_value = first_entity_value(centre)
        centre_label = get_centre_name(class_info) or first_entity_value(centre, ("shortName", "name", "label", "value"))
        add_filter_option(centres, seen_centres, centre_value, centre_label)

        if class_id and class_name and class_id not in seen_classes:
            seen_classes.add(class_id)
            class_options.append({
                "id": class_id,
                "name": class_name,
                "subject": subject,
                "course": course_display(class_info),
                "centre": get_centre_name(class_info),
            })

    return {
        "subjects": sorted(subjects),
        "course_lines": sorted(course_lines, key=option_sort_key),
        "courses": sorted(courses, key=option_sort_key),
        "centres": sorted(centres, key=option_sort_key),
        "classes": sorted(class_options, key=lambda item: str(item["name"]).lower()),
    }


def compact_subject_code(value):
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())


def class_search_text(class_info):
    course = (class_info or {}).get("course") or {}
    values = [
        (class_info or {}).get("name"),
        course.get("code"),
        course.get("shortName"),
        course.get("name"),
    ]
    return " ".join(str(value or "").strip().upper() for value in values if str(value or "").strip())


def configured_subject_codes_from_text(value):
    text = str(value or "").strip().upper()
    compact_text = compact_subject_code(text)
    if not text:
        return set()

    matches = set()
    tokens = re.findall(r"[A-Z]+[A-Z0-9]*", text)
    normalized_tokens = {
        re.sub(r"\d+$", "", token)
        for token in tokens
        if token
    }

    for subject in DEFAULT_SUBJECT_OPTIONS:
        subject_text = subject.upper()
        subject_compact = compact_subject_code(subject_text)
        if not subject_compact:
            continue
        if text == subject_text or compact_text == subject_compact:
            matches.add(subject_text)
            continue
        if subject_text in text:
            matches.add(subject_text)
            continue
        if any(token == subject_compact for token in normalized_tokens):
            matches.add(subject_text)
            continue
        if re.search(rf"{re.escape(subject_compact)}\d*$", compact_text):
            matches.add(subject_text)

    return matches


def class_program_group(class_info):
    text = class_search_text(class_info)
    compact = compact_subject_code(text)
    candidates = set(subject_code_candidates(class_info))
    compact_candidates = {compact_subject_code(candidate) for candidate in candidates}

    robotics_keywords = {"ROB", "ROBOT", "ROBOTICS", "WRO", "KIND", "ROB4MN", "PREB"}
    digital_art_keywords = {"XART", "VTB", "GAB", "CMB", "AMVCO", "AM-VCO", "DIGITALART", "DAFB"}
    coding_keywords = {
        "C4K", "CODING", "CODE", "CSB", "CSA", "CSI", "JSB", "JSA", "JSI",
        "PTB", "SB", "SA", "SI", "AI4A",
    }

    if any(keyword in text or keyword in compact or keyword in compact_candidates for keyword in robotics_keywords):
        return "Robotics"
    if any(keyword in text or keyword in compact or keyword in candidates or keyword in compact_candidates for keyword in digital_art_keywords):
        return "Digital Art"
    if any(keyword in text or keyword in compact or keyword in candidates or keyword in compact_candidates for keyword in coding_keywords):
        return "Coding"
    return "Coding"


def subject_code_candidates(class_info):
    course = (class_info or {}).get("course") or {}
    raw_values = [
        course.get("code"),
        course.get("shortName"),
        course.get("name"),
    ]
    class_name = str((class_info or {}).get("name") or "").strip().upper()
    if class_name:
        raw_values.extend([
            class_name.split("-", 1)[0].strip(),
            class_name.split("_", 1)[0].strip(),
        ])

    candidates = set()
    for raw_value in raw_values:
        value = str(raw_value or "").strip().upper()
        if not value:
            continue
        candidates.update(configured_subject_codes_from_text(value))
        candidates.add(value)
        for token in value.replace("_", "-").replace("/", "-").split("-"):
            token = token.strip()
            if token:
                candidates.add(token)
                stripped_token = re.sub(r"\d+$", "", token)
                if stripped_token:
                    candidates.add(stripped_token)
        compact = compact_subject_code(value)
        if compact:
            candidates.add(compact)

    return tuple(sorted(candidates))


def class_filter_option(class_info):
    subject = preferred_subject_code(class_info)
    return {
        "id": (class_info or {}).get("id"),
        "name": (class_info or {}).get("name"),
        "subject": subject,
    }


def preferred_subject_code(class_info):
    course = (class_info or {}).get("course") or {}
    class_name_subjects = configured_subject_codes_from_text((class_info or {}).get("name"))
    if class_name_subjects:
        return sorted(class_name_subjects, key=lambda value: (len(value), value))[0]

    for raw_value in (course.get("code"), course.get("shortName"), course.get("name")):
        value = str(raw_value or "").strip().upper()
        configured = configured_subject_codes_from_text(value)
        if configured:
            return sorted(configured, key=lambda item: (len(item), item))[0]
        compact = compact_subject_code(value)
        if not compact:
            continue
        if value in DEFAULT_SUBJECT_OPTIONS:
            return value
        if len(compact) == 3 and compact[0] in {"C", "J"} and compact[1:] in {"SB", "SA", "SI"}:
            return compact[1:]
        if 2 <= len(compact) <= 4:
            return compact

    candidates = subject_code_candidates(class_info)
    short = [
        candidate
        for candidate in candidates
        if 2 <= len(candidate) <= 4 and candidate.isalnum() and any(ch.isalpha() for ch in candidate)
    ]
    return sorted(short, key=lambda value: (len(value), value))[0] if short else (candidates[0] if candidates else "")


def course_option_value(course):
    course = course or {}
    course_id = str(course.get("id") or "").strip()
    fallback = str(course.get("shortName") or course.get("name") or "").strip().upper()
    return course_id or fallback


def course_filter_option(course):
    course = course or {}
    value = course_option_value(course)
    name = str(course.get("name") or "").strip()
    short_name = str(course.get("shortName") or "").strip()
    label = short_name or name or value
    if short_name and name and normalize_for_search(short_name) not in normalize_for_search(name):
        label = f"{short_name} - {name}"
    return {
        "id": course.get("id"),
        "value": value,
        "label": label or value,
        "name": name,
        "isActive": bool(course.get("isActive", True)),
    }


def course_line_filter_option(course):
    line = (course or {}).get("courseLine") or {}
    if not isinstance(line, dict):
        return None
    line_id = str(line.get("id") or "").strip()
    name = str(line.get("name") or "").strip()
    value = name or line_id
    if not value:
        return None
    return {
        "id": line_id,
        "value": value,
        "label": name or value,
        "name": line_id if line_id and line_id != value else "",
    }


def course_line_api_filter_option(course_line):
    course_line = course_line or {}
    line_id = str(course_line.get("id") or "").strip()
    name = str(course_line.get("name") or "").strip()
    category = str(course_line.get("category") or "").strip()
    description = str(course_line.get("description") or "").strip()
    value = name or line_id
    if not value:
        return None
    meta = category or description or line_id
    return {
        "id": line_id,
        "value": value,
        "label": name or value,
        "name": meta if meta and meta != value else "",
        "isActive": bool(course_line.get("isActive", True)),
    }


def post_graphql_payload(payload, session=None, timeout=(10, 60), urls=None):
    active_session = session or create_session()
    last_error = None
    for url in (urls or (API_URL, API_ROOT_URL)):
        try:
            response = active_session.post(url, headers=HEADERS, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            last_error = error
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code not in {404, 405}:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("Không thể gửi request GraphQL.")


def centre_filter_option(centre):
    centre = centre or {}
    centre_id = str(centre.get("id") or "").strip()
    short_name = str(centre.get("shortName") or "").strip()
    name = str(centre.get("name") or "").strip()
    label = name or short_name or centre_id
    meta = short_name if short_name and short_name != label else name
    return {
        "value": centre_id or short_name or name,
        "label": label,
        "name": meta,
        "isActive": bool(centre.get("isActive", True)),
    }


def fetch_centre_filter_options(
    search="",
    active_only=True,
    limit=CENTRES_PER_PAGE,
    order_by="createdAt_desc",
    auto_login=False,
    force_refresh=False,
    skip_auth=False,
):
    if not skip_auth:
        validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    active_session = create_session()
    page_index = 0
    scanned_count = 0
    options = []
    seen_values = set()
    started_at = time.perf_counter()

    while True:
        payload = {
            "operationName": "getCentres",
            "query": CENTRES_QUERY,
            "variables": {
                "search": str(search or ""),
                "isActive": True if active_only else None,
                "pageIndex": page_index,
                "itemsPerPage": max(1, int(limit or CENTRES_PER_PAGE)),
                "orderBy": order_by,
            },
        }
        try:
            res_json = post_graphql_payload(
                payload,
                session=active_session,
                timeout=(10, 30),
                urls=(API_ROOT_URL, API_URL),
            )
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi tải danh sách cơ sở trang {page_index}: {error}") from error

        if "errors" in res_json:
            if is_auth_error(res_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi tải danh sách cơ sở trang {page_index}: {res_json['errors']}")

        centre_data = res_json.get("data", {}).get("centres", {})
        centre_items = centre_data.get("data") or []
        pagination = centre_data.get("pagination") or {}
        centre_total = pagination.get("total") or 0
        if not centre_items:
            break

        scanned_count += len(centre_items)
        for item in centre_items:
            option = centre_filter_option(item)
            value = str(option.get("value") or "").strip()
            if not value or value in seen_values:
                continue
            if active_only and not option.get("isActive", True):
                continue
            seen_values.add(value)
            options.append(option)

        if scanned_count >= centre_total or len(centre_items) < int(limit or CENTRES_PER_PAGE):
            break

        page_index += 1
        time.sleep(0.03)

    print(
        f"✅ Tải {len(options)} cơ sở trực tiếp từ centres API trong {time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return sorted(options, key=option_sort_key)


def fetch_course_line_filter_options(
    search="",
    active_only=True,
    limit=COURSE_LINES_PER_PAGE,
    order_by="createdAt_desc",
    auto_login=False,
    force_refresh=False,
    skip_auth=False,
):
    if not skip_auth:
        validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    active_session = create_session()
    page_index = 0
    scanned_count = 0
    options = []
    seen_values = set()
    started_at = time.perf_counter()

    while True:
        per_page = max(1, int(limit or COURSE_LINES_PER_PAGE))
        payload = {
            "operationName": "getCourseLines",
            "query": COURSE_LINES_QUERY,
            "variables": {
                "search": str(search or ""),
                "isActive": True if active_only else None,
                "pageIndex": page_index,
                "itemsPerPage": per_page,
                "orderBy": order_by,
            },
        }
        try:
            res_json = post_graphql_payload(
                payload,
                session=active_session,
                timeout=(10, 30),
                urls=(API_ROOT_URL, API_URL),
            )
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi tải danh sách course line trang {page_index}: {error}") from error

        if "errors" in res_json:
            if is_auth_error(res_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi tải danh sách course line trang {page_index}: {res_json['errors']}")

        line_data = res_json.get("data", {}).get("courseLines", {})
        line_items = line_data.get("data") or []
        pagination = line_data.get("pagination") or {}
        line_total = pagination.get("total") or 0
        if not line_items:
            break

        scanned_count += len(line_items)
        for item in line_items:
            option = course_line_api_filter_option(item)
            if not option:
                continue
            value = str(option.get("value") or "").strip()
            key = normalize_for_search(value)
            if not key or key in seen_values:
                continue
            if active_only and not option.get("isActive", True):
                continue
            seen_values.add(key)
            options.append(option)

        if scanned_count >= line_total or len(line_items) < per_page:
            break

        page_index += 1
        time.sleep(0.03)

    print(
        f"✅ Tải {len(options)} course line trực tiếp từ courseLines API trong {time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return sorted(options, key=option_sort_key)


def fetch_course_filter_options(
    text_search="",
    limit=COURSES_PER_PAGE,
    active_only=True,
    auto_login=False,
    force_refresh=False,
    skip_auth=False,
):
    return fetch_course_and_line_filter_options(
        text_search=text_search,
        limit=limit,
        active_only=active_only,
        auto_login=auto_login,
        force_refresh=force_refresh,
        skip_auth=skip_auth,
    )["courses"]


def fetch_course_and_line_filter_options(
    text_search="",
    limit=COURSES_PER_PAGE,
    active_only=True,
    order_by="createdAt_desc",
    auto_login=False,
    force_refresh=False,
    skip_auth=False,
):
    if not skip_auth:
        validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    session = create_session()
    search_text = str(text_search or "").strip()
    page_index = 0
    scanned_count = 0
    course_options = []
    course_line_options = []
    seen_courses = set()
    seen_course_lines = set()
    started_at = time.perf_counter()

    def add_option(options, seen, option):
        if not option:
            return
        value = str(option.get("value") or "").strip()
        key = normalize_for_search(value)
        if not key or key in seen:
            return
        seen.add(key)
        options.append(option)

    while True:
        per_page = max(1, int(limit or COURSES_PER_PAGE))
        payload = {
            "operationName": "getCourses",
            "query": COURSES_QUERY,
            "variables": {
                "search": search_text,
                "isActive": True if active_only else None,
                "pageIndex": page_index,
                "itemsPerPage": per_page,
                "orderBy": order_by,
            },
        }
        try:
            res_json = post_graphql_payload(
                payload,
                session=session,
                timeout=(10, 30),
                urls=(API_ROOT_URL, API_URL),
            )
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi tải danh sách course ở trang {page_index}: {error}") from error

        if "errors" in res_json:
            if is_auth_error(res_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi tải danh sách course trang {page_index}: {res_json['errors']}")

        course_data = res_json.get("data", {}).get("courses", {})
        course_items = course_data.get("data") or []
        pagination = course_data.get("pagination") or {}
        course_total = pagination.get("total") or 0

        if not course_items:
            break

        scanned_count += len(course_items)
        for item in course_items:
            course_option = course_filter_option(item)
            if active_only and not course_option["isActive"]:
                continue
            add_option(course_options, seen_courses, course_option)
            add_option(course_line_options, seen_course_lines, course_line_filter_option(item))

        if scanned_count >= course_total or len(course_items) < per_page:
            break

        page_index += 1
        time.sleep(0.03)

    print(
        f"✅ Tải {len(course_options)} course và {len(course_line_options)} course line "
        f"trực tiếp từ courses API trong {time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return {
        "course_lines": sorted(course_line_options, key=option_sort_key),
        "courses": sorted(course_options, key=option_sort_key),
    }


def fetch_request_teacher_fast_filter_options(auto_login=False, force_refresh=False):
    validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            "centres": executor.submit(
                fetch_centre_filter_options,
                auto_login=False,
                force_refresh=False,
                skip_auth=True,
            ),
            "course_lines": executor.submit(
                fetch_course_line_filter_options,
                auto_login=False,
                force_refresh=False,
                skip_auth=True,
            ),
            "courses": executor.submit(
                fetch_course_and_line_filter_options,
                auto_login=False,
                force_refresh=False,
                skip_auth=True,
            ),
        }
        centres = futures["centres"].result()
        course_lines = futures["course_lines"].result()
        course_payload = futures["courses"].result()

    seen_course_lines = {normalize_for_search(option.get("value")) for option in course_lines}
    merged_course_lines = list(course_lines)
    for option in course_payload.get("course_lines") or []:
        key = normalize_for_search(option.get("value"))
        if not key or key in seen_course_lines:
            continue
        seen_course_lines.add(key)
        merged_course_lines.append(option)

    print(
        f"✅ Tải nhanh filter Request Teacher trong {time.perf_counter() - started_at:.1f}s "
        f"({len(centres)} cơ sở, {len(course_payload.get('courses') or [])} course, "
        f"{len(merged_course_lines)} course line).",
        flush=True,
    )
    return {
        "centres": centres,
        "course_lines": sorted(merged_course_lines, key=option_sort_key),
        "courses": course_payload.get("courses") or [],
    }


def fetch_request_class_fast_options(
    courses=None,
    centres=None,
    course_lines=None,
    text_search="",
    class_limit=DEFAULT_LIMIT,
    order_by="createdAt_desc",
    auto_login=False,
    force_refresh=False,
):
    validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    selected_courses = [str(value).strip() for value in (courses or []) if str(value).strip()]
    selected_centres = [str(value).strip() for value in (centres or []) if str(value).strip()]
    selected_course_lines = [str(value).strip() for value in (course_lines or []) if str(value).strip()]
    search_text = str(text_search or "").strip()
    if not selected_courses and len(search_text) < CLASS_SEARCH_MIN_CHARS:
        return {"classes": []}

    active_session = create_session()
    page_index = 0
    classes = []
    started_at = time.perf_counter()
    per_page = max(1, int(class_limit or DEFAULT_LIMIT))

    payload = {
        "operationName": "GetClasses",
        "query": GET_CLASSES_FILTER_QUERY,
        "variables": {
            "search": search_text,
            "centres": selected_centres,
            "courses": selected_courses,
            "courseLines": selected_course_lines,
            "pageIndex": page_index,
            "itemsPerPage": per_page,
            "orderBy": order_by,
        },
    }
    try:
        res_json = post_graphql_payload(
            payload,
            session=active_session,
            timeout=(10, 30),
            urls=(API_ROOT_URL, API_URL),
        )
    except requests.exceptions.RequestException as error:
        raise RuntimeError(f"Lỗi tải mã lớp từ LMS: {error}") from error

    if "errors" in res_json:
        if is_auth_error(res_json["errors"]):
            raise RuntimeError(TOKEN_HELP)
        raise RuntimeError(f"API lỗi tải mã lớp từ LMS: {res_json['errors']}")

    class_data = res_json.get("data", {}).get("classes", {})
    classes = class_data.get("data") or []

    class_options = build_class_filter_options_from_classes(classes).get("classes") or []
    print(
        f"✅ Tải {len(class_options)} mã lớp theo từ khóa/course "
        f"trong {time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return {"classes": class_options}


def fetch_classes_for_filter_options(
    start_date=DEFAULT_START_DATE,
    end_date=DEFAULT_END_DATE,
    center_ids=None,
    subject_codes=None,
    course_lines=None,
    courses=None,
    centres=None,
    text_search="",
    class_limit=DEFAULT_LIMIT,
    date_field=DEFAULT_DATE_FIELD,
    auto_login=False,
    force_refresh=False,
):
    date_field = normalize_date_field(date_field)
    validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    session = create_session()
    page_index = 0
    scanned_count = 0
    classes = []

    while True:
        class_payload = build_class_payload(
            page_index=page_index,
            limit=class_limit,
            start_date=start_date,
            end_date=end_date,
            center_ids=center_ids,
            text_search=text_search,
            date_field=date_field,
        )

        try:
            res = session.post(API_URL, headers=HEADERS, json=class_payload, timeout=(10, 60))
            res.raise_for_status()
            res_json = res.json()
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi tải danh sách lớp ở trang {page_index}: {error}") from error

        if "errors" in res_json:
            if is_auth_error(res_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi tải danh sách lớp trang {page_index}: {res_json['errors']}")

        class_data = res_json.get("data", {}).get("classes", {})
        class_items = class_data.get("data") or []
        pagination = class_data.get("pagination") or {}
        class_total = pagination.get("total") or 0

        if not class_items:
            break

        scanned_count += len(class_items)
        for item in class_items:
            if not course_matches_subjects(item, subject_codes):
                continue
            if not class_matches_extra_filters(item, course_lines=course_lines, courses=courses, centres=centres):
                continue
            classes.append(item)

        if scanned_count >= class_total or len(class_items) < class_limit:
            break

        page_index += 1
        time.sleep(0.1)

    deduped_class_items = []
    seen = set()
    for item in sorted(classes, key=lambda value: str(value.get("name") or "")):
        key = item.get("id")
        if key in seen:
            continue
        seen.add(key)
        deduped_class_items.append(item)

    return deduped_class_items


def fetch_class_filter_options(
    start_date=DEFAULT_START_DATE,
    end_date=DEFAULT_END_DATE,
    center_ids=None,
    subject_codes=None,
    course_lines=None,
    courses=None,
    centres=None,
    text_search="",
    class_limit=DEFAULT_LIMIT,
    date_field=DEFAULT_DATE_FIELD,
    auto_login=False,
    force_refresh=False,
):
    classes = fetch_classes_for_filter_options(
        start_date=start_date,
        end_date=end_date,
        center_ids=center_ids,
        subject_codes=subject_codes,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        text_search=text_search,
        class_limit=class_limit,
        date_field=date_field,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    return build_class_filter_options_from_classes(classes)


def scalar_filter_options(values):
    options = []
    seen = set()
    for value in values or []:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        options.append({
            "value": cleaned,
            "label": cleaned.replace("_", " ").title() if cleaned.isupper() else cleaned,
            "name": cleaned,
        })
    return sorted(options, key=option_sort_key)


def build_request_facets_from_requests(requests):
    types = []
    statuses = []
    satisfied = set()
    for item in requests or []:
        types.append(item.get("type"))
        statuses.append(item.get("status"))
        if item.get("isSatisfied") is True:
            satisfied.add("true")
        elif item.get("isSatisfied") is False:
            satisfied.add("false")
    return {
        "request_types": scalar_filter_options(types),
        "request_statuses": scalar_filter_options(statuses),
        "satisfaction": [
            {"value": "true", "label": "Đã đáp ứng", "name": "isSatisfied = true"},
            {"value": "false", "label": "Chưa đáp ứng", "name": "isSatisfied = false"},
        ] if satisfied else [],
    }


def fetch_request_facets_for_classes_bulk(
    classes,
    center_ids=None,
    text_search="",
    request_limit=DEFAULT_LIMIT,
):
    selected_class_ids = {
        str((class_item or {}).get("id") or "").strip()
        for class_item in (classes or [])
        if str((class_item or {}).get("id") or "").strip()
    }
    if not selected_class_ids:
        return build_request_facets_from_requests([])

    session = create_session()
    page_index = 0
    pages_scanned = 0
    scanned_count = 0
    matched_count = 0
    empty_pages_after_match = 0
    request_total = 0
    requests_found = []
    fallback_requests = []
    seen_request_ids = set()
    page_limit = max(int(request_limit or DEFAULT_LIMIT), DEFAULT_REQUEST_TEACHER_BULK_LIMIT)
    max_pages = max(0, int(REQUEST_TEACHER_FILTER_FACET_PAGES or 0))
    started_at = time.perf_counter()

    print(
        f"🔎 Facet request teacher: bulk page_limit={page_limit}, "
        f"max_pages={max_pages or 'không giới hạn'}, lớp mục tiêu={len(selected_class_ids)}.",
        flush=True,
    )

    while True:
        request_payload = build_request_teacher_payload(
            page_index=page_index,
            limit=page_limit,
            center_ids=center_ids,
            text_search=text_search,
        )
        try:
            req_res = session.post(API_URL, headers=HEADERS, json=request_payload, timeout=(10, 60))
            req_res.raise_for_status()
            req_json = req_res.json()
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi tải facet request teacher bulk trang {page_index}: {error}") from error

        if "errors" in req_json:
            if is_auth_error(req_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi tải facet request teacher bulk trang {page_index}: {req_json['errors']}")

        request_data = req_json.get("data", {}).get("findRequestTeacher", {})
        request_items = request_data.get("data") or []
        request_total = request_data.get("total") or 0
        if not request_items:
            break

        pages_scanned += 1
        scanned_count += len(request_items)
        page_match_count = 0
        fallback_requests.extend(request_items)

        for item in request_items:
            request_id = item.get("id")
            item_class = item.get("class") or {}
            item_class_id = str(item_class.get("id") or "").strip()
            if item_class_id not in selected_class_ids:
                continue
            if request_id in seen_request_ids:
                continue
            seen_request_ids.add(request_id)
            requests_found.append(item)
            matched_count += 1
            page_match_count += 1

        print(
            f"   Facet page {page_index}: quét {scanned_count}/{request_total or '?'} request, "
            f"match page {page_match_count}, match tổng {matched_count}.",
            flush=True,
        )

        if matched_count and page_match_count == 0:
            empty_pages_after_match += 1
        else:
            empty_pages_after_match = 0

        if max_pages and pages_scanned >= max_pages:
            print(
                f"   Dừng facet sau {pages_scanned} trang để giữ UI nhanh "
                f"(REQUEST_TEACHER_FILTER_FACET_PAGES={max_pages}).",
                flush=True,
            )
            break
        if REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES > 0 and empty_pages_after_match >= REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES:
            print(
                f"   Dừng facet sau {empty_pages_after_match} trang liên tiếp không có match mới.",
                flush=True,
            )
            break
        if scanned_count >= request_total or len(request_items) < page_limit:
            break

        page_index += 1
        time.sleep(0.02)

    facet_source = requests_found or fallback_requests
    if not requests_found and fallback_requests:
        print(
            "   Không thấy request khớp lớp trong phạm vi facet đã quét; "
            "dùng facet từ các request API gần nhất để không làm rỗng dropdown.",
            flush=True,
        )

    print(
        f"✅ Facet request teacher: {len(requests_found)} request khớp / "
        f"{scanned_count} request đã quét trong {time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return build_request_facets_from_requests(facet_source)


def fetch_request_teacher_filter_options(
    start_date=DEFAULT_START_DATE,
    end_date=DEFAULT_END_DATE,
    center_ids=None,
    subject_codes=None,
    course_lines=None,
    courses=None,
    centres=None,
    class_ids=None,
    text_search="",
    class_limit=DEFAULT_LIMIT,
    request_limit=DEFAULT_LIMIT,
    date_field=DEFAULT_DATE_FIELD,
    auto_login=False,
    force_refresh=False,
):
    started_at = time.perf_counter()
    class_limit = max(
        int(class_limit or DEFAULT_LIMIT),
        int(REQUEST_TEACHER_FILTER_CLASS_LIMIT or DEFAULT_LIMIT),
    )
    print(
        f"🔎 Tải bộ lọc Request Teacher: {start_date} → {end_date}, "
        f"date_field={normalize_date_field(date_field)}, class_limit={class_limit}.",
        flush=True,
    )
    class_started_at = time.perf_counter()
    classes = fetch_classes_for_filter_options(
        start_date=start_date,
        end_date=end_date,
        center_ids=center_ids,
        subject_codes=subject_codes,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        text_search=text_search,
        class_limit=class_limit,
        date_field=date_field,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    print(
        f"✅ Tải lớp cho filter: {len(classes)} lớp trong {time.perf_counter() - class_started_at:.1f}s.",
        flush=True,
    )
    if class_ids:
        selected_class_ids = {str(value).strip() for value in class_ids if str(value).strip()}
        classes = [item for item in classes if str(item.get("id") or "").strip() in selected_class_ids]

    class_options = build_class_filter_options_from_classes(classes)
    try:
        direct_centres = fetch_centre_filter_options(auto_login=False, force_refresh=False)
        if direct_centres:
            class_options["centres"] = direct_centres
    except Exception as error:
        print(f"⚠️ Không tải được centres API trực tiếp, dùng cơ sở từ class: {error}", flush=True)
    facet_started_at = time.perf_counter()
    class_options.update(fetch_request_facets_for_classes_bulk(
        classes,
        center_ids=center_ids,
        text_search=text_search,
        request_limit=request_limit,
    ))
    print(
        f"✅ Tải facet request cho filter trong {time.perf_counter() - facet_started_at:.1f}s.",
        flush=True,
    )
    print(
        f"✅ Hoàn tất bộ lọc Request Teacher trong {time.perf_counter() - started_at:.1f}s.",
        flush=True,
    )
    return class_options


def flatten_request_teacher(request_teacher):
    created_by = request_teacher.get("createdBy") or {}
    last_modified_by = request_teacher.get("lastModifiedBy") or {}
    class_info = request_teacher.get("class") or {}
    class_course = class_info.get("course") or {}
    center = request_teacher.get("center") or {}
    class_center = class_info.get("centre") or {}
    class_site = request_teacher.get("classSite") or {}
    request_class_site = request_teacher.get("requestTeacherClassSite") or {}
    session_start_times = session_start_time_ms_values(request_teacher)

    return {
        "program.group": class_program_group(class_info),
        "id": request_teacher.get("id"),
        "type": request_teacher.get("type"),
        "class.name": class_info.get("name"),
        "mã lớp basic": class_course.get("code"),
        "Course": course_display(class_info),
        "Course line": course_line_display(class_info),
        "class.studentCount": class_student_count(class_info),
        "class.startDate.VN": format_datetime_vn(class_info.get("startDate")),
        "class.endDate.VN": format_datetime_vn(class_info.get("endDate")),
        "class.status": class_info.get("status"),
        "center.shortName": center.get("shortName"),
        "center.name": center.get("name"),
        "class.centre.shortName": class_center.get("shortName"),
        "class.centre.name": class_center.get("name"),
        "classSite.name": class_site.get("name"),
        "requestTeacherClassSite.name": request_class_site.get("name"),
        "sessions.startTime.min.VN": format_epoch_ms_vn(min(session_start_times) if session_start_times else None),
        "sessions.startTime.all.VN": format_epoch_ms_values_vn(session_start_times),
        "sessions.teachers": collect_teachers(request_teacher.get("sessions")),
        "status": request_teacher.get("status"),
        "isSatisfied": request_teacher.get("isSatisfied"),
        "exceptionalReason": request_teacher.get("exceptionalReason"),
        "createdBy.displayName": created_by.get("displayName"),
        "createdBy.username": created_by.get("username"),
        "createdBy.email": created_by.get("email"),
        "createdAt.VN": format_datetime_vn(request_teacher.get("createdAt")),
        "lastModifiedBy.displayName": last_modified_by.get("displayName"),
        "lastModifiedBy.username": last_modified_by.get("username"),
        "lastModifiedBy.email": last_modified_by.get("email"),
        "lastModifiedAt.VN": format_datetime_vn(request_teacher.get("lastModifiedAt")),
    }


def fetch_target_classes_by_date(
    start_date,
    end_date,
    center_ids=None,
    text_search="",
    subject_codes=None,
    course_lines=None,
    courses=None,
    centres=None,
    class_ids=None,
    date_field=DEFAULT_DATE_FIELD,
    class_limit=DEFAULT_LIMIT,
):
    start_ms, end_ms = vn_date_range_to_epoch_ms(start_date, end_date)
    date_field = normalize_date_field(date_field)
    session = create_session()
    class_page_index = 0
    scanned_class_count = 0
    target_classes = []
    field_label = DATE_FIELD_LABELS[date_field]

    while True:
        class_payload = build_class_payload(
            page_index=class_page_index,
            limit=class_limit,
            start_date=start_date,
            end_date=end_date,
            center_ids=center_ids,
            class_ids=class_ids,
            text_search=text_search,
            date_field=date_field,
        )

        try:
            res = session.post(API_URL, headers=HEADERS, json=class_payload, timeout=(10, 60))
            res.raise_for_status()
            res_json = res.json()
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi lấy class ở trang {class_page_index}: {error}") from error

        if "errors" in res_json:
            if is_auth_error(res_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi lấy class trang {class_page_index}: {res_json['errors']}")

        class_data = res_json.get("data", {}).get("classes", {})
        class_items = class_data.get("data") or []
        pagination = class_data.get("pagination") or {}
        class_total = pagination.get("total") or 0

        if not class_items:
            break

        scanned_class_count += len(class_items)
        page_target_count = 0
        for class_item in class_items:
            class_date_value_ms = class_date_ms(class_item, date_field)
            if class_date_value_ms is None or not (start_ms <= class_date_value_ms <= end_ms):
                continue
            if not course_matches_subjects(class_item, subject_codes):
                continue
            if not class_matches_extra_filters(class_item, course_lines=course_lines, courses=courses, centres=centres):
                continue
            target_classes.append(class_item)
            page_target_count += 1

        print(
            f"Trang class {class_page_index}: quét {scanned_class_count}/{class_total or '?'} class, "
            f"chọn {len(target_classes)} class theo {field_label}.",
            flush=True,
        )

        if scanned_class_count >= class_total or len(class_items) < class_limit:
            break

        class_page_index += 1

    deduped = []
    seen = set()
    for item in target_classes:
        key = item.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def fetch_request_teachers_for_class(
    class_item,
    center_ids=None,
    request_types=None,
    statuses=None,
    is_satisfied=None,
    limit=DEFAULT_LIMIT,
):
    session = create_session()
    request_page_index = 0
    class_request_count = 0
    matched_items = []

    while True:
        request_payload = build_request_teacher_payload(
            page_index=request_page_index,
            limit=limit,
            center_ids=center_ids,
            request_types=request_types,
            statuses=statuses,
            is_satisfied=is_satisfied,
            text_search=class_item.get("name") or "",
        )

        try:
            req_res = session.post(API_URL, headers=HEADERS, json=request_payload, timeout=(10, 60))
            req_res.raise_for_status()
            req_json = req_res.json()
        except requests.exceptions.RequestException as error:
            raise RuntimeError(
                f"Lỗi request teacher cho class '{class_item.get('name')}' trang {request_page_index}: {error}"
            ) from error

        if "errors" in req_json:
            if is_auth_error(req_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(
                f"API lỗi request teacher cho class '{class_item.get('name')}' "
                f"trang {request_page_index}: {req_json['errors']}"
            )

        request_data = req_json.get("data", {}).get("findRequestTeacher", {})
        request_items = request_data.get("data") or []
        request_total = request_data.get("total") or 0

        if not request_items:
            break

        class_request_count += len(request_items)
        for item in request_items:
            item_class = item.get("class") or {}
            if item_class.get("id") == class_item.get("id"):
                matched_items.append(item)

        if class_request_count >= request_total or len(request_items) < limit:
            break

        request_page_index += 1

    return class_item, class_request_count, matched_items


def iter_request_teachers_by_date(
    start_date,
    end_date,
    center_ids=None,
    request_types=None,
    statuses=None,
    is_satisfied=None,
    text_search="",
    subject_codes=None,
    course_lines=None,
    courses=None,
    centres=None,
    class_ids=None,
    date_field=DEFAULT_DATE_FIELD,
    limit=DEFAULT_LIMIT,
    class_limit=DEFAULT_LIMIT,
    debug=False,
):
    start_ms, end_ms = vn_date_range_to_epoch_ms(start_date, end_date)
    date_field = normalize_date_field(date_field)
    selected_class_ids = {str(value).strip() for value in (class_ids or []) if str(value).strip()}
    scanned_request_count = 0
    matched_count = 0
    seen_request_ids = set()
    page_index = 0
    page_limit = max(int(limit or DEFAULT_LIMIT), DEFAULT_REQUEST_TEACHER_BULK_LIMIT)
    empty_pages_after_match = 0
    session = create_session()

    field_label = DATE_FIELD_LABELS[date_field]
    print(f"Khoảng {field_label} VN: {parse_vn_date(start_date)} -> {parse_vn_date(end_date)}", flush=True)
    print(f"Kéo request teacher theo bulk page {page_limit} record rồi lọc local theo {field_label}.", flush=True)

    while True:
        request_payload = build_request_teacher_payload(
            page_index=page_index,
            limit=page_limit,
            center_ids=center_ids,
            request_types=request_types,
            statuses=statuses,
            is_satisfied=is_satisfied,
            text_search=text_search,
        )

        try:
            req_res = session.post(API_URL, headers=HEADERS, json=request_payload, timeout=(10, 90))
            req_res.raise_for_status()
            req_json = req_res.json()
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi request teacher bulk trang {page_index}: {error}") from error

        if "errors" in req_json:
            if is_auth_error(req_json["errors"]):
                raise RuntimeError(TOKEN_HELP)
            raise RuntimeError(f"API lỗi request teacher bulk trang {page_index}: {req_json['errors']}")

        request_data = req_json.get("data", {}).get("findRequestTeacher", {})
        request_items = request_data.get("data") or []
        request_total = request_data.get("total") or 0

        if not request_items:
            break

        scanned_request_count += len(request_items)
        page_match_count = 0
        for item in request_items:
            request_id = item.get("id")
            item_class = item.get("class") or {}
            class_id = str(item_class.get("id") or "").strip()
            class_date_value_ms = class_date_ms(item_class, date_field)

            if not class_id or (selected_class_ids and class_id not in selected_class_ids):
                continue
            if class_date_value_ms is None or not (start_ms <= class_date_value_ms <= end_ms):
                continue
            if not course_matches_subjects(item_class, subject_codes):
                continue
            if not class_matches_extra_filters(item_class, course_lines=course_lines, courses=courses, centres=centres):
                continue
            if request_id in seen_request_ids:
                continue

            seen_request_ids.add(request_id)
            matched_count += 1
            page_match_count += 1
            yield item

        print(
            f"Request teacher bulk page {page_index}: quét {scanned_request_count}/{request_total or '?'} request, "
            f"match page {page_match_count}, match tổng {matched_count}.",
            flush=True,
        )

        if matched_count and page_match_count == 0:
            empty_pages_after_match += 1
        else:
            empty_pages_after_match = 0

        if REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES > 0 and empty_pages_after_match >= REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES:
            print(
                f"Dừng sớm sau {empty_pages_after_match} page liên tiếp không có match. "
                "Đặt REQUEST_TEACHER_STOP_AFTER_EMPTY_PAGES=0 nếu cần quét hết toàn bộ lịch sử.",
                flush=True,
            )
            break

        if scanned_request_count >= request_total or len(request_items) < page_limit:
            break

        page_index += 1


def export_request_teachers_by_date(
    start_date=DEFAULT_START_DATE,
    end_date=DEFAULT_END_DATE,
    output_file=None,
    center_ids=None,
    request_types=None,
    statuses=None,
    is_satisfied=None,
    text_search="",
    subject_codes=None,
    course_lines=None,
    courses=None,
    centres=None,
    class_ids=None,
    date_field=DEFAULT_DATE_FIELD,
    limit=DEFAULT_LIMIT,
    class_limit=DEFAULT_LIMIT,
    debug=False,
    auto_login=False,
    force_refresh=False,
):
    date_field = normalize_date_field(date_field)
    output_file = resolve_output_path(output_file) if output_file else build_output_file(start_date, end_date, date_field)
    request_count = 0
    row_count = 0

    validate_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    request_teachers = list(iter_request_teachers_by_date(
        start_date=start_date,
        end_date=end_date,
        center_ids=center_ids,
        request_types=request_types,
        statuses=statuses,
        is_satisfied=is_satisfied,
        text_search=text_search,
        subject_codes=subject_codes,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        class_ids=class_ids,
        date_field=date_field,
        limit=limit,
        class_limit=class_limit,
        debug=debug,
    ))
    def request_teacher_sort_key(item):
        class_info = item.get("class") or {}
        group = class_program_group(class_info)
        start_ms = class_start_date_ms(class_info)
        return (
            PROGRAM_GROUP_ORDER.get(group, len(PROGRAM_GROUP_ORDER)),
            start_ms is None,
            start_ms or 0,
            str((class_info.get("name") or "")),
            str(item.get("createdAt") or ""),
        )

    request_teachers.sort(
        key=request_teacher_sort_key
    )
    request_count = len(request_teachers)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for request_teacher in request_teachers:
            writer.writerow(flatten_request_teacher(request_teacher))
            row_count += 1

    print(f"Đã lưu {row_count} dòng từ {request_count} request teacher vào '{output_file}'", flush=True)
    return output_file


def parse_bool_filter(value):
    if value is None or value == "all":
        return None
    return value == "true"


def parse_args():
    parser = argparse.ArgumentParser(description="Export Request Teacher theo startDate hoặc endDate.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="Lọc từ ngày này. YYYY-MM-DD hoặc DD/MM/YYYY")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE, help="Lọc đến ngày này. YYYY-MM-DD hoặc DD/MM/YYYY")
    parser.add_argument("--date-field", choices=["startDate", "endDate"], default=DEFAULT_DATE_FIELD, help="Trường ngày của class dùng để lọc")
    parser.add_argument("--output", default=None, help="Tên file CSV output")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Số request mỗi page khi tìm request teacher theo class")
    parser.add_argument("--class-limit", type=int, default=DEFAULT_LIMIT, help="Số class mỗi page")
    parser.add_argument("--center-id", action="append", dest="center_ids", default=None)
    parser.add_argument("--class-id", action="append", dest="class_ids", default=None, help="Lọc theo class id từ LMS")
    parser.add_argument("--type", action="append", dest="request_types", default=None)
    parser.add_argument("--status", action="append", dest="statuses", default=None)
    parser.add_argument("--text-search", default="")
    parser.add_argument("--subject-code", action="append", dest="subject_codes", default=None, help="Lọc bộ môn theo course code/shortName, ví dụ PTB")
    parser.add_argument("--course-line", action="append", dest="course_lines", default=None, help="Lọc course line/khối theo dữ liệu class LMS")
    parser.add_argument("--course", action="append", dest="courses", default=None, help="Lọc course theo id/code/shortName/tên từ LMS")
    parser.add_argument("--centre", "--center", action="append", dest="centres", default=None, help="Lọc cơ sở theo id/shortName/tên từ class LMS")
    parser.add_argument("--is-satisfied", choices=["true", "false", "all"], default="all")
    parser.add_argument("--debug", action="store_true", help="In thêm khoảng sessions.startTime.min theo từng page")
    parser.add_argument("--login", action="store_true", help="Mở web LMS để đăng nhập/lấy token nếu cache chưa có")
    parser.add_argument("--force-refresh", action="store_true", help="Bỏ qua id token hiện tại và refresh/lấy token mới")
    return parser.parse_args()


def main():
    args = parse_args()
    is_satisfied = (
        parse_bool_filter(args.is_satisfied)
        if args.is_satisfied != "all"
        else DEFAULT_IS_SATISFIED
    )

    try:
        export_request_teachers_by_date(
            start_date=args.start_date,
            end_date=args.end_date,
            output_file=args.output,
            center_ids=args.center_ids or DEFAULT_CENTER_IDS,
            class_ids=args.class_ids,
            request_types=args.request_types or DEFAULT_TYPES,
            statuses=args.statuses or DEFAULT_STATUSES,
            is_satisfied=is_satisfied,
            text_search=args.text_search,
            subject_codes=args.subject_codes or DEFAULT_SUBJECT_CODES,
            course_lines=args.course_lines,
            courses=args.courses,
            centres=args.centres,
            date_field=args.date_field,
            limit=args.limit,
            class_limit=args.class_limit,
            debug=args.debug,
            auto_login=args.login,
            force_refresh=args.force_refresh,
        )
    except RuntimeError as error:
        print(f"❌ {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
