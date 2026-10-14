"""Export teacher attendance for LMS class sessions."""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter, Retry

from lms_auth import LMS_API_URL, LMS_GRAPHQL_URL, build_auth_headers, ensure_auth_token


API_URLS = (LMS_GRAPHQL_URL, f"{LMS_API_URL.rstrip('/')}/")
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC_TZ = ZoneInfo("UTC")

DEFAULT_START_DATE = date.today().replace(day=1).isoformat()
DEFAULT_OUTPUT_FILE = "teacher_attendance.csv"
DEFAULT_ITEMS_PER_PAGE = int(os.getenv("TEACHER_ATTENDANCE_CLASSES_PER_PAGE", "100"))
DEFAULT_TIMESHEET_WORKERS = int(os.getenv("TEACHER_ATTENDANCE_TIMESHEET_WORKERS", "4"))
GRAPHQL_RETRIES = max(0, int(os.getenv("TEACHER_ATTENDANCE_GRAPHQL_RETRIES", "3")))
GRAPHQL_RETRY_BACKOFF = max(
    0.0, float(os.getenv("TEACHER_ATTENDANCE_GRAPHQL_RETRY_BACKOFF", "1.0"))
)
DEFAULT_SESSION_NUMBERS = tuple(range(1, 15))
DEFAULT_CLASS_STATUSES = ("PENDING", "PRE_OPEN", "RUNNING", "OPEN", "FINISHED")

EXPORT_COLUMNS = [
    "Centre shortname",
    "Type",
    "Class name",
    "Class Site",
    "Course",
    "Course Line",
    "Buổi",
    "Teacher name",
    "Work email",
    "Personal email",
    "Username",
    "Class role/Office hour type",
    "Status",
    "Slot time",
    "Slot duration",
    "Effective duration",
    "Student count",
]

CHECKED_ATTENDANCE_DETAILS = {"ATTENDED", "LATE_ARRIVED", "ABSENT_WITH_NOTICE"}
LEGACY_CLASS_ROLE_ALIASES = {
    "main": ("Lecturer", "LEC"),
    "lecturer": ("Lecturer", "LEC"),
    "lecture": ("Lecturer", "LEC"),
    "lec": ("Lecturer", "LEC"),
    "support": ("Teacher Assisstant", "TA"),
    "assistant": ("Teacher Assisstant", "TA"),
    "teacher assistant": ("Teacher Assisstant", "TA"),
    "teacher assisstant": ("Teacher Assisstant", "TA"),
    "ta": ("Teacher Assisstant", "TA"),
    "supply": ("Supply teacher", "Supply"),
    "supply teacher": ("Supply teacher", "Supply"),
    "judge": ("Judge", "Judge"),
    "mentor": ("Mentor", "Mentor"),
    "super teacher 18+": ("Super Teacher 18+", "ST 18+"),
    "st 18+": ("Super Teacher 18+", "ST 18+"),
    "contact k18 hn": ("Contact K18 HN", "CXO k18"),
    "cxo k18": ("Contact K18 HN", "CXO k18"),
}

CLASS_FIELDS = """
  id
  name
  status
  centre { id name shortName }
  course {
    id
    code
    shortName
    name
    courseLine { id name }
  }
  teachers {
    teacher { id username fullName email personalEmail code }
    role { id name shortName }
    isActive
    classSiteId
  }
  classSites {
    _id
    name
    centre { id name shortName }
    teachers {
      teacher { id username fullName email personalEmail code }
      role { id name shortName }
      isActive
      classSiteId
    }
    classSiteSlots {
      classSlotId
      teachers {
        teacher { id username fullName email personalEmail code }
        role { id name shortName }
        isActive
        classSiteId
      }
    }
  }
  slots {
    _id
    index
    date
    startTime
    endTime
    sessionHour
    teachers {
      teacher { id username fullName email personalEmail code }
      role { id name shortName }
      isActive
      classSiteId
    }
    teacherAttendance {
      _id
      status
      classSiteId
      teacher { id username fullName email personalEmail code }
    }
    studentAttendance { _id }
  }
"""

GET_CLASSES_QUERY = f"""
query TeacherAttendanceClasses($payload: ClassQuery) {{
  classes(payload: $payload) {{
    data {{
      {CLASS_FIELDS}
    }}
    pagination {{ total }}
  }}
}}
"""

