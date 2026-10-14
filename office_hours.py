"""Export Office Hours data from MindX LMS."""

from __future__ import annotations

import os
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

from lms_auth import LMS_API_URL, LMS_GRAPHQL_URL, build_auth_headers, ensure_auth_token

load_dotenv()

API_ROOT_URL = f"{LMS_API_URL.rstrip('/')}/"
API_URL = LMS_GRAPHQL_URL
GRAPHQL_URLS = (API_ROOT_URL, API_URL)

DEFAULT_START_DATE = os.getenv("OFFICE_HOURS_START_DATE", "2026-07-01")
DEFAULT_END_DATE = os.getenv("OFFICE_HOURS_END_DATE", "2026-07-31")
DEFAULT_OUTPUT_FILE = "office_hours.csv"
DEFAULT_OFFICE_HOUR_TYPES = ("Trial", "Fixed")
DEFAULT_ITEMS_PER_PAGE = int(os.getenv("OFFICE_HOURS_ITEMS_PER_PAGE", "100"))
LOCAL_TZ_NAME = os.getenv("OFFICE_HOURS_TIMEZONE", "Asia/Ho_Chi_Minh")
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)
UTC_TZ = ZoneInfo("UTC")

OUTPUT_COLUMNS = [
    "officeHourId",
    "type",
    "appointmentId",
    "startTime",
    "officeHourStatus",
    "centreName",
    "centreShortName",
    "courseLineName",
    "candidateName",
    "candidateStatus",
    "leadId",
    "teacherName",
    "teacherCode",
    "teacherEmail",
    "appointmentCourseLineNames",
    "Course Lines",
]


def parse_csv_values(value, *, upper: bool = False) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\n", ",").split(",")
    items = [str(item).strip() for item in raw_items if str(item).strip()]
    return [item.upper() for item in items] if upper else items


