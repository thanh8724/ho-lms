"""Survey export helpers for MindX PullData.

This module is intentionally self-contained because the desktop app imports it
directly from ``controllers.py`` and ``ui/main_window.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter, Retry

from lms_auth import build_auth_headers, ensure_auth_token, summarize_graphql_errors


CENTRE_IDS: list[str] = []
QUESTION_IDS = ["676a887afe6e69ed05003d88", "676a84b4fe6e69ed05003d84"]
SURVEY_IDS = ["676a84b4fe6e69ed05003d81"]
DEFAULT_ITEMS_PER_PAGE = 1000
MAX_SURVEY_TICKET_PAGES = 100
DEFAULT_SUBMITTED_FROM = "2025-01-01"
LAST_FETCH_DIAGNOSTICS: dict[str, object] = {}

API_URL = "https://lms-api.mindx.edu.vn/graphql"
API_ROOT_URL = "https://lms-api.mindx.edu.vn/"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC_TZ = ZoneInfo("UTC")
AUTH_TOKEN = ""
HEADERS = {
    "Authorization": AUTH_TOKEN,
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://lms.mindx.edu.vn",
    "Referer": "https://lms.mindx.edu.vn/",
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

BASE_COLUMNS = [
    "ticket_id",
    "classId",
    "className",
    "studentName",
    "studentId",
    "Ngày đánh giá",
    "Ngày buổi học",
    "Thời gian buổi học",
    "Buổi số",
    "centre_shortName",
]

FIND_TICKET_PAGINATE_QUERY = """
query FindTicketPaginate($payload: TicketQuery) {
  findTicketPaginate(payload: $payload) {
    data {
      id
      ticketCode
      title
      status
      feedbackTopic
      createdAt
      closedDate
      ticketSource {
        id
        channel
        classId
        studentName
        studentId
        className
        centreId
        surveyId
        answers { questionId value }
        centre { id shortName name }
      }
    }
    pagination { type total }
  }
}
"""

FIND_SURVEY_RESPONSES_QUERY = """
query FindSurveyResponses($payload: SurveyResponseQueryInput!) {
  findSurveyResponses(payload: $payload) {
    data {
      id
      appName
      surveyId
      submittedAt
      userId
      metadata
      answers { questionId value }
    }
  }
}
"""

CLASS_SESSION_DETAILS_QUERY = """
query SurveyClassSessionDetails($classIds: [String], $itemsPerPage: Int!) {
  classes(payload: {id_in: $classIds, pageIndex: 0, itemsPerPage: $itemsPerPage}) {
    data {
      id
      name
      centre { id shortName name }
      course { id code shortName name courseLine { id name } }
      slots { _id startTime endTime date index sessionHour }
    }
  }
}
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


session = create_session()


def configure_auth(auto_login=False, force_refresh=False):
    global AUTH_TOKEN, HEADERS
    AUTH_TOKEN = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    HEADERS = build_auth_headers(AUTH_TOKEN)
    return AUTH_TOKEN


def parse_csv_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            items.extend(parse_csv_values(item))
        return items
    return [
        item.strip()
        for item in str(value or "").replace("\n", ",").split(",")
        if item.strip()
    ]


def parse_session_numbers(value):
    numbers = []
    for item in parse_csv_values(value):
        try:
            parsed = int(item)
        except ValueError as exc:
            raise ValueError(f"Buổi học phải là số nguyên: {item}") from exc
        if parsed > 0:
            numbers.append(parsed)
    return tuple(sorted(set(numbers)))


def normalize_text(value) -> str:
    return str(value or "").strip()


def normalize_for_search(value) -> str:
    normalized = unicodedata.normalize("NFD", normalize_text(value).lower())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return normalized.replace("đ", "d")


def parse_api_datetime(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if text.isdigit():
            timestamp = int(text)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=UTC_TZ)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC_TZ)
        return parsed
    except (OverflowError, ValueError):
        return None


def format_vn_date(value):
    parsed = parse_api_datetime(value)
    return parsed.astimezone(VN_TZ).strftime("%Y-%m-%d") if parsed else ""


def format_vn_datetime(value):
    parsed = parse_api_datetime(value)
    return parsed.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


def format_vn_time(value):
    parsed = parse_api_datetime(value)
    return parsed.astimezone(VN_TZ).strftime("%H:%M") if parsed else ""