GET_CLASS_FILTER_QUERY = """
query TeacherAttendanceClassOptions($payload: ClassQuery) {
  classes(payload: $payload) {
    data {
      id
      name
      status
      centre { id name shortName }
      course {
        id
        code
        shortName
        name
        courseLine { id name }
      }
    }
    pagination { total }
  }
}
"""

GET_TEACHER_TIMESHEET_QUERY = """
query TeacherClassAttendanceTimesheet($payload: TimesheetItemQuery) {
  findTimesheetByTeacher(payload: $payload) {
    id
    type
    status
    classSessionAttendance {
      id
      startTime
      endTime
      sessionHour
      status
      class { id name }
    }
  }
}
"""


def normalize_text(value) -> str:
    return str(value or "").strip()


def normalize_for_search(value) -> str:
    normalized = unicodedata.normalize("NFD", normalize_text(value))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").lower()


def parse_csv_values(value, *, upper: bool = False) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            items.extend(parse_csv_values(item, upper=upper))
        return tuple(items)
    items = [item.strip() for item in re.split(r"[,\n]+", normalize_text(value)) if item.strip()]
    return tuple(item.upper() if upper else item for item in items)


def parse_session_numbers(value) -> tuple[int, ...]:
    if value is None or value == "":
        return DEFAULT_SESSION_NUMBERS
    numbers = []
    for item in parse_csv_values(value):
        try:
            number = int(item)
        except ValueError as exc:
            raise ValueError(f"Buổi học không hợp lệ: {item}") from exc
        if number <= 0:
            raise ValueError(f"Buổi học phải lớn hơn 0: {item}")
        if number not in numbers:
            numbers.append(number)
    return tuple(numbers)


def parse_date(value, field_name="ngày") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = normalize_text(value)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"{field_name} không hợp lệ: {text}")


def vn_date_range(start_date, end_date) -> tuple[datetime, datetime]:
    start = datetime.combine(parse_date(start_date, "ngày bắt đầu"), dt_time.min).replace(tzinfo=VN_TZ)
    end = datetime.combine(parse_date(end_date, "ngày kết thúc"), dt_time.max).replace(tzinfo=VN_TZ)
    if start > end:
        raise ValueError("Ngày bắt đầu không được sau ngày kết thúc.")
    return start, end


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(UTC_TZ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_api_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    text = normalize_text(value)
    try:
        if re.fullmatch(r"\d{10,13}", text):
            timestamp = int(text)
            if len(text) == 13:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC_TZ).astimezone(VN_TZ)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC_TZ)
        return parsed.astimezone(VN_TZ)
    except (OSError, TypeError, ValueError):
        return None


def create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=0.7,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def graphql_error_message(errors) -> str:
    messages = []
    for error in errors or []:
        if isinstance(error, dict):
            messages.append(normalize_text(error.get("message")) or str(error))
        else:
            messages.append(str(error))
    return " | ".join(messages[:5])


def is_transient_graphql_error(errors) -> bool:
    """Return whether the API error looks like a dropped backend connection."""
    message = graphql_error_message(errors).lower()
    transient_markers = (
        "connection closed",
        "connection reset",
        "socket hang up",
        "econnreset",
        "mongodb connection",
        "mongonetworkerror",
        "server selection timeout",
        "network error",
        "broken pipe",
    )
    return (
        any(marker in message for marker in transient_markers)
        or ("connection" in message and "closed" in message)
    )


def role_from_legacy_value(value) -> dict:
    raw_value = normalize_text(value)
    key = normalize_for_search(raw_value).replace("_", " ").replace("-", " ")
    key = re.sub(r"\s+", " ", key).strip()
    name, short_name = LEGACY_CLASS_ROLE_ALIASES.get(key, (raw_value, raw_value))
    return {"id": "", "name": name, "shortName": short_name}


def legacy_class_role_value(error) -> str:
    if not isinstance(error, dict):
        return ""
    message = normalize_text(error.get("message"))
    path = error.get("path") or []
    if (
        not isinstance(path, list)
        or not path
        or path[-1] != "role"
        or "classRoles" not in message
        or "Cast to ObjectId failed" not in message
    ):
        return ""
    match = re.search(r'value\s+"([^"]+)"', message)
    return match.group(1) if match else ""