def to_utc_iso(value, end_of_day: bool = False) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if "T" in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed_date = datetime.strptime(text, "%Y-%m-%d").date()
            local_time = dt_time(23, 59, 59, 999000) if end_of_day else dt_time(0, 0, 0)
            dt = datetime.combine(parsed_date, local_time)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)

    return dt.astimezone(UTC_TZ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def raise_for_graphql_errors(res_json: dict, context: str) -> None:
    errors = res_json.get("errors") or []
    if not errors:
        return

    messages = []
    for error in errors[:3]:
        if isinstance(error, dict):
            messages.append(error.get("message") or str(error))
        else:
            messages.append(str(error))

    raise RuntimeError(f"API trả về lỗi GraphQL ({context}): " + " | ".join(messages))


def post_lms_graphql(payload: dict, context: str, token: str, timeout: int = 30, urls=None) -> dict:
    if not token:
        raise RuntimeError("Thiếu token LMS. Hãy đăng nhập LMS trong app trước khi chạy.")

    last_error = None
    for url in (urls or GRAPHQL_URLS):
        try:
            response = requests.post(url, headers=build_auth_headers(token), json=payload, timeout=timeout)
            response.raise_for_status()
            res_json = response.json()
            raise_for_graphql_errors(res_json, context)
            return res_json
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Không gọi được LMS API ({context}): {last_error}")


def build_payload(
    page_index: int,
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    centre_ids=None,
    office_hour_types=None,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
) -> dict:
    query_payload = {
        "pageIndex": page_index,
        "itemsPerPage": items_per_page,
        "orderBy": "createdAt_asc",
        "timeFrom": to_utc_iso(start_date),
        "timeTo": to_utc_iso(end_date, end_of_day=True),
        "paginationType": "OFFSET",
    }

    selected_centres = parse_csv_values(centre_ids)
    if selected_centres:
        query_payload["centreIn"] = selected_centres

    selected_types = parse_csv_values(office_hour_types or DEFAULT_OFFICE_HOUR_TYPES)
    if selected_types:
        query_payload["typeEquals"] = selected_types

    return {
        "operationName": "GetOfficeHours",
        "variables": {"payload": query_payload},
        "query": """
        query GetOfficeHours($payload: OfficeHourQuery) {
          officeHours(payload: $payload) {
            data {
              id
              type
              status
              startTime
              centre { id name shortName }
              teacher { code fullName email }
              courseLines { id name }
              appointments {
                id
                status
                candidate { id fullName }
              }
            }
            pagination { type total }
          }
        }
        """,
    }


def appointment_course_key(index: int, appointment: dict) -> str:
    return appointment.get("id") or f"index:{index}"


def format_appointment_course_line(appointment: dict) -> str:
    courses = appointment.get("courses") or []
    if not courses:
        return ""
    return (courses[0].get("shortName") or "").strip()


def format_appointment_course_line_names(appointment: dict) -> str:
    courses = appointment.get("courses") or []
    names = []
    for course in courses:
        name = (course.get("shortName") or course.get("name") or "").strip()
        if name and name not in names:
            names.append(name)

    return "; ".join(names) or "N/A"


def build_appointment_course_lines_map(appointments) -> dict:
    return {
        appointment_course_key(index, appointment): {
            "appointmentCourseLineNames": format_appointment_course_line_names(appointment),
            "Course Lines": format_appointment_course_line(appointment),
        }
        for index, appointment in enumerate(appointments or [])
    }


def build_office_hour_appointment_courses_batch_payload(office_hour_ids) -> dict:
    unique_ids = [office_hour_id for office_hour_id in dict.fromkeys(office_hour_ids) if office_hour_id]
    variable_defs = ", ".join([f"$id{idx}: ID!" for idx, _ in enumerate(unique_ids)])
    variables = {f"id{idx}": office_hour_id for idx, office_hour_id in enumerate(unique_ids)}
    selections = []

    for idx, _ in enumerate(unique_ids):
        selections.append(
            f"""
          officeHour{idx}: officeHoursById(id: $id{idx}) {{
            id
            appointments {{
              id
              courses {{
                id
                name
                shortName
                __typename
              }}
              __typename
            }}
          }}"""
        )

    return {
        "operationName": "GetOficeHourById",
        "variables": variables,
        "query": f"""
        query GetOficeHourById({variable_defs}) {{
{''.join(selections)}
        }}
        """,
    }


def fetch_appointment_course_lines_by_office_hour_ids(
    office_hour_ids,
    *,
    token: str,
    cache: dict | None = None,
    fallback_by_id: dict | None = None,
    batch_size: int = 20,
) -> dict:
    fallback_by_id = fallback_by_id or {}
    result = {}
    pending_ids = []

    for office_hour_id in dict.fromkeys([office_hour_id for office_hour_id in office_hour_ids if office_hour_id]):
        if cache is not None and office_hour_id in cache:
            result[office_hour_id] = cache[office_hour_id]
        else:
            result[office_hour_id] = dict(fallback_by_id.get(office_hour_id, {}))
            pending_ids.append(office_hour_id)

    for start in range(0, len(pending_ids), batch_size):
        batch_ids = pending_ids[start:start + batch_size]
        last_error = None
        fetched = False

        try:
            res_json = post_lms_graphql(
                build_office_hour_appointment_courses_batch_payload(batch_ids),
                context=f"officeHoursById batch {start // batch_size + 1}",
                token=token,
                timeout=30,
                urls=[API_URL],
            )
            data = res_json.get("data") or {}

            for office_hour in data.values():
                if not office_hour:
                    continue

                office_hour_id = office_hour.get("id")
                if not office_hour_id:
                    continue

                detail_lines = build_appointment_course_lines_map(office_hour.get("appointments"))
                merged_lines = dict(result.get(office_hour_id, {}))
                merged_lines.update({key: value for key, value in detail_lines.items() if value})
                result[office_hour_id] = merged_lines

            fetched = True
        except Exception as exc:
            last_error = exc

        if not fetched and last_error:
            print(f"⚠️ Không lấy được Course Lines chi tiết cho {len(batch_ids)} office hours: {last_error}")

        if cache is not None:
            for office_hour_id in batch_ids:
                cache[office_hour_id] = dict(result.get(office_hour_id, fallback_by_id.get(office_hour_id, {})))

        time.sleep(0.1)

    return result


def value_or_na(value) -> str:
    if value is None:
        return "N/A"
    text = str(value).strip()
    return text or "N/A"


def join_named_values(values, field_name: str = "name") -> str:
    names = []
    for value in values or []:
        name = str((value or {}).get(field_name) or "").strip()
        if name and name not in names:
            names.append(name)
    return "; ".join(names) or "N/A"


def format_local_start_time(value) -> str:
    if not value:
        return "N/A"

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return value_or_na(value)


def fetch_all_office_hours(
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    centre_ids=None,
    office_hour_types=None,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
    auto_login: bool = False,
    force_refresh: bool = False,
) -> list[dict]:
    token = ensure_auth_token(auto_login=auto_login, force_refresh=force_refresh)
    rows_out = []
    page_index = 0
    appointment_course_lines_cache = {}
    selected_types = parse_csv_values(office_hour_types or DEFAULT_OFFICE_HOUR_TYPES)
    allowed_types = {str(type_name).strip().upper() for type_name in selected_types}
    selected_centres = parse_csv_values(centre_ids)
    centre_label = "toàn bộ BU" if not selected_centres else f"{len(selected_centres)} BU/centre"
    type_label = "toàn bộ type" if not selected_types else "; ".join(selected_types)
    print(f"🔎 Query office hours: {start_date} → {end_date} ({LOCAL_TZ_NAME}) | {centre_label} | {type_label}")

    while True:
        payload = build_payload(
            page_index,
            start_date=start_date,
            end_date=end_date,
            centre_ids=selected_centres,
            office_hour_types=selected_types,
            items_per_page=items_per_page,
        )
        res_json = post_lms_graphql(payload, context=f"officeHours page {page_index}", token=token, timeout=30)

        data_section = ((res_json.get("data") or {}).get("officeHours") or {})
        items = data_section.get("data") or []
        total = (data_section.get("pagination") or {}).get("total", 0)

        if not items:
            print(f"✅ Hoàn tất: tổng cộng {len(rows_out)} dòng (pageIndex={page_index})")
            break

        items = [
            item for item in items
            if not allowed_types or str(item.get("type") or "").strip().upper() in allowed_types
        ]

        fallback_appointment_course_lines_by_id = {
            item.get("id"): build_appointment_course_lines_map(item.get("appointments"))
            for item in items
            if item.get("id")
        }
        appointment_course_lines_by_id = fetch_appointment_course_lines_by_office_hour_ids(
            [item.get("id") for item in items if item.get("appointments")],
            token=token,
            cache=appointment_course_lines_cache,
            fallback_by_id=fallback_appointment_course_lines_by_id,
        )

        for item in items:
            centre = item.get("centre") or {}
            teacher = item.get("teacher") or {}
            appointments = item.get("appointments") or []
            appointment_lines = appointment_course_lines_by_id.get(
                item.get("id"),
                fallback_appointment_course_lines_by_id.get(item.get("id"), {}),
            )
            base_row = {
                "officeHourId": value_or_na(item.get("id")),
                "type": value_or_na(item.get("type")),
                "startTime": format_local_start_time(item.get("startTime")),
                "officeHourStatus": value_or_na(item.get("status")),
                "centreName": value_or_na(centre.get("name")),
                "centreShortName": value_or_na(centre.get("shortName")),
                "courseLineName": join_named_values(item.get("courseLines")),
                "teacherName": value_or_na(teacher.get("fullName")),
                "teacherCode": value_or_na(teacher.get("code")),
                "teacherEmail": value_or_na(teacher.get("email")),
            }

            if not appointments:
                rows_out.append({
                    **base_row,
                    "appointmentId": "N/A",
                    "candidateName": "N/A",
                    "candidateStatus": "N/A",
                    "leadId": "N/A",
                    "appointmentCourseLineNames": "N/A",
                    "Course Lines": "",
                })
                continue

            for appointment_index, appointment in enumerate(appointments):
                candidate = appointment.get("candidate") or {}
                appointment_values = appointment_lines.get(
                    appointment_course_key(appointment_index, appointment),
                    {},
                ) or {}
                rows_out.append({
                    **base_row,
                    "appointmentId": value_or_na(appointment.get("id")),
                    "candidateName": value_or_na(candidate.get("fullName")),
                    "candidateStatus": value_or_na(appointment.get("status")),
                    "leadId": value_or_na(candidate.get("id")),
                    "appointmentCourseLineNames": appointment_values.get("appointmentCourseLineNames", "N/A"),
                    "Course Lines": appointment_values.get("Course Lines") or format_appointment_course_line(appointment),
                })

        print(f"📄 Trang {page_index}: lấy {len(items)} records | Tổng đã lấy: {len(rows_out)} / {total}")
        page_index += 1
        time.sleep(0.3)

    return rows_out


def export_office_hours(
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output_file: str | Path | None = None,
    centre_ids=None,
    office_hour_types=None,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
    auto_login: bool = False,
    force_refresh: bool = False,
) -> str | None:
    rows = fetch_all_office_hours(
        start_date=start_date,
        end_date=end_date,
        centre_ids=centre_ids,
        office_hour_types=office_hour_types,
        items_per_page=items_per_page,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    if not rows:
        print("⚠️ Không có dữ liệu office hours.")
        return None

    output_path = Path(output_file or DEFAULT_OUTPUT_FILE).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"📁 Đã lưu {len(df)} dòng vào {output_path}")
    return str(output_path)


if __name__ == "__main__":
    export_office_hours()