def format_vn_time_range(start_value, end_value):
    start = format_vn_time(start_value)
    end = format_vn_time(end_value)
    if start and end:
        return f"{start} - {end}"
    return start or end


def parse_date_bound(value, end_of_day=False):
    cleaned = normalize_text(value)
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            day = datetime.strptime(cleaned, fmt).date()
            bound_time = dt_time.max if end_of_day else dt_time.min
            return datetime.combine(day, bound_time).replace(tzinfo=VN_TZ)
        except ValueError:
            continue
    parsed = parse_api_datetime(cleaned)
    return parsed.astimezone(VN_TZ) if parsed else None


def is_submitted_in_range(value, submitted_from=None, submitted_to=None):
    parsed = parse_api_datetime(value)
    if not parsed:
        return True
    parsed_vn = parsed.astimezone(VN_TZ)
    return (submitted_from is None or parsed_vn >= submitted_from) and (
        submitted_to is None or parsed_vn <= submitted_to
    )


def submitted_sort_value(value):
    parsed = parse_api_datetime(value)
    return parsed.timestamp() if parsed else 0


def submitted_month_key(value):
    parsed = parse_api_datetime(value)
    return parsed.astimezone(VN_TZ).strftime("%Y-%m") if parsed else ""


def _counter_preview(counter, limit=8):
    return ", ".join(f"{key}: {count}" for key, count in counter.most_common(limit) if key)


LESSON_MISSING_REASON_LABELS = {
    "missing_classId": "thiếu classId",
    "class_not_found": "không tìm thấy lớp trong LMS",
    "missing_sessionId": "thiếu sessionId",
    "class_has_no_slots": "lớp không có slots",
    "sessionId_not_in_class_slots": "sessionId không nằm trong slots hiện tại",
    "slot_missing_start_time": "slot thiếu startTime/date",
    "unknown": "không rõ",
}


def lesson_missing_reason_label(reason):
    return LESSON_MISSING_REASON_LABELS.get(normalize_text(reason), normalize_text(reason) or "không rõ")


def describe_last_fetch_diagnostics() -> str:
    diagnostics = LAST_FETCH_DIAGNOSTICS or {}
    if not diagnostics:
        return ""

    lines = [
        (
            f"API tải {diagnostics.get('scanned_count', 0)} response/"
            f"{diagnostics.get('api_total') or '?'}; "
            f"{diagnostics.get('survey_match_count', 0)} response đúng surveyId; "
            f"{diagnostics.get('date_match_count', 0)} nằm trong khoảng ngày; "
            f"{diagnostics.get('survey_date_match_count', 0)} đúng surveyId + khoảng ngày; "
            f"{diagnostics.get('question_match_count', 0)} có câu hỏi cần xuất; "
            f"{diagnostics.get('post_filter_count', 0)} còn lại sau bộ lọc UI."
        )
    ]
    month_summary = diagnostics.get("survey_month_summary") or diagnostics.get("month_summary")
    if month_summary:
        lines.append(f"Tháng có dữ liệu survey API trả về: {month_summary}.")
    lesson_missing_count = diagnostics.get("lesson_missing_count") or 0
    lesson_missing_summary = diagnostics.get("lesson_missing_reason_summary")
    if lesson_missing_count:
        detail = f" ({lesson_missing_summary})" if lesson_missing_summary else ""
        lines.append(f"{lesson_missing_count} row thiếu Ngày/Thời gian buổi học{detail}.")
    selected_range = diagnostics.get("selected_range")
    if selected_range:
        lines.append(f"Khoảng ngày đang chọn: {selected_range}.")
    return "\n".join(lines)


def parse_metadata(value):
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def normalize_metadata_filter(value):
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return normalize_text(value)


def build_metadata_filter(class_id, session_id):
    return normalize_metadata_filter({"classId": normalize_text(class_id), "sessionId": normalize_text(session_id)})


def parse_class_session_filter(value):
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    if ":" not in cleaned:
        raise ValueError("Class/session filter phải có dạng classId:sessionId.")
    class_id, session_id = cleaned.split(":", 1)
    return build_metadata_filter(class_id, session_id)


def build_ticket_payload(page_index, items_per_page, centre_ids=None, statuses=None, feedback_topics=None):
    payload = {
        "pageIndex": page_index,
        "itemsPerPage": max(1, min(int(items_per_page or DEFAULT_ITEMS_PER_PAGE), 100)),
    }
    if centre_ids:
        payload["centreId_in"] = list(centre_ids)
    if statuses:
        payload["status_in"] = list(statuses)
    if feedback_topics:
        payload["feedbackTopic_in"] = list(feedback_topics)
    return {
        "operationName": "FindTicketPaginate",
        "query": FIND_TICKET_PAGINATE_QUERY,
        "variables": {"payload": payload},
    }