def apply_legacy_class_role_errors(result: dict) -> tuple[dict, int]:
    data = result.get("data") or {}
    patched = 0
    for error in result.get("errors") or []:
        legacy_value = legacy_class_role_value(error)
        if not legacy_value:
            continue
        path = error.get("path") or []
        parent = data
        for key in path[:-1]:
            try:
                parent = parent[key]
            except (KeyError, IndexError, TypeError):
                parent = None
                break
        if isinstance(parent, dict):
            parent["role"] = role_from_legacy_value(legacy_value)
            patched += 1
    return result, patched


def is_legacy_class_role_error(error) -> bool:
    return bool(legacy_class_role_value(error))


def post_graphql(
    payload: dict,
    token: str,
    *,
    session=None,
    timeout=(10, 60),
    allow_legacy_role_errors=False,
) -> dict:
    active_session = session or create_session()
    last_error = None
    for url in API_URLS:
        for attempt in range(GRAPHQL_RETRIES + 1):
            try:
                response = active_session.post(
                    url,
                    headers=build_auth_headers(token),
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                result = response.json()
                if result.get("errors"):
                    if allow_legacy_role_errors and all(
                        is_legacy_class_role_error(error)
                        for error in result.get("errors") or []
                    ):
                        result, patched = apply_legacy_class_role_errors(result)
                        if patched < len(result.get("errors") or []):
                            raise RuntimeError(graphql_error_message(result["errors"]))
                        if patched:
                            print(
                                f"⚠️ Đã map {patched} role giáo viên legacy từ LMS.",
                                flush=True,
                            )
                        result.pop("errors", None)
                        return result
                    if is_transient_graphql_error(result["errors"]):
                        last_error = RuntimeError(graphql_error_message(result["errors"]))
                        if attempt < GRAPHQL_RETRIES:
                            delay = GRAPHQL_RETRY_BACKOFF * (2**attempt)
                            operation = payload.get("operationName") or "GraphQL"
                            print(
                                f"⚠️ {operation} bị đóng kết nối backend; "
                                f"thử lại {attempt + 1}/{GRAPHQL_RETRIES} sau {delay:g}s.",
                                flush=True,
                            )
                            time.sleep(delay)
                            continue
                    raise RuntimeError(graphql_error_message(result["errors"]))
                return result
            except requests.RequestException as exc:
                last_error = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code in {404, 405}:
                    break
                raise
    raise RuntimeError(f"Không gọi được LMS GraphQL: {last_error}")


def build_class_payload(
    page_index,
    start_date,
    end_date,
    *,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
) -> dict:
    start_vn, end_vn = vn_date_range(start_date, end_date)
    return {
        "filter_textSearch": normalize_text(search_text),
        "centre_in": list(parse_csv_values(centres)),
        "course_in": list(parse_csv_values(courses)),
        "courseLine_in": list(parse_csv_values(course_lines)),
        "id_in": list(parse_csv_values(class_ids)) or None,
        "haveSlot_from": to_utc_iso(start_vn),
        "haveSlot_to": to_utc_iso(end_vn),
        "status_in": list(parse_csv_values(statuses, upper=True) or DEFAULT_CLASS_STATUSES),
        "pageIndex": page_index,
        "itemsPerPage": max(1, int(items_per_page or DEFAULT_ITEMS_PER_PAGE)),
        "orderBy": "name_asc",
        "paginationType": "OFFSET",
    }


def fetch_classes(
    start_date=DEFAULT_START_DATE,
    end_date=None,
    *,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
    max_classes=None,
    detail=True,
    auto_login=False,
    force_refresh=False,
) -> list[dict]:
    token = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    end_date = end_date or date.today().isoformat()
    query = GET_CLASSES_QUERY if detail else GET_CLASS_FILTER_QUERY
    operation_name = "TeacherAttendanceClasses" if detail else "TeacherAttendanceClassOptions"
    limit = max(1, int(items_per_page or DEFAULT_ITEMS_PER_PAGE))
    max_count = int(max_classes) if max_classes else None
    session = create_session()
    classes = []
    seen = set()
    page_index = 0

    while True:
        variables = build_class_payload(
            page_index,
            start_date,
            end_date,
            statuses=statuses,
            class_ids=class_ids,
            course_lines=course_lines,
            courses=courses,
            centres=centres,
            search_text=search_text,
            items_per_page=limit,
        )
        result = post_graphql(
            {"operationName": operation_name, "variables": {"payload": variables}, "query": query},
            token,
            session=session,
            allow_legacy_role_errors=detail,
        )
        page = ((result.get("data") or {}).get("classes") or {})
        batch = page.get("data") or []
        total = int((page.get("pagination") or {}).get("total") or 0)
        for class_info in batch:
            class_id = normalize_text(class_info.get("id"))
            if not class_id or class_id in seen:
                continue
            seen.add(class_id)
            classes.append(class_info)
            if max_count and len(classes) >= max_count:
                break

        print(
            f"📚 Teacher attendance classes trang {page_index}: "
            f"{len(batch)} lớp · tổng đã lấy {len(classes)}/{total or '?'}",
            flush=True,
        )
        if (
            not batch
            or (max_count and len(classes) >= max_count)
            or (total and (page_index + 1) * limit >= total)
            or len(batch) < limit
        ):
            break
        page_index += 1
        time.sleep(0.05)
    return classes


def course_display(class_info) -> str:
    course = (class_info or {}).get("course") or {}
    return normalize_text(course.get("name") or course.get("shortName") or course.get("code"))


def course_line_display(class_info) -> str:
    line = ((class_info or {}).get("course") or {}).get("courseLine") or {}
    return normalize_text(line.get("name") or line.get("shortName") or line.get("code"))


def centre_display(class_info) -> str:
    centre = (class_info or {}).get("centre") or {}
    return normalize_text(centre.get("shortName") or centre.get("name"))


def build_status_filter_options(statuses=None) -> list[dict]:
    return [
        {"value": status, "label": status.replace("_", " ").title(), "name": "classStatus"}
        for status in parse_csv_values(statuses, upper=True) or DEFAULT_CLASS_STATUSES
    ]


def build_class_filter_options(classes) -> dict:
    options = []
    seen = set()
    for class_info in classes or []:
        class_id = normalize_text(class_info.get("id"))
        class_name = normalize_text(class_info.get("name"))
        if not class_id or not class_name or class_id in seen:
            continue
        seen.add(class_id)
        options.append({
            "id": class_id,
            "name": class_name,
            "subject": course_line_display(class_info),
            "course": course_display(class_info),
            "centre": centre_display(class_info),
        })
    return {"classes": sorted(options, key=lambda item: normalize_for_search(item["name"]))}


def fetch_teacher_attendance_class_filter_options(
    start_date=DEFAULT_START_DATE,
    end_date=None,
    *,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    class_limit=DEFAULT_ITEMS_PER_PAGE,
    auto_login=False,
    force_refresh=False,
) -> dict:
    classes = fetch_classes(
        start_date,
        end_date,
        statuses=statuses,
        class_ids=class_ids,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        search_text=search_text,
        items_per_page=class_limit,
        max_classes=class_limit,
        detail=False,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    return build_class_filter_options(classes)


def is_target_slot(slot, start_vn, end_vn, sessions) -> bool:
    start_time = parse_api_datetime((slot or {}).get("startTime") or (slot or {}).get("date"))
    session_index = (slot or {}).get("index")
    if not start_time or start_time < start_vn or start_time > end_vn:
        return False
    return isinstance(session_index, int) and session_index + 1 in sessions


def target_slots(classes, start_date, end_date, sessions) -> list[tuple[dict, dict]]:
    start_vn, end_vn = vn_date_range(start_date, end_date)
    selected_sessions = set(parse_session_numbers(sessions))
    result = []
    for class_info in classes or []:
        for slot in class_info.get("slots") or []:
            if is_target_slot(slot, start_vn, end_vn, selected_sessions):
                result.append((class_info, slot))
    return result


def teacher_id(entry) -> str:
    return normalize_text(((entry or {}).get("teacher") or {}).get("id"))


def assignment_lookup(entries) -> dict[str, dict]:
    return {
        teacher_id(entry): entry
        for entry in entries or []
        if teacher_id(entry)
    }


def slot_assignments(class_info, slot) -> list[dict]:
    slot_id = normalize_text((slot or {}).get("_id"))
    class_sites = (class_info or {}).get("classSites") or []
    class_site_by_id = {
        normalize_text(site.get("_id")): site
        for site in class_sites
        if normalize_text(site.get("_id"))
    }
    class_teacher_map = assignment_lookup((class_info or {}).get("teachers"))
    site_teacher_maps = {
        site_id: assignment_lookup(site.get("teachers"))
        for site_id, site in class_site_by_id.items()
    }
    assignments = []
    seen = set()

    def add(entry, site=None):
        current_teacher_id = teacher_id(entry)
        if not current_teacher_id:
            return
        site_id = normalize_text((site or {}).get("_id") or (entry or {}).get("classSiteId"))
        key = (site_id, current_teacher_id)
        if key in seen:
            return
        seen.add(key)
        assignments.append({"entry": entry, "site": site or class_site_by_id.get(site_id) or {}})

    for site in class_sites:
        for class_site_slot in site.get("classSiteSlots") or []:
            if normalize_text(class_site_slot.get("classSlotId")) != slot_id:
                continue
            for entry in class_site_slot.get("teachers") or []:
                add(entry, site)

    # classSiteSlots is the source of truth for per-session assignments. The
    # slot-level list can retain the class's default teacher after a supply swap.
    if not assignments:
        for entry in (slot or {}).get("teachers") or []:
            site_id = normalize_text(entry.get("classSiteId"))
            site = class_site_by_id.get(site_id)
            if site is None and len(class_sites) == 1:
                site = class_sites[0]
            add(entry, site)

    attendance_by_teacher = {
        teacher_id(item): item
        for item in (slot or {}).get("teacherAttendance") or []
        if teacher_id(item)
    }
    assigned_teacher_ids = {teacher_id(item["entry"]) for item in assignments}
    for current_teacher_id, attendance in attendance_by_teacher.items():
        if current_teacher_id in assigned_teacher_ids:
            continue
        site_id = normalize_text(attendance.get("classSiteId"))
        site = class_site_by_id.get(site_id)
        if site is None and len(class_sites) == 1:
            site = class_sites[0]
            site_id = normalize_text(site.get("_id"))
        role_entry = (site_teacher_maps.get(site_id) or {}).get(current_teacher_id)
        role_entry = role_entry or class_teacher_map.get(current_teacher_id) or {}
        add({
            "teacher": attendance.get("teacher") or {},
            "role": role_entry.get("role") or {},
            "classSiteId": site_id,
            "isActive": role_entry.get("isActive"),
        }, site)
    return assignments


def collect_teacher_ids(slot_contexts) -> tuple[str, ...]:
    result = []
    seen = set()
    for class_info, slot in slot_contexts:
        for assignment in slot_assignments(class_info, slot):
            current_id = teacher_id(assignment.get("entry"))
            if current_id and current_id not in seen:
                seen.add(current_id)
                result.append(current_id)
    return tuple(result)


def fetch_teacher_timesheet(teacher_id_value, start_date, end_date, token) -> dict:
    payload = {
        "operationName": "TeacherClassAttendanceTimesheet",
        "variables": {
            "payload": {
                "teacherId": teacher_id_value,
                "startDate": parse_date(start_date).isoformat(),
                "endDate": parse_date(end_date).isoformat(),
                "type": "ATTENDANCE_CLASS",
            }
        },
        "query": GET_TEACHER_TIMESHEET_QUERY,
    }
    result = post_graphql(payload, token, session=create_session())
    rows = ((result.get("data") or {}).get("findTimesheetByTeacher") or [])
    timesheet = {}
    for item in rows:
        attendance = (item or {}).get("classSessionAttendance") or {}
        slot_id = normalize_text(attendance.get("id"))
        if not slot_id:
            continue
        timesheet[(teacher_id_value, slot_id)] = {
            "status": normalize_attendance_status(item.get("status")),
            "effective_duration": attendance.get("sessionHour"),
            "status_detail": normalize_text(attendance.get("status")).upper(),
        }
    return timesheet


def fetch_timesheet_map(
    teacher_ids,
    start_date,
    end_date,
    *,
    token,
    workers=DEFAULT_TIMESHEET_WORKERS,
) -> dict:
    selected_ids = tuple(dict.fromkeys(value for value in teacher_ids if value))
    if not selected_ids:
        return {}
    result = {}
    worker_count = min(max(1, int(workers or 1)), len(selected_ids))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_teacher_timesheet, value, start_date, end_date, token): value
            for value in selected_ids
        }
        completed = 0
        for future in as_completed(futures):
            current_id = futures[future]
            completed += 1
            try:
                result.update(future.result())
            except Exception as exc:
                print(f"⚠️ Không tải được timesheet giáo viên {current_id}: {exc}", flush=True)
            print(f"🧑‍🏫 Timesheet giáo viên {completed}/{len(selected_ids)}", flush=True)
    return result


