"""Export student completion status from MindX LMS classes.

This module is a productionized version of the workflow in
``complatetion_class.ipynb``:

1. Query LMS classes with optional class/course/centre/date filters.
2. Query class student completion details for each class.
3. Write one CSV containing class metadata and student completion fields.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter, Retry

from lms_auth import AuthError, TOKEN_HELP, build_auth_headers, ensure_auth_token

load_dotenv()

API_URL = "https://lms-api.mindx.edu.vn/graphql"
API_ROOT_URL = "https://lms-api.mindx.edu.vn/"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC_TZ = ZoneInfo("UTC")

DEFAULT_START_DATE = "2026-06-01"
DEFAULT_OUTPUT_FILE = "students_completion_status.csv"
DEFAULT_ITEMS_PER_PAGE = int(os.getenv("COMPLETION_CLASSES_PER_PAGE", "100"))
DEFAULT_CLASS_LIMIT = int(os.getenv("COMPLETION_FILTER_CLASS_LIMIT", "100"))
DEFAULT_STUDENT_WORKERS = int(os.getenv("COMPLETION_STUDENT_WORKERS", "4"))
REQUEST_DELAY_SECONDS = float(os.getenv("COMPLETION_REQUEST_DELAY_SECONDS", "0.05"))
DEFAULT_DATE_FIELD = "startDate"
DEFAULT_CLASS_STATUSES = ("PENDING", "PRE_OPEN", "RUNNING", "OPEN", "FINISHED")

AUTH_TOKEN = (os.getenv("LMS_AUTH_TOKEN") or os.getenv("AUTH_TOKEN") or os.getenv("TOKEN") or "").strip()
HEADERS = build_auth_headers(AUTH_TOKEN) if AUTH_TOKEN else {
    "Authorization": "",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://lms.mindx.edu.vn",
    "Referer": "https://lms.mindx.edu.vn/",
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

EXPORT_COLUMNS = [
    "Ngày xuất",
    "Class ID",
    "Mã lớp",
    "Cơ sở",
    "Course",
    "Course line",
    "Ngày bắt đầu",
    "Ngày kết thúc",
    "Trạng thái lớp",
    "Giáo viên",
    "Số học viên trong lớp",
    "Số lượng học viên khi lớp học kết thúc",
    "Số lượng học viên uncompleted",
    "Class student ID",
    "Student ID",
    "Tên học viên",
    "Email học viên",
    "Completed",
    "Completion status",
    "Completion reason",
    "Completion note",
]

GET_CLASSES_QUERY = """
query GetClasses(
  $search: String,
  $centres: [String],
  $courses: [String],
  $courseLines: [String],
  $classIds: [String],
  $startDateFrom: Date,
  $startDateTo: Date,
  $endDateFrom: Date,
  $endDateTo: Date,
  $statusIn: [String],
  $pageIndex: Int!,
  $itemsPerPage: Int!,
  $orderBy: String
) {
  classes(payload: {
    id_in: $classIds,
    filter_textSearch: $search,
    centre_in: $centres,
    course_in: $courses,
    courseLine_in: $courseLines,
    startDate_gt: $startDateFrom,
    startDate_lt: $startDateTo,
    endDate_gt: $endDateFrom,
    endDate_lt: $endDateTo,
    status_in: $statusIn,
    pageIndex: $pageIndex,
    itemsPerPage: $itemsPerPage,
    orderBy: $orderBy
  }) {
    data {
      id
      name
      startDate
      endDate
      status
      centre {
        id
        shortName
        name
      }
      course {
        id
        code
        shortName
        name
        courseLine {
          id
          name
        }
      }
      teachers {
        teacher {
          id
          fullName
          code
          email
        }
        role {
          id
          name
          shortName
        }
      }
      students {
        _id
      }
    }
    pagination {
      total
    }
  }
}
"""

CLASS_STUDENTS_COMPLETION_QUERY = """
query ClassStudentsForCompletion($classIds: [String], $itemsPerPage: Int!) {
  classes(payload: {id_in: $classIds, pageIndex: 0, itemsPerPage: $itemsPerPage}) {
    data {
      id
      name
      students {
        _id
        activeInClass
        completed
        completionInfo {
          status
          reason
          note
        }
        student {
          id
          studentId
          fullName
          email
        }
      }
    }
  }
}
"""


def refresh_auth_token(auto_login=False, force_refresh=False):
    global AUTH_TOKEN, HEADERS

    AUTH_TOKEN = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    HEADERS = build_auth_headers(AUTH_TOKEN)
    return AUTH_TOKEN


def ensure_valid_token(auto_login=False, force_refresh=False):
    refresh_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    if not AUTH_TOKEN:
        raise RuntimeError(TOKEN_HELP)


def create_session():
    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=0.8,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def is_auth_error(error):
    return "Authentication failed" in str(error) or TOKEN_HELP in str(error)


def is_http_auth_error(error):
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    return status_code in {401, 403}


def post_graphql_payload(payload, session=None, timeout=(10, 60), retry_auth=True):
    active_session = session or create_session()
    last_error = None
    auth_retried = False

    while True:
        for url in (API_URL, API_ROOT_URL):
            try:
                response = active_session.post(url, headers=HEADERS, json=payload, timeout=timeout)
                response.raise_for_status()
                data = response.json()
                api_errors = data.get("errors")
                if api_errors:
                    if retry_auth and not auth_retried and is_auth_error(api_errors):
                        refresh_auth_token(auto_login=False, force_refresh=True)
                        auth_retried = True
                        break
                    if is_auth_error(api_errors):
                        raise AuthError(TOKEN_HELP)
                    raise RuntimeError(api_errors)
                return data
            except requests.exceptions.RequestException as error:
                last_error = error
                status_code = getattr(getattr(error, "response", None), "status_code", None)
                if status_code in {404, 405}:
                    continue
                if retry_auth and not auth_retried and is_http_auth_error(error):
                    refresh_auth_token(auto_login=False, force_refresh=True)
                    auth_retried = True
                    break
                if is_http_auth_error(error):
                    raise AuthError(TOKEN_HELP) from error
                raise
        else:
            break

        if auth_retried:
            continue

    if last_error:
        raise last_error
    raise RuntimeError("Không thể gửi request GraphQL.")


def parse_vn_date(value, field_name="ngày"):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"{field_name} không hợp lệ: {text}. Dùng YYYY-MM-DD hoặc DD/MM/YYYY.")


def vn_date_range_to_utc(start_date, end_date):
    start_vn = datetime.combine(parse_vn_date(start_date, "ngày bắt đầu"), dt_time.min).replace(tzinfo=VN_TZ)
    end_vn = datetime.combine(parse_vn_date(end_date, "ngày kết thúc"), dt_time.max).replace(tzinfo=VN_TZ)
    return (
        start_vn.astimezone(UTC_TZ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        end_vn.astimezone(UTC_TZ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )


def normalize_text(value):
    return str(value or "").strip()


def normalize_for_search(value):
    normalized = unicodedata.normalize("NFD", normalize_text(value))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").lower()


def parse_csv_values(value, upper=False):
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            items.extend(parse_csv_values(item, upper=upper))
        return tuple(items)
    items = [item.strip() for item in re.split(r"[,\n]+", normalize_text(value)) if item.strip()]
    return tuple(item.upper() if upper else item for item in items)


def normalize_date_field(value):
    field = normalize_text(value)
    if field not in {"startDate", "endDate"}:
        return DEFAULT_DATE_FIELD
    return field


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


def option_sort_key(option):
    return (normalize_for_search(option.get("label")), normalize_for_search(option.get("name")))


def add_filter_option(options, seen, value, label=None, name=None):
    value = normalize_text(value)
    label = normalize_text(label) or value
    name = normalize_text(name)
    key = normalize_for_search(value)
    if not key or key in seen:
        return
    seen.add(key)
    options.append({"value": value, "label": label, "name": name})


def course_entity(class_info):
    return (class_info or {}).get("course") or {}


def course_line_entity(class_info):
    course = course_entity(class_info)
    if isinstance(course, dict) and course.get("courseLine"):
        return course.get("courseLine") or {}
    return (class_info or {}).get("courseLine") or {}


def course_display(class_info):
    course = course_entity(class_info)
    code = normalize_text(course.get("shortName") or course.get("code"))
    name = normalize_text(course.get("name"))
    if code and name and normalize_for_search(code) not in normalize_for_search(name):
        return f"{code} - {name}"
    return code or name or normalize_text(course.get("id"))


def course_line_display(class_info):
    line = course_line_entity(class_info)
    return first_entity_value(line, ("shortName", "code", "name", "label", "value", "id"))


def centre_display(class_info):
    centre = (class_info or {}).get("centre") or {}
    return normalize_text(centre.get("name") or centre.get("shortName") or centre.get("id"))


def teacher_display(entry):
    teacher = (entry or {}).get("teacher") or {}
    role = (entry or {}).get("role") or {}
    name = normalize_text(teacher.get("fullName") or teacher.get("email") or teacher.get("id"))
    code = normalize_text(teacher.get("code"))
    role_name = normalize_text(role.get("shortName") or role.get("name"))
    teacher_name = f"{name} - {code}" if name and code else name or code
    return f"{teacher_name} ({role_name})" if teacher_name and role_name else teacher_name


def teachers_display(class_info):
    values = []
    seen = set()
    for item in (class_info or {}).get("teachers") or []:
        text = teacher_display(item)
        key = normalize_for_search(text)
        if text and key not in seen:
            seen.add(key)
            values.append(text)
    return "; ".join(values)


def format_api_date(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(VN_TZ).strftime("%Y-%m-%d")
    except ValueError:
        return normalize_text(value)


def bool_text(value):
    if is_true_value(value):
        return "TRUE"
    if is_false_value(value):
        return "FALSE"
    return ""


def is_true_value(value):
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def is_false_value(value):
    if value is False:
        return True
    if value is True or value is None:
        return False
    return str(value).strip().lower() in {"false", "0", "no"}


def is_active_in_class(value):
    return is_true_value(value)


def normalize_completion_status(value):
    return re.sub(r"[^A-Z0-9]+", "", normalize_text(value).upper())


def is_uncompleted_completion(student_row):
    if (student_row or {}).get("has_completion_info") is False:
        return True
    status = normalize_completion_status((student_row or {}).get("completion_status"))
    if status in {"COMPLETED", "COMPLETE"}:
        return False
    return True


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


def build_class_filter_options(classes):
    course_lines = []
    courses = []
    centres = []
    statuses = []
    class_options = []
    seen_course_lines = set()
    seen_courses = set()
    seen_centres = set()
    seen_statuses = set()
    seen_classes = set()

    for class_info in classes or []:
        class_id = normalize_text((class_info or {}).get("id"))
        class_name = normalize_text((class_info or {}).get("name"))
        course = course_entity(class_info)
        line = course_line_entity(class_info)
        centre = (class_info or {}).get("centre") or {}
        status = normalize_text((class_info or {}).get("status")).upper()

        line_value = first_entity_value(line)
        line_label = first_entity_value(line, ("shortName", "code", "name", "label", "value")) or line_value
        add_filter_option(course_lines, seen_course_lines, line_value, line_label)

        course_value = first_entity_value(course)
        course_label = first_entity_value(course, ("shortName", "code", "name", "label", "value")) or course_display(class_info)
        add_filter_option(courses, seen_courses, course_value, course_label, course_display(class_info))

        centre_value = first_entity_value(centre)
        centre_label = centre_display(class_info)
        add_filter_option(centres, seen_centres, centre_value, centre_label, centre_label)

        if status and status not in seen_statuses:
            seen_statuses.add(status)
            statuses.append({"value": status, "label": status.replace("_", " ").title(), "name": "classStatus"})

        if class_id and class_name and class_id not in seen_classes:
            seen_classes.add(class_id)
            class_options.append({
                "id": class_id,
                "name": class_name,
                "subject": course_line_display(class_info),
                "course": course_display(class_info),
                "centre": centre_display(class_info),
            })

    return {
        "course_lines": sorted(course_lines, key=option_sort_key),
        "courses": sorted(courses, key=option_sort_key),
        "centres": sorted(centres, key=option_sort_key),
        "statuses": sorted(statuses, key=option_sort_key) or build_status_filter_options(),
        "classes": sorted(class_options, key=lambda item: normalize_for_search(item["name"])),
    }


def build_classes_payload(
    page_index,
    start_date,
    end_date,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    date_field=DEFAULT_DATE_FIELD,
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
):
    start_utc, end_utc = vn_date_range_to_utc(start_date, end_date)
    field = normalize_date_field(date_field)
    variables = {
        "search": normalize_text(search_text),
        "centres": list(centres or []),
        "courses": list(courses or []),
        "courseLines": list(course_lines or []),
        "classIds": list(class_ids or []) or None,
        "startDateFrom": start_utc if field == "startDate" else None,
        "startDateTo": end_utc if field == "startDate" else None,
        "endDateFrom": start_utc if field == "endDate" else None,
        "endDateTo": end_utc if field == "endDate" else None,
        "statusIn": list(statuses or DEFAULT_CLASS_STATUSES),
        "pageIndex": page_index,
        "itemsPerPage": max(1, int(items_per_page or DEFAULT_ITEMS_PER_PAGE)),
        "orderBy": f"{field}_desc",
    }
    return {
        "operationName": "GetClasses",
        "variables": variables,
        "query": GET_CLASSES_QUERY,
    }


def fetch_classes(
    start_date=DEFAULT_START_DATE,
    end_date=None,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    date_field=DEFAULT_DATE_FIELD,
    items_per_page=DEFAULT_ITEMS_PER_PAGE,
    max_classes=None,
    auto_login=False,
    force_refresh=False,
    skip_auth=False,
):
    if not skip_auth:
        ensure_valid_token(auto_login=auto_login, force_refresh=force_refresh)

    end_date = end_date or date.today().isoformat()
    selected_statuses = parse_csv_values(statuses, upper=True) or DEFAULT_CLASS_STATUSES
    selected_class_ids = parse_csv_values(class_ids)
    selected_course_lines = parse_csv_values(course_lines)
    selected_courses = parse_csv_values(courses)
    selected_centres = parse_csv_values(centres)
    limit = max(1, int(items_per_page or DEFAULT_ITEMS_PER_PAGE))
    max_count = int(max_classes) if max_classes else None

    session = create_session()
    classes = []
    seen = set()
    scanned = 0
    page_index = 0

    while True:
        payload = build_classes_payload(
            page_index,
            start_date,
            end_date,
            selected_statuses,
            selected_class_ids,
            selected_course_lines,
            selected_courses,
            selected_centres,
            search_text,
            date_field,
            limit,
        )
        try:
            res_json = post_graphql_payload(payload, session=session, timeout=(10, 60))
        except requests.exceptions.RequestException as error:
            raise RuntimeError(f"Lỗi tải classes completion trang {page_index}: {error}") from error
        except RuntimeError as error:
            if "Authentication failed" in str(error):
                raise RuntimeError(TOKEN_HELP) from error
            raise RuntimeError(f"API lỗi classes completion trang {page_index}: {error}") from error

        page = res_json.get("data", {}).get("classes", {})
        batch = page.get("data") or []
        total = (page.get("pagination") or {}).get("total") or 0
        scanned += len(batch)
        for class_info in batch:
            class_id = normalize_text(class_info.get("id"))
            if not class_id or class_id in seen:
                continue
            seen.add(class_id)
            classes.append(class_info)
            if max_count and len(classes) >= max_count:
                break

        print(f"✅ Completion classes trang {page_index}: lấy {len(batch)} lớp ({scanned} / {total or '?'})", flush=True)

        if max_count and len(classes) >= max_count:
            break
        if not batch or (total and scanned >= total):
            break

        page_index += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    return classes


def fetch_class_completion_status(class_id, session=None):
    class_id = normalize_text(class_id)
    if not class_id:
        return []
    payload = {
        "operationName": "ClassStudentsForCompletion",
        "variables": {"classIds": [class_id], "itemsPerPage": 1},
        "query": CLASS_STUDENTS_COMPLETION_QUERY,
    }
    try:
        res_json = post_graphql_payload(payload, session=session, timeout=(10, 60))
    except requests.exceptions.RequestException as error:
        raise RuntimeError(f"Lỗi tải completion lớp {class_id}: {error}") from error
    except RuntimeError as error:
        if "Authentication failed" in str(error):
            raise RuntimeError(TOKEN_HELP) from error
        raise RuntimeError(f"API lỗi completion lớp {class_id}: {error}") from error

    classes = res_json.get("data", {}).get("classes", {}).get("data") or []
    students = (classes[0] if classes else {}).get("students") or []
    rows = []
    for item in students:
        student = (item or {}).get("student") or {}
        raw_completion_info = (item or {}).get("completionInfo")
        has_completion_info = isinstance(raw_completion_info, dict)
        completion_info = raw_completion_info if has_completion_info else {}
        rows.append({
            "class_student_id": normalize_text((item or {}).get("id") or (item or {}).get("_id")),
            "student_id": normalize_text(student.get("studentId") or student.get("id")),
            "student_name": normalize_text(student.get("fullName")),
            "student_email": normalize_text(student.get("email")),
            "active_in_class": (item or {}).get("activeInClass"),
            "completed": (item or {}).get("completed"),
            "has_completion_info": has_completion_info,
            "completion_status": normalize_text(completion_info.get("status")),
            "completion_reason": normalize_text(completion_info.get("reason")),
            "completion_note": normalize_text(completion_info.get("note")),
        })
    return rows


def class_completion_counts(student_rows):
    return {
        "Số lượng học viên khi lớp học kết thúc": sum(
            1 for student_row in student_rows or [] if is_active_in_class(student_row.get("active_in_class"))
        ),
        "Số lượng học viên uncompleted": sum(
            1
            for student_row in student_rows or []
            if is_active_in_class(student_row.get("active_in_class"))
            and is_uncompleted_completion(student_row)
        ),
    }


def class_row_context(class_info, completion_counts=None):
    counts = completion_counts or {}
    return {
        "Class ID": normalize_text((class_info or {}).get("id")),
        "Mã lớp": normalize_text((class_info or {}).get("name")),
        "Cơ sở": centre_display(class_info),
        "Course": course_display(class_info),
        "Course line": course_line_display(class_info),
        "Ngày bắt đầu": format_api_date((class_info or {}).get("startDate")),
        "Ngày kết thúc": format_api_date((class_info or {}).get("endDate")),
        "Trạng thái lớp": normalize_text((class_info or {}).get("status")),
        "Giáo viên": teachers_display(class_info),
        "Số học viên trong lớp": len((class_info or {}).get("students") or []),
        "Số lượng học viên khi lớp học kết thúc": counts.get("Số lượng học viên khi lớp học kết thúc", ""),
        "Số lượng học viên uncompleted": counts.get("Số lượng học viên uncompleted", ""),
    }


def completion_export_row(class_info, student_row, exported_at, completion_counts=None):
    row = {
        "Ngày xuất": exported_at,
        **class_row_context(class_info, completion_counts),
        "Class student ID": student_row.get("class_student_id", ""),
        "Student ID": student_row.get("student_id", ""),
        "Tên học viên": student_row.get("student_name", ""),
        "Email học viên": student_row.get("student_email", ""),
        "Completed": bool_text(student_row.get("completed")),
        "Completion status": student_row.get("completion_status", ""),
        "Completion reason": student_row.get("completion_reason", ""),
        "Completion note": student_row.get("completion_note", ""),
    }
    return row


def build_completion_rows(classes, workers=DEFAULT_STUDENT_WORKERS):
    exported_at = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    class_list = list(classes or [])
    rows = []
    total_classes = len(class_list)
    if not total_classes:
        return rows

    worker_count = max(1, min(int(workers or DEFAULT_STUDENT_WORKERS), total_classes))

    def fetch_one(class_info):
        session = create_session()
        class_id = normalize_text(class_info.get("id"))
        student_rows = fetch_class_completion_status(class_id, session=session)
        return class_info, student_rows

    print(f"🚀 Đang tải completion cho {total_classes} lớp · {worker_count} workers", flush=True)
    if worker_count == 1:
        for index, class_info in enumerate(class_list, start=1):
            class_name = normalize_text(class_info.get("name") or class_info.get("id"))
            print(f"📘 Completion {index}/{total_classes}: {class_name}", flush=True)
            _, student_rows = fetch_one(class_info)
            completion_counts = class_completion_counts(student_rows)
            for student_row in student_rows:
                rows.append(completion_export_row(class_info, student_row, exported_at, completion_counts))
            time.sleep(REQUEST_DELAY_SECONDS)
        return rows

    completed = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(fetch_one, class_info) for class_info in class_list]
        for future in futures:
            class_info, student_rows = future.result()
            completed += 1
            class_name = normalize_text(class_info.get("name") or class_info.get("id"))
            print(
                f"📘 Completion {completed}/{total_classes}: {class_name} · {len(student_rows)} học viên",
                flush=True,
            )
            completion_counts = class_completion_counts(student_rows)
            for student_row in student_rows:
                rows.append(completion_export_row(class_info, student_row, exported_at, completion_counts))

    rows.sort(key=lambda item: (normalize_for_search(item.get("Mã lớp")), normalize_for_search(item.get("Tên học viên"))))
    return rows


def fetch_completion_class_filter_options(
    start_date=DEFAULT_START_DATE,
    end_date=None,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    date_field=DEFAULT_DATE_FIELD,
    class_limit=DEFAULT_CLASS_LIMIT,
    auto_login=False,
    force_refresh=False,
):
    classes = fetch_classes(
        start_date=start_date,
        end_date=end_date,
        statuses=statuses,
        class_ids=class_ids,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        search_text=search_text,
        date_field=date_field,
        items_per_page=min(max(1, int(class_limit or DEFAULT_CLASS_LIMIT)), DEFAULT_ITEMS_PER_PAGE),
        max_classes=max(1, int(class_limit or DEFAULT_CLASS_LIMIT)),
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    return {"classes": build_class_filter_options(classes).get("classes") or []}


def resolve_output_path(output_file=None):
    path = Path(output_file or DEFAULT_OUTPUT_FILE).expanduser()
    return str(path)


def export_completion_status(
    start_date=DEFAULT_START_DATE,
    end_date=None,
    output_file=None,
    statuses=None,
    class_ids=None,
    course_lines=None,
    courses=None,
    centres=None,
    search_text="",
    date_field=DEFAULT_DATE_FIELD,
    class_limit=DEFAULT_ITEMS_PER_PAGE,
    workers=DEFAULT_STUDENT_WORKERS,
    auto_login=False,
    force_refresh=False,
):
    output_path = resolve_output_path(output_file)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    end_date = end_date or date.today().isoformat()

    classes = fetch_classes(
        start_date=start_date,
        end_date=end_date,
        statuses=statuses,
        class_ids=class_ids,
        course_lines=course_lines,
        courses=courses,
        centres=centres,
        search_text=search_text,
        date_field=date_field,
        items_per_page=class_limit,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    if not classes:
        print("⚠️ Không có lớp phù hợp với bộ lọc completion.", flush=True)
        return None

    rows = build_completion_rows(classes, workers=workers)
    if not rows:
        print("⚠️ Không có dữ liệu học viên completion phù hợp.", flush=True)
        return None

    with open(output_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"📁 Đã lưu {len(rows)} dòng completion từ {len(classes)} lớp vào '{output_path}'", flush=True)
    return output_path


def build_parser():
    parser = argparse.ArgumentParser(description="Export completion học viên theo class LMS.")
    parser.add_argument("--start", "--start-date", dest="start_date", default=DEFAULT_START_DATE)
    parser.add_argument("--end", "--end-date", dest="end_date", default=date.today().isoformat())
    parser.add_argument("--date-field", choices=["startDate", "endDate"], default=DEFAULT_DATE_FIELD)
    parser.add_argument("--status", action="append", dest="statuses")
    parser.add_argument("--class-id", action="append", dest="class_ids")
    parser.add_argument("--course-line", action="append", dest="course_lines")
    parser.add_argument("--course", action="append", dest="courses")
    parser.add_argument("--centre", "--center", action="append", dest="centres")
    parser.add_argument("--search", default="")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--class-limit", type=int, default=DEFAULT_ITEMS_PER_PAGE)
    parser.add_argument("--workers", type=int, default=DEFAULT_STUDENT_WORKERS)
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    return export_completion_status(
        start_date=args.start_date,
        end_date=args.end_date,
        output_file=args.output,
        statuses=args.statuses or DEFAULT_CLASS_STATUSES,
        class_ids=args.class_ids,
        course_lines=args.course_lines,
        courses=args.courses,
        centres=args.centres,
        search_text=args.search,
        date_field=args.date_field,
        class_limit=args.class_limit,
        workers=args.workers,
        auto_login=args.login,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