def request_ticket_page(page_index, items_per_page, centre_ids=None, statuses=None, feedback_topics=None):
    payload = build_ticket_payload(page_index, items_per_page, centre_ids, statuses, feedback_topics)
    data = post_graphql_payload(payload, timeout=(10, 60))
    if data.get("errors"):
        raise RuntimeError(f"API lỗi survey page {page_index}: {summarize_graphql_errors(data['errors'])}")
    page = data.get("data", {}).get("findTicketPaginate", {}) or {}
    return page.get("data") or [], int((page.get("pagination") or {}).get("total") or 0)


def post_graphql_payload(payload, timeout=(10, 60), urls=None):
    last_error = None
    for url in (urls or (API_URL, API_ROOT_URL)):
        try:
            response = session.post(url, headers=HEADERS, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except ValueError as error:
            last_error = error
        except requests.exceptions.RequestException as error:
            last_error = error
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code not in {404, 405}:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("Không thể gửi request GraphQL.")


def build_survey_response_payload(page, items_per_page, survey_id, metadata=None):
    filter_payload = {"surveyId": normalize_text(survey_id)}
    metadata = normalize_text(metadata)
    if metadata:
        filter_payload["metadata"] = metadata
    return {
        "operationName": "FindSurveyResponses",
        "query": FIND_SURVEY_RESPONSES_QUERY,
        "variables": {
            "payload": {
                "pagination": {
                    "page": max(1, int(page or 1)),
                    "limit": max(1, int(items_per_page or DEFAULT_ITEMS_PER_PAGE)),
                },
                "filter": filter_payload,
            }
        },
    }


def request_survey_response_page(page, items_per_page, survey_id, metadata=None):
    payload = build_survey_response_payload(page, items_per_page, survey_id, metadata)
    data = post_graphql_payload(payload, timeout=(10, 90), urls=(API_ROOT_URL, API_URL))
    if data.get("errors"):
        raise RuntimeError(f"API lỗi survey response page {page}: {summarize_graphql_errors(data['errors'])}")
    result = data.get("data", {}).get("findSurveyResponses", {}) or {}
    return result.get("data") or []


def chunked(items, size):
    items = list(items or [])
    for index in range(0, len(items), max(1, int(size or 1))):
        yield items[index:index + size]


def fetch_class_session_details(class_ids):
    selected_ids = [normalize_text(value) for value in class_ids or [] if normalize_text(value)]
    if not selected_ids:
        return {}
    details = {}
    for batch in chunked(dict.fromkeys(selected_ids), 40):
        payload = {
            "operationName": "SurveyClassSessionDetails",
            "query": CLASS_SESSION_DETAILS_QUERY,
            "variables": {"classIds": batch, "itemsPerPage": len(batch)},
        }
        data = post_graphql_payload(payload, timeout=(10, 90), urls=(API_ROOT_URL, API_URL))
        if data.get("errors"):
            raise RuntimeError(f"API lỗi tải thông tin lớp survey: {summarize_graphql_errors(data['errors'])}")
        for item in data.get("data", {}).get("classes", {}).get("data") or []:
            class_id = normalize_text(item.get("id"))
            if class_id:
                details[class_id] = item
        time.sleep(0.03)
    return details


def infer_course_line_from_texts(*values):
    text = " ".join(normalize_text(value).upper() for value in values if normalize_text(value))
    compact = re.sub(r"[^A-Z0-9]", "", text)
    for line in ("C4K", "ROB", "XART", "PTB", "PREB", "DAFB", "VTB", "GAB", "CMB", "AMVCO", "AM-VCO"):
        compact_line = re.sub(r"[^A-Z0-9]", "", line)
        if line in text or compact_line in compact:
            return line
    return ""


def normalized_candidate_matches_selection(candidates, selected_values, *, allow_contains=False):
    if not selected_values:
        return True
    normalized_candidates = [
        normalize_for_search(value)
        for value in candidates or []
        if normalize_text(value)
    ]
    if not normalized_candidates:
        return False
    for candidate in normalized_candidates:
        if candidate in selected_values:
            return True
        if allow_contains and any(selected and selected in candidate for selected in selected_values):
            return True
    return False


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


def _answer_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def infer_centre_short_name_from_class_name(class_name):
    cleaned = normalize_text(class_name)
    if "-" not in cleaned:
        return ""
    return cleaned.split("-", 1)[0].strip()


def course_display_from_class_info(class_info):
    course = (class_info or {}).get("course") or {}
    return (
        normalize_text(course.get("shortName"))
        or normalize_text(course.get("code"))
        or normalize_text(course.get("name"))
    )


def course_line_display_from_class_info(class_info):
    course = (class_info or {}).get("course") or {}
    line = course.get("courseLine") or {}
    return normalize_text(line.get("name")) or infer_course_line_from_texts(course_display_from_class_info(class_info))


def build_survey_response_record(response_item, question_ids):
    metadata = parse_metadata(response_item.get("metadata"))
    answers = response_item.get("answers") or []
    question_set = set(question_ids)
    answer_map = {
        answer.get("questionId"): _answer_value(answer.get("value"))
        for answer in answers
        if answer.get("questionId") in question_set
    }
    if not answer_map:
        return None

    class_name = normalize_text(metadata.get("className"))
    submitted_at = response_item.get("submittedAt")
    record = {
        "ticket_id": response_item.get("id"),
        "classId": metadata.get("classId"),
        "className": class_name,
        "studentName": metadata.get("studentName"),
        "studentId": metadata.get("studentId") or response_item.get("userId"),
        "centreId": metadata.get("centreId"),
        "centre_shortName": (
            metadata.get("centre_shortName")
            or metadata.get("centreShortName")
            or infer_centre_short_name_from_class_name(class_name)
        ),
        "surveyId": response_item.get("surveyId"),
        "createdAt": format_vn_datetime(submitted_at),
        "closedDate": "",
        "Ngày đánh giá": format_vn_date(submitted_at),
        "Ngày buổi học": "",
        "Thời gian buổi học": "",
        "Buổi số": metadata.get("sessionNumber") or "",
        "_created_at": submitted_at,
        "_class_id": metadata.get("classId"),
        "_session_id": metadata.get("sessionId"),
        "_centre_name": metadata.get("centreName") or "",
        "_course": metadata.get("course") or infer_course_line_from_texts(class_name),
        "_course_line": metadata.get("courseLine") or infer_course_line_from_texts(class_name),
    }
    for question_id in question_ids:
        record[question_id] = answer_map.get(question_id)
    return record


def enrich_survey_records(records):
    class_ids = {
        normalize_text(record.get("_class_id") or record.get("classId"))
        for record in records or []
        if normalize_text(record.get("_class_id") or record.get("classId"))
    }
    class_details = fetch_class_session_details(class_ids)
    for record in records or []:
        class_id = normalize_text(record.get("_class_id") or record.get("classId"))
        class_info = class_details.get(class_id) or {}
        record["_lesson_missing_reason"] = ""
        if not class_info:
            record["_lesson_missing_reason"] = "missing_classId" if not class_id else "class_not_found"
            continue
        record["className"] = record.get("className") or class_info.get("name") or ""
        centre = class_info.get("centre") or {}
        if centre:
            record["centreId"] = centre.get("id") or record.get("centreId") or ""
            record["centre_shortName"] = centre.get("shortName") or record.get("centre_shortName") or ""
            record["_centre_name"] = centre.get("name") or record.get("_centre_name") or ""
        course = course_display_from_class_info(class_info)
        course_line = course_line_display_from_class_info(class_info)
        if course:
            record["_course"] = course
        if course_line:
            record["_course_line"] = course_line
        session_id = normalize_text(record.get("_session_id"))
        if not session_id:
            record["_lesson_missing_reason"] = "missing_sessionId"
            continue
        slots = class_info.get("slots") or []
        slot = next(
            (
                item
                for item in slots
                if normalize_text(item.get("_id")) == session_id
            ),
            None,
        )
        if not slot:
            record["_lesson_missing_reason"] = "class_has_no_slots" if not slots else "sessionId_not_in_class_slots"
            continue
        start_time = slot.get("startTime") or slot.get("date")
        if not start_time:
            record["_lesson_missing_reason"] = "slot_missing_start_time"
            continue
        record["Ngày buổi học"] = format_vn_date(start_time)
        record["Thời gian buổi học"] = format_vn_time_range(slot.get("startTime"), slot.get("endTime"))
        if isinstance(slot.get("index"), int):
            record["Buổi số"] = slot.get("index") + 1
    return records


def build_survey_record(ticket, question_ids):
    source = ticket.get("ticketSource") or {}
    answers = source.get("answers") or []
    question_set = set(question_ids)
    answer_map = {
        answer.get("questionId"): _answer_value(answer.get("value"))
        for answer in answers
        if answer.get("questionId") in question_set
    }
    if not answer_map:
        return None

    centre = source.get("centre") or {}
    class_name = source.get("className") or ""
    inferred_course = infer_course_line_from_texts(class_name)
    submitted_at = ticket.get("createdAt") or ticket.get("closedDate")
    record = {
        "ticket_id": ticket.get("id"),
        "ticketCode": ticket.get("ticketCode"),
        "ticket_status": ticket.get("status"),
        "classId": source.get("classId"),
        "className": class_name,
        "studentName": source.get("studentName"),
        "studentId": source.get("studentId"),
        "centreId": source.get("centreId") or centre.get("id"),
        "centre_shortName": centre.get("shortName") or source.get("centreId") or "",
        "surveyId": source.get("surveyId"),
        "createdAt": format_vn_datetime(ticket.get("createdAt")),
        "closedDate": format_vn_datetime(ticket.get("closedDate")),
        "Ngày đánh giá": format_vn_date(submitted_at),
        "Ngày buổi học": "",
        "Thời gian buổi học": "",
        "Buổi số": "",
        "_created_at": submitted_at,
        "_class_id": source.get("classId"),
        "_session_id": "",
        "_centre_name": centre.get("name") or centre.get("shortName") or "",
        "_course": inferred_course,
        "_course_line": inferred_course,
    }
    for question_id in question_ids:
        record[question_id] = answer_map.get(question_id)
    return record


def survey_record_matches_filters(
    record,
    class_ids=None,
    session_numbers=None,
    course_lines=None,
    courses=None,
    centres=None,
):
    selected_class_ids = {normalize_text(value) for value in (class_ids or []) if normalize_text(value)}
    selected_sessions = {int(value) for value in (session_numbers or []) if str(value).strip().isdigit()}
    selected_course_lines = {normalize_for_search(value) for value in (course_lines or []) if normalize_text(value)}
    selected_courses = {normalize_for_search(value) for value in (courses or []) if normalize_text(value)}
    selected_centres = {normalize_for_search(value) for value in (centres or []) if normalize_text(value)}

    if selected_class_ids and normalize_text(record.get("_class_id") or record.get("classId")) not in selected_class_ids:
        return False
    try:
        session_number = int(record.get("Buổi số") or 0)
    except (TypeError, ValueError):
        session_number = 0
    if selected_sessions and session_number not in selected_sessions:
        return False

    line_candidates = [record.get("_course_line"), infer_course_line_from_texts(record.get("className"))]
    course_candidates = [record.get("_course"), record.get("className")]
    centre_candidates = [record.get("centreId"), record.get("centre_shortName"), record.get("_centre_name")]
    if not normalized_candidate_matches_selection(line_candidates, selected_course_lines):
        return False
    if not normalized_candidate_matches_selection(course_candidates, selected_courses, allow_contains=True):
        return False
    if not normalized_candidate_matches_selection(centre_candidates, selected_centres):
        return False
    return True


def filter_survey_records(
    records,
    class_ids=None,
    session_numbers=None,
    course_lines=None,
    courses=None,
    centres=None,
):
    if not any((class_ids, session_numbers, course_lines, courses, centres)):
        return list(records or [])
    return [
        record
        for record in records or []
        if survey_record_matches_filters(
            record,
            class_ids=class_ids,
            session_numbers=session_numbers,
            course_lines=course_lines,
            courses=courses,
            centres=centres,
        )
    ]


def build_survey_filter_options(records):
    course_lines = []
    courses = []
    centres = []
    classes = []
    sessions = set()
    seen_course_lines = set()
    seen_courses = set()
    seen_centres = set()
    seen_classes = set()

    for record in records or []:
        line_value = record.get("_course_line") or infer_course_line_from_texts(record.get("className"))
        add_filter_option(course_lines, seen_course_lines, line_value, line_value)

        course_value = record.get("_course") or line_value
        add_filter_option(courses, seen_courses, course_value, course_value)

        centre_value = record.get("centreId") or record.get("centre_shortName")
        centre_label = record.get("centre_shortName") or record.get("_centre_name") or centre_value
        add_filter_option(centres, seen_centres, centre_value, centre_label, record.get("_centre_name"))

        class_id = normalize_text(record.get("_class_id") or record.get("classId"))
        class_name = normalize_text(record.get("className"))
        if class_id and class_name and class_id not in seen_classes:
            seen_classes.add(class_id)
            classes.append({
                "id": class_id,
                "name": class_name,
                "subject": line_value,
                "course": course_value,
                "centre": centre_label,
            })

        try:
            session_number = int(record.get("Buổi số") or 0)
        except (TypeError, ValueError):
            session_number = 0
        if session_number > 0:
            sessions.add(session_number)

    return {
        "course_lines": sorted(course_lines, key=option_sort_key),
        "courses": sorted(courses, key=option_sort_key),
        "centres": sorted(centres, key=option_sort_key),
        "classes": sorted(classes, key=lambda item: normalize_for_search(item["name"])),
        "sessions": tuple(sorted(sessions)),
    }


def fetch_all(
    question_ids=None,
    survey_ids=None,
    metadata_filters=None,
    centre_ids=None,
    centres=None,
    class_ids=None,
    session_numbers=None,
    course_lines=None,
    courses=None,
    statuses=None,
    feedback_topics=None,
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
    submitted_from=None,
    submitted_to=None,
    auto_login=False,
    force_refresh=False,
    enrich_classes=True,
):
    global LAST_FETCH_DIAGNOSTICS
    configure_auth(auto_login=auto_login, force_refresh=force_refresh)
    question_ids = list(question_ids or QUESTION_IDS)
    survey_ids = list(dict.fromkeys(parse_csv_values(survey_ids) or SURVEY_IDS))
    centre_ids = parse_csv_values(centre_ids)
    centres = parse_csv_values(centres)
    selected_centres = list(dict.fromkeys([*centres, *centre_ids]))
    statuses = parse_csv_values(statuses)
    feedback_topics = parse_csv_values(feedback_topics)
    submitted_start = parse_date_bound(submitted_from, end_of_day=False)
    submitted_end = parse_date_bound(submitted_to, end_of_day=True)
    if submitted_start and submitted_end and submitted_start > submitted_end:
        raise ValueError("Ngày bắt đầu không được sau ngày kết thúc.")

    records = []
    fetched_pages = 0
    fetched_rows = 0
    response_match_count = 0
    date_match_count = 0
    question_match_count = 0
    month_counts = Counter()
    page_cache = {}
    seen_response_ids = set()
    date_order = None
    previous_page_date = None
    limit = max(1, min(int(items_per_page or DEFAULT_ITEMS_PER_PAGE), 1000))
    started_at = time.perf_counter()
    print(
        f"🔎 Tải Survey responses: page_size={limit}, centres={len(selected_centres)}, "
        f"statuses={len(statuses)}, topics={len(feedback_topics)}.",
        flush=True,
    )

    def row_datetime(item):
        return parse_api_datetime((item or {}).get("submittedAt"))

    def fetch_page(survey_id, page, metadata=None):
        nonlocal fetched_pages, fetched_rows
        cache_key = (survey_id, normalize_text(metadata), int(page))
        if cache_key not in page_cache:
            rows = request_survey_response_page(page, limit, survey_id, metadata)
            page_cache[cache_key] = rows
            fetched_pages += 1
            fetched_rows += len(rows)
            time.sleep(0.03)
        return page_cache[cache_key]

    def process_rows(rows):
        nonlocal response_match_count, date_match_count, question_match_count
        page_added = 0
        for item in rows or []:
            response_id = normalize_text(item.get("id"))
            if response_id and response_id in seen_response_ids:
                continue
            if response_id:
                seen_response_ids.add(response_id)
            response_match_count += 1
            submitted_at = item.get("submittedAt")
            month_key = submitted_month_key(submitted_at)
            if month_key:
                month_counts[month_key] += 1
            if not is_submitted_in_range(submitted_at, submitted_start, submitted_end):
                continue
            date_match_count += 1
            record = build_survey_response_record(item, question_ids)
            if record:
                records.append(record)
                question_match_count += 1
                page_added += 1
        return page_added

    def page_date_stats(rows):
        nonlocal date_order, previous_page_date
        dates = [row_datetime(item) for item in rows or []]
        dates = [value for value in dates if value is not None]
        if not dates:
            return {}
        first_date = dates[0]
        last_date = dates[-1]
        if first_date > last_date:
            date_order = "desc"
        elif first_date < last_date:
            date_order = "asc"
        elif previous_page_date is not None and date_order is None:
            if first_date > previous_page_date:
                date_order = "asc"
            elif first_date < previous_page_date:
                date_order = "desc"
        previous_page_date = last_date
        return {
            "first": first_date,
            "last": last_date,
            "min": min(dates),
            "max": max(dates),
            "order": date_order or "unknown",
        }

    def date_range_action(stats):
        if not stats:
            return "process"
        page_is_newer_than_range = submitted_end is not None and stats["min"] > submitted_end
        page_is_older_than_range = submitted_start is not None and stats["max"] < submitted_start
        order = stats["order"]
        if page_is_newer_than_range:
            return "stop" if order == "asc" else "skip"
        if page_is_older_than_range:
            return "stop" if order == "desc" else "skip"
        return "process"

    def should_stop_after_processing(stats):
        if not stats:
            return False
        if stats["order"] == "desc" and submitted_start is not None and stats["min"] < submitted_start:
            return True
        if stats["order"] == "asc" and submitted_end is not None and stats["max"] > submitted_end:
            return True
        return False

    metadata_values = [
        normalize_metadata_filter(value)
        for value in (metadata_filters or [])
        if normalize_text(value)
    ]
    selected_survey_ids = list(survey_ids or SURVEY_IDS)

    for survey_id in selected_survey_ids:
        if metadata_values:
            for metadata in metadata_values:
                page = 1
                while page <= MAX_SURVEY_TICKET_PAGES:
                    rows = fetch_page(survey_id, page, metadata)
                    if not rows:
                        break
                    stats = page_date_stats(rows)
                    action = date_range_action(stats)
                    if action == "stop":
                        break
                    if action == "skip":
                        print(f"   Survey response page {page}: bỏ qua ngoài khoảng ngày, tổng {len(records)}.", flush=True)
                        if len(rows) < limit:
                            break
                        page += 1
                        continue
                    added = process_rows(rows)
                    print(f"   Survey response page {page}: thêm {added}, tổng {len(records)}.", flush=True)
                    if len(rows) < limit:
                        break
                    if should_stop_after_processing(stats):
                        break
                    page += 1
            continue

        page = 1
        while page <= MAX_SURVEY_TICKET_PAGES:
            rows = fetch_page(survey_id, page)
            if not rows:
                break
            stats = page_date_stats(rows)
            action = date_range_action(stats)
            if action == "stop":
                break
            if action == "skip":
                print(f"   Survey response page {page}: bỏ qua ngoài khoảng ngày, tổng {len(records)}.", flush=True)
                if len(rows) < limit:
                    break
                page += 1
                continue
            added = process_rows(rows)
            print(f"   Survey response page {page}: thêm {added}, tổng {len(records)}.", flush=True)
            if len(rows) < limit:
                break
            if should_stop_after_processing(stats):
                break
            page += 1

    if enrich_classes:
        enrich_survey_records(records)
    records.sort(key=lambda item: submitted_sort_value(item.get("_created_at")), reverse=True)
    pre_filter_count = len(records)
    records = filter_survey_records(
        records,
        class_ids=class_ids,
        session_numbers=session_numbers,
        course_lines=course_lines,
        courses=courses,
        centres=selected_centres,
    )
    lesson_missing_reasons = Counter(
        lesson_missing_reason_label(record.get("_lesson_missing_reason"))
        for record in records
        if not record.get("Ngày buổi học") or not record.get("Thời gian buổi học")
    )
    LAST_FETCH_DIAGNOSTICS = {
        "scanned_count": fetched_rows,
        "api_total": f"{fetched_pages} page",
        "survey_match_count": response_match_count,
        "date_match_count": date_match_count,
        "survey_date_match_count": date_match_count,
        "question_match_count": question_match_count,
        "pre_filter_count": pre_filter_count,
        "post_filter_count": len(records),
        "centre_filter_count": len(selected_centres),
        "lesson_missing_count": sum(lesson_missing_reasons.values()),
        "lesson_missing_reason_summary": _counter_preview(lesson_missing_reasons),
        "month_summary": _counter_preview(month_counts),
        "survey_month_summary": _counter_preview(month_counts),
        "selected_range": (
            f"{submitted_start.strftime('%Y-%m-%d') if submitted_start else 'không giới hạn'}"
            " - "
            f"{submitted_end.strftime('%Y-%m-%d') if submitted_end else 'không giới hạn'}"
        ),
    }
    print(f"✅ Hoàn tất Survey: {len(records)} record trong {time.perf_counter() - started_at:.1f}s.", flush=True)
    return records


def _clean_export_record(record):
    clean = dict(record)
    for key in (
        "_created_at",
        "_class_id",
        "_session_id",
        "_centre_name",
        "_course",
        "_course_line",
        "_lesson_missing_reason",
    ):
        clean.pop(key, None)
    return clean


def export_survey(
    question_ids=None,
    output_file="response_survey.csv",
    survey_ids=None,
    metadata_filters=None,
    centre_ids=None,
    centres=None,
    class_ids=None,
    session_numbers=None,
    course_lines=None,
    courses=None,
    statuses=None,
    feedback_topics=None,
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
    submitted_from=None,
    submitted_to=None,
    auto_login=False,
    force_refresh=False,
):
    question_ids = list(question_ids or QUESTION_IDS)
    records = fetch_all(
        question_ids=question_ids,
        survey_ids=survey_ids,
        metadata_filters=metadata_filters,
        centre_ids=centre_ids,
        centres=centres,
        class_ids=class_ids,
        session_numbers=session_numbers,
        course_lines=course_lines,
        courses=courses,
        statuses=statuses,
        feedback_topics=feedback_topics,
        items_per_page=items_per_page,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    if not records:
        return None

    output_path = Path(output_file or "response_survey.csv").expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = BASE_COLUMNS + [question_id for question_id in question_ids if question_id not in BASE_COLUMNS]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(_clean_export_record(record))
    print(f"📁 Đã lưu {len(records)} survey response vào '{output_path}'", flush=True)
    return str(output_path)


def fetch_survey_filter_options(
    question_ids=None,
    survey_ids=None,
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
    submitted_from=None,
    submitted_to=None,
    auto_login=False,
    force_refresh=False,
):
    records = fetch_all(
        question_ids=list(question_ids or QUESTION_IDS),
        survey_ids=list(survey_ids or SURVEY_IDS),
        items_per_page=items_per_page,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    return build_survey_filter_options(records)


def build_parser():
    parser = argparse.ArgumentParser(description="Export survey responses.")
    parser.add_argument("--question-id", action="append", dest="question_ids")
    parser.add_argument("--survey-id", action="append", dest="survey_ids")
    parser.add_argument("--metadata-filter", action="append", dest="metadata_filters")
    parser.add_argument("--class-session", action="append", dest="class_sessions")
    parser.add_argument("--centre-id", action="append", dest="centre_ids")
    parser.add_argument("--centre", action="append", dest="centres")
    parser.add_argument("--class-id", action="append", dest="class_ids")
    parser.add_argument("--session", dest="sessions")
    parser.add_argument("--course-line", action="append", dest="course_lines")
    parser.add_argument("--course", action="append", dest="courses")
    parser.add_argument("--status", action="append", dest="statuses")
    parser.add_argument("--feedback-topic", action="append", dest="feedback_topics")
    parser.add_argument("--items-per-page", type=int, default=DEFAULT_ITEMS_PER_PAGE)
    parser.add_argument("--submitted-from")
    parser.add_argument("--submitted-to")
    parser.add_argument("--output", default="response_survey.csv")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    metadata_filters = list(args.metadata_filters or [])
    metadata_filters.extend(parse_class_session_filter(value) for value in args.class_sessions or [])
    return export_survey(
        question_ids=parse_csv_values(args.question_ids) or QUESTION_IDS,
        output_file=args.output,
        survey_ids=parse_csv_values(args.survey_ids) or SURVEY_IDS,
        metadata_filters=metadata_filters,
        centre_ids=parse_csv_values(args.centre_ids) or CENTRE_IDS,
        centres=parse_csv_values(args.centres),
        class_ids=parse_csv_values(args.class_ids),
        session_numbers=parse_session_numbers(args.sessions),
        course_lines=parse_csv_values(args.course_lines),
        courses=parse_csv_values(args.courses),
        statuses=parse_csv_values(args.statuses),
        feedback_topics=parse_csv_values(args.feedback_topics),
        items_per_page=args.items_per_page,
        submitted_from=args.submitted_from,
        submitted_to=args.submitted_to,
        auto_login=args.login,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