def normalize_attendance_status(value) -> str:
    return "CHECKED" if normalize_text(value).upper() == "CHECKED" else "UNCHECKED"


def fallback_status(raw_status) -> str:
    return "CHECKED" if normalize_text(raw_status).upper() in CHECKED_ATTENDANCE_DETAILS else "UNCHECKED"


def duration_hours(start_time, end_time):
    if not start_time or not end_time:
        return ""
    hours = (end_time - start_time).total_seconds() / 3600
    return number_value(hours) if hours >= 0 else ""


def number_value(value):
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else round(number, 2)


def format_slot_time(start_time, end_time) -> str:
    if not start_time:
        return ""
    if end_time:
        return f"{start_time:%d/%m/%Y %H:%M} - {end_time:%H:%M}"
    return f"{start_time:%d/%m/%Y %H:%M}"


def student_count_for_site(slot, site_id) -> int:
    attendances = (slot or {}).get("studentAttendance") or []
    if not site_id:
        return len(attendances)
    site_attendances = [
        item for item in attendances
        if normalize_text((item or {}).get("classSiteId")) == site_id
    ]
    return len(site_attendances) if site_attendances else len(attendances)


def build_export_rows(slot_contexts, timesheet_map=None) -> list[dict]:
    timesheet_map = timesheet_map or {}
    rows = []
    for class_info, slot in slot_contexts:
        slot_id = normalize_text(slot.get("_id"))
        start_time = parse_api_datetime(slot.get("startTime") or slot.get("date"))
        end_time = parse_api_datetime(slot.get("endTime"))
        attendance_map = {
            teacher_id(item): item
            for item in slot.get("teacherAttendance") or []
            if teacher_id(item)
        }
        course = class_info.get("course") or {}
        course_line = course.get("courseLine") or {}
        class_centre = class_info.get("centre") or {}
        session_number = slot.get("index") + 1 if isinstance(slot.get("index"), int) else ""

        for assignment in slot_assignments(class_info, slot):
            entry = assignment.get("entry") or {}
            site = assignment.get("site") or {}
            teacher = entry.get("teacher") or {}
            role = entry.get("role") or {}
            current_teacher_id = normalize_text(teacher.get("id"))
            attendance = attendance_map.get(current_teacher_id) or {}
            timesheet = timesheet_map.get((current_teacher_id, slot_id)) or {}
            centre = site.get("centre") or class_centre
            site_id = normalize_text(site.get("_id") or entry.get("classSiteId"))
            effective_duration = timesheet.get("effective_duration")
            if effective_duration in (None, ""):
                effective_duration = slot.get("sessionHour")
            if effective_duration in (None, ""):
                effective_duration = duration_hours(start_time, end_time)

            status = timesheet.get("status")
            if not status:
                status = fallback_status(attendance.get("status"))

            rows.append({
                "Centre shortname": normalize_text(centre.get("shortName") or centre.get("name")),
                "Type": "CLASS",
                "Class name": normalize_text(class_info.get("name")),
                "Class Site": normalize_text(site.get("name")),
                "Course": normalize_text(course.get("name") or course.get("shortName") or course.get("code")),
                "Course Line": normalize_text(course_line.get("name") or course_line.get("shortName")),
                "Buổi": session_number,
                "Teacher name": normalize_text(teacher.get("fullName")),
                "Work email": normalize_text(teacher.get("email")),
                "Personal email": normalize_text(teacher.get("personalEmail")),
                "Username": normalize_text(teacher.get("username") or teacher.get("code")),
                "Class role/Office hour type": normalize_text(role.get("shortName") or role.get("name")),
                "Status": normalize_attendance_status(status),
                "Slot time": format_slot_time(start_time, end_time),
                "Slot duration": duration_hours(start_time, end_time),
                "Effective duration": number_value(effective_duration),
                "Student count": student_count_for_site(slot, site_id),
                "_sort_time": start_time or datetime.min.replace(tzinfo=VN_TZ),
            })

    rows.sort(key=lambda row: (
        row["_sort_time"],
        normalize_for_search(row["Class name"]),
        normalize_for_search(row["Class Site"]),
        normalize_for_search(row["Teacher name"]),
    ))
    for row in rows:
        row.pop("_sort_time", None)
    return rows


def export_teacher_attendance(
    start_date=DEFAULT_START_DATE,
    end_date=None,
    output_file=None,
    *,
    sessions=None,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    class_limit=DEFAULT_ITEMS_PER_PAGE,
    timesheet_workers=DEFAULT_TIMESHEET_WORKERS,
    auto_login=False,
    force_refresh=False,
) -> str | None:
    end_date = end_date or date.today().isoformat()
    selected_sessions = parse_session_numbers(sessions)
    token = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    classes = fetch_classes(
        start_date,
        end_date,
        statuses=statuses,
        class_ids=class_ids,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        search_text=search_text,
        items_per_page=class_limit,
        auto_login=False,
        force_refresh=False,
    )
    if not classes:
        print("⚠️ Không có lớp phù hợp với bộ lọc điểm danh giáo viên.", flush=True)
        return None

    contexts = target_slots(classes, start_date, end_date, selected_sessions)
    if not contexts:
        print("⚠️ Không có buổi học phù hợp với ngày và số buổi đã chọn.", flush=True)
        return None

    selected_teacher_ids = collect_teacher_ids(contexts)
    timesheet_map = fetch_timesheet_map(
        selected_teacher_ids,
        start_date,
        end_date,
        token=token,
        workers=timesheet_workers,
    )
    rows = build_export_rows(contexts, timesheet_map)
    if not rows:
        print("⚠️ Không có giáo viên được phân công trong các buổi học đã chọn.", flush=True)
        return None

    output_path = Path(output_file or DEFAULT_OUTPUT_FILE).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    checked_count = sum(1 for row in rows if row["Status"] == "CHECKED")
    print(
        f"📁 Đã lưu {len(rows)} dòng điểm danh giáo viên từ {len(contexts)} buổi học "
        f"({checked_count} CHECKED, {len(rows) - checked_count} UNCHECKED) vào '{output_path}'",
        flush=True,
    )
    return str(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Xuất điểm danh giáo viên theo từng buổi học LMS.")
    parser.add_argument("--start", "--start-date", dest="start_date", default=DEFAULT_START_DATE)
    parser.add_argument("--end", "--end-date", dest="end_date", default=date.today().isoformat())
    parser.add_argument("--sessions", default=",".join(map(str, DEFAULT_SESSION_NUMBERS)))
    parser.add_argument("--status", action="append", dest="statuses")
    parser.add_argument("--class-id", action="append", dest="class_ids")
    parser.add_argument("--course-line", action="append", dest="course_lines")
    parser.add_argument("--course", action="append", dest="courses")
    parser.add_argument("--centre", "--center", action="append", dest="centres")
    parser.add_argument("--search", default="")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--class-limit", type=int, default=DEFAULT_ITEMS_PER_PAGE)
    parser.add_argument("--workers", type=int, default=DEFAULT_TIMESHEET_WORKERS)
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    return export_teacher_attendance(
        start_date=args.start_date,
        end_date=args.end_date,
        output_file=args.output,
        sessions=args.sessions,
        statuses=args.statuses or DEFAULT_CLASS_STATUSES,
        class_ids=args.class_ids,
        course_lines=args.course_lines,
        courses=args.courses,
        centres=args.centres,
        search_text=args.search,
        class_limit=args.class_limit,
        timesheet_workers=args.workers,
        auto_login=args.login,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
