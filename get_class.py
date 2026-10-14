import argparse
import calendar
import os
import re
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

from lms_auth import build_auth_headers, ensure_auth_token

load_dotenv()

DEFAULT_AUTH_TOKEN = ""
AUTH_TOKEN = (os.getenv("AUTH_TOKEN") or os.getenv("TOKEN") or DEFAULT_AUTH_TOKEN).strip()
AUTH_HEADER_VALUE = AUTH_TOKEN[7:].strip() if AUTH_TOKEN.lower().startswith("bearer ") else AUTH_TOKEN

API_URL = "https://lms-api.mindx.edu.vn/graphql"
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

# === CHỈNH THỜI GIAN Ở ĐÂY ===
# Format ngày: YYYY-MM-DD
START_DATE = "2026-07-13"
END_DATE = "2026-07-19"

CLASS_PREFIXES = ("PXL", "PVT", "TK")
DEFAULT_BLOCKS = ("XART", "C4K", "ROB")
ALWAYS_EXCLUDED_CLASS_KEYWORDS = ("ONL", "1:1", "NG", "WRO")
BLOCK_KEYWORDS = {
    "XART": ("XART", "X-ART", "X ART"),
    "C4K": ("C4K", "CSB", "CSA", "CSI", "JSB", "JSA", "JSI"),
    "ROB": ("ROB", "KIND"),
}
DEFAULT_CLASS_STATUSES = ("PENDING", "OPENING", "RUNNING", "CLOSED")
CLASS_STATUSES = DEFAULT_CLASS_STATUSES
CLASS_STATUS_ALIASES = {
    "PENDING": "PENDING",
    "PEND": "PENDING",
    "OPEN": "OPENING",
    "OPENING": "OPENING",
    "RUN": "RUNNING",
    "RUNNING": "RUNNING",
    "FINISH": "CLOSED",
    "FINISHED": "CLOSED",
    "CLOSE": "CLOSED",
    "CLOSED": "CLOSED",
}
ITEMS_PER_PAGE = 50
MIN_SESSION = 1
MAX_SESSION = 8
EXCLUDED_SESSIONS = {5}

WEEKDAY_LABELS = [
    "Thứ 2",
    "Thứ 3",
    "Thứ 4",
    "Thứ 5",
    "Thứ 6",
    "Thứ 7",
    "Chủ Nhật",
]

EXPORT_COLUMNS = [
    "mã lớp",
    "giáo viên chính",
    "buổi học số mấy",
    "thời gian buổi học",
    "giờ buổi học",
    "thứ mấy",
    "ngày mấy",
    "cơ sở",
]

CSV_HEADERS = {
    "mã lớp": "Mã lớp",
    "giáo viên chính": "Giáo viên chính",
    "buổi học số mấy": "Buổi học số mấy",
    "thời gian buổi học": "Thời gian buổi học",
    "giờ buổi học": "Giờ buổi học",
    "thứ mấy": "Thứ",
    "ngày mấy": "Ngày diễn ra",
    "cơ sở": "Cơ sở",
}


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


def parse_date_value(value, field_name="ngày"):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} phải có format YYYY-MM-DD, ví dụ 2026-07-06") from exc


def resolve_month_range(value):
    try:
        year, month = map(int, value.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
    except Exception as exc:
        raise ValueError("Tháng phải có format YYYY-MM, ví dụ 2026-07") from exc


def resolve_year_range(value):
    try:
        year = int(value)
        if year < 1:
            raise ValueError
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    except ValueError as exc:
        raise ValueError("Năm phải có format YYYY, ví dụ 2026") from exc


def resolve_period_range(args):
    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("Khi dùng --start/--end bạn cần truyền đủ cả hai giá trị")
        start = parse_date_value(args.start, "--start")
        end = parse_date_value(args.end, "--end")
        if start > end:
            raise ValueError("--start không được lớn hơn --end")
        return args.start, args.end, f"{args.start}_to_{args.end}"

    period = args.date or args.month or args.year or args.period
    if not period:
        start = parse_date_value(START_DATE, "START_DATE")
        end = parse_date_value(END_DATE, "END_DATE")
        if start > end:
            raise ValueError("START_DATE không được lớn hơn END_DATE")
        print(f"ℹ️ Dùng thời gian cấu hình trong file: {START_DATE} → {END_DATE}")
        return START_DATE, END_DATE, f"{START_DATE}_to_{END_DATE}"

    period = str(period).strip()
    if args.date or (len(period) == 10 and period.count("-") == 2):
        day = parse_date_value(period)
        return day.isoformat(), day.isoformat(), day.isoformat()
    if args.month or (len(period) == 7 and period.count("-") == 1):
        start_date, end_date = resolve_month_range(period)
        return start_date, end_date, period
    if args.year or (len(period) == 4 and period.isdigit()):
        start_date, end_date = resolve_year_range(period)
        return start_date, end_date, period

    raise ValueError("Không nhận diện được thời gian. Dùng YYYY-MM-DD, YYYY-MM, YYYY hoặc --start/--end.")


def vn_date_range_to_utc(start_date, end_date):
    start_vn = datetime.combine(parse_date_value(start_date, "ngày bắt đầu"), dt_time.min).replace(tzinfo=VN_TZ)
    end_vn = datetime.combine(parse_date_value(end_date, "ngày kết thúc"), dt_time.max).replace(tzinfo=VN_TZ)
    start_utc = start_vn.astimezone(UTC_TZ)
    end_utc = end_vn.astimezone(UTC_TZ)
    return (
        start_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        end_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )


def get_vn_datetime_range(start_date, end_date):
    start = datetime.combine(parse_date_value(start_date, "START_DATE"), dt_time.min).replace(tzinfo=VN_TZ)
    end = datetime.combine(parse_date_value(end_date, "END_DATE"), dt_time.max).replace(tzinfo=VN_TZ)
    return start, end


def parse_api_datetime_to_vn(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(VN_TZ)
    except ValueError:
        return None


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def parse_csv_values(value, upper=False):
    items = [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]
    return tuple(item.upper() if upper else item for item in items)


def parse_status_values(value):
    if value is None:
        return ()
    if isinstance(value, str):
        parts = re.split(r"[\s,;]+", value.strip())
    else:
        parts = value
    return tuple(str(item).strip() for item in parts if str(item).strip())


def normalize_blocks(values=None):
    selected = []
    for value in values or DEFAULT_BLOCKS:
        block = normalize_text(value).upper()
        if block not in DEFAULT_BLOCKS or block in selected:
            continue
        selected.append(block)
    return tuple(selected or DEFAULT_BLOCKS)


def normalize_class_statuses(values=None):
    selected = []
    for value in parse_status_values(values) or DEFAULT_CLASS_STATUSES:
        status = normalize_text(value).upper()
        canonical = CLASS_STATUS_ALIASES.get(status)
        if not canonical or canonical in selected:
            continue
        selected.append(canonical)
    return tuple(selected or DEFAULT_CLASS_STATUSES)


def escape_graphql_string(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def post_graphql(query, timeout=35):
    response = requests.post(API_URL, headers=HEADERS, json={"query": query}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError(payload["errors"])
    return payload


def is_auth_error(error):
    return "Authentication failed" in str(error)


def build_classes_query(page_index, status, search_text, extra_filters=None):
    filters = [
        f"pageIndex: {page_index}",
        f"itemsPerPage: {ITEMS_PER_PAGE}",
        f'status_in: ["{status}"]',
        f'filter_textSearch: "{escape_graphql_string(search_text)}"',
        *(extra_filters or []),
    ]

    return f"""
    {{
      classes(payload: {{ {", ".join(filters)} }}) {{
        data {{
          id
          name
          status
          endDate
          slots {{
            _id
            index
            date
            startTime
            endTime
            sessionHour
            teachers {{
              role {{
                id
                name
                shortName
              }}
              teacher {{
                id
                fullName
                email
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


def fetch_all_classes(start_date, end_date, statuses=None, auto_login=False, force_refresh=False):
    ensure_valid_token(auto_login=auto_login, force_refresh=force_refresh)
    start_utc, _ = vn_date_range_to_utc(start_date, end_date)
    selected_statuses = normalize_class_statuses(statuses)
    print(f"🇻🇳 Khoảng ngày Việt Nam: {start_date} → {end_date}")
    print(f"🏷️ Trạng thái lớp: {', '.join(selected_statuses)}")

    classes = []
    for prefix in CLASS_PREFIXES:
        for status in selected_statuses:
            page_index = 0
            extra_filters = [f'endDate_gt: "{start_utc}"'] if status == "CLOSED" else []

            while True:
                query = build_classes_query(page_index, status, prefix, extra_filters)
                try:
                    payload = post_graphql(query)
                except requests.exceptions.RequestException as exc:
                    print(f"❌ Lỗi request {prefix}/{status} trang {page_index}: {exc}")
                    break
                except ValueError as exc:
                    if is_auth_error(exc):
                        raise ValueError("AUTH_TOKEN đã hết hạn hoặc không hợp lệ. Hãy cập nhật token rồi chạy lại.")
                    print(f"❌ API lỗi {prefix}/{status} trang {page_index}: {exc}")
                    break

                page = payload.get("data", {}).get("classes", {})
                batch = page.get("data") or []
                total = page.get("pagination", {}).get("total", 0)
                classes.extend(batch)
                print(f"✅ {prefix}/{status} trang {page_index}: {len(batch)} lớp")

                if not batch or (total and (page_index + 1) * ITEMS_PER_PAGE >= total):
                    break

                page_index += 1
                time.sleep(0.2)

    return dedupe_classes(classes)


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


def infer_block_from_class_name(class_name):
    upper_name = normalize_text(class_name).upper()
    tokens = re.findall(r"[A-Z0-9]+", upper_name)
    searchable = " ".join(tokens)

    for block, keywords in BLOCK_KEYWORDS.items():
        if any(keyword in upper_name or keyword in searchable for keyword in keywords):
            return block
    return ""


def is_target_class_name(class_name, blocks=None):
    selected_blocks = set(normalize_blocks(blocks))
    upper_name = normalize_text(class_name).upper()
    if not any(upper_name.startswith(prefix) for prefix in CLASS_PREFIXES):
        return False
    if any(keyword in upper_name for keyword in ALWAYS_EXCLUDED_CLASS_KEYWORDS):
        return False
    return infer_block_from_class_name(class_name) in selected_blocks


def get_centre_name(class_name):
    upper_name = normalize_text(class_name).upper()
    for prefix in CLASS_PREFIXES:
        if upper_name.startswith(prefix):
            return prefix
    return ""


def is_lec_role(role):
    role_name = normalize_text(role.get("name")).lower()
    role_short_name = normalize_text(role.get("shortName")).upper()
    return role_short_name == "LEC" or role_name in {"lec", "lecturer"}


def teacher_display_name(teacher):
    return normalize_text(teacher.get("fullName")) or normalize_text(teacher.get("email"))


def get_slot_lec_names(slot):
    names = []
    for entry in slot.get("teachers") or []:
        if not is_lec_role(entry.get("role") or {}):
            continue
        name = teacher_display_name(entry.get("teacher") or {})
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def format_vn_date(dt):
    return dt.strftime("%d/%m/%Y")


def format_vn_time(dt):
    return dt.strftime("%H:%M") if dt else ""


def format_duration_label(slot, start_time, end_time):
    session_hour = slot.get("sessionHour")
    if session_hour not in ("", None):
        try:
            return f"{float(session_hour):g}h"
        except (TypeError, ValueError):
            return str(session_hour)

    if not start_time or not end_time:
        return ""

    minutes = round((end_time - start_time).total_seconds() / 60)
    if minutes <= 0:
        return ""

    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h" if remaining_minutes == 0 else f"{hours}h{remaining_minutes:02d}"


def is_target_session(session_index):
    if not isinstance(session_index, int):
        return False
    return MIN_SESSION <= session_index <= MAX_SESSION and session_index not in EXCLUDED_SESSIONS


def build_lesson_rows(classes, start_date, end_date, blocks=None):
    selected_blocks = normalize_blocks(blocks)
    start_vn, end_vn = get_vn_datetime_range(start_date, end_date)
    rows = []
    seen_slots = set()

    for cls in classes:
        class_name = normalize_text(cls.get("name"))
        if not is_target_class_name(class_name, selected_blocks):
            continue

        for slot in cls.get("slots") or []:
            start_time = parse_api_datetime_to_vn(slot.get("startTime") or slot.get("date"))
            if not start_time or start_time < start_vn or start_time > end_vn:
                continue

            slot_key = slot.get("_id") or f"{cls.get('id')}|{slot.get('startTime')}"
            if slot_key in seen_slots:
                continue
            seen_slots.add(slot_key)

            end_time = parse_api_datetime_to_vn(slot.get("endTime"))
            session_index = slot.get("index")
            if isinstance(session_index, int):
                session_index += 1
            if not is_target_session(session_index):
                continue

            time_label = format_vn_time(start_time)
            if end_time:
                time_label = f"{format_vn_time(start_time)}-{format_vn_time(end_time)}"

            rows.append({
                "mã lớp": class_name,
                "giáo viên chính": get_slot_lec_names(slot),
                "buổi học số mấy": session_index,
                "thời gian buổi học": time_label,
                "giờ buổi học": format_duration_label(slot, start_time, end_time),
                "thứ mấy": WEEKDAY_LABELS[start_time.weekday()],
                "ngày mấy": format_vn_date(start_time),
                "cơ sở": get_centre_name(class_name),
                "_sort_time": start_time,
                "_class_name": class_name,
            })

    rows.sort(key=lambda row: (row["_sort_time"], row["_class_name"], row["buổi học số mấy"] or 0))
    for row in rows:
        row.pop("_sort_time", None)
        row.pop("_class_name", None)
    return rows


def fetch_class_filter_options(
    start_date,
    end_date,
    statuses=None,
    auto_login=False,
    force_refresh=False,
):
    selected_statuses = normalize_class_statuses(statuses)
    classes = fetch_all_classes(
        start_date,
        end_date,
        selected_statuses,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    blocks = set()
    class_options = []
    for cls in classes:
        class_name = normalize_text(cls.get("name"))
        if not class_name or not is_target_class_name(class_name, DEFAULT_BLOCKS):
            continue
        block = infer_block_from_class_name(class_name)
        if block:
            blocks.add(block)
        class_options.append({
            "id": cls.get("id") or class_name,
            "name": class_name,
            "subject": block,
        })
    return {
        "blocks": sorted(blocks),
        "classes": sorted(class_options, key=lambda item: item["name"]),
    }


def filter_classes_by_ids(classes, class_ids=None):
    selected = {str(value).strip() for value in (class_ids or []) if str(value).strip()}
    if not selected:
        return classes
    return [
        cls for cls in classes
        if str(cls.get("id") or cls.get("name") or "").strip() in selected
    ]


def print_rows(rows, start_date, end_date, blocks=None):
    block_text = ", ".join(normalize_blocks(blocks))
    session_text = f"buổi {MIN_SESSION}-{MAX_SESSION}, bỏ buổi {', '.join(map(str, sorted(EXCLUDED_SESSIONS)))}"
    if not rows:
        print(f"⚠️ Không có lớp khối {block_text} nào có {session_text} từ {start_date} đến {end_date}")
        return

    print(f"\n📚 Danh sách buổi học lớp khối {block_text} ({session_text}) từ {start_date} đến {end_date}")
    for index, row in enumerate(rows, start=1):
        print(
            f"{index}. {row['mã lớp']} | LEC: {row['giáo viên chính']} | "
            f"Buổi {row['buổi học số mấy']} | {row['thứ mấy']} {row['ngày mấy']} | "
            f"{row['thời gian buổi học']} | {row['giờ buổi học']}"
        )

    unique_classes = {row["mã lớp"] for row in rows}
    print(f"\nTổng: {len(rows)} buổi học / {len(unique_classes)} lớp")


def build_output_path(label, blocks=None, output_file=None):
    if output_file:
        return output_file
    block_label = "_".join(normalize_blocks(blocks)).lower()
    return f"class_observe_{block_label}_{label}_VN.csv"


def export_lessons(
    start_date,
    end_date,
    label=None,
    blocks=None,
    class_ids=None,
    output_file=None,
    statuses=None,
    auto_login=False,
    force_refresh=False,
):
    selected_blocks = normalize_blocks(blocks)
    selected_statuses = normalize_class_statuses(statuses)
    classes = fetch_all_classes(
        start_date,
        end_date,
        selected_statuses,
        auto_login=auto_login,
        force_refresh=force_refresh,
    )
    classes = filter_classes_by_ids(classes, class_ids)
    rows = build_lesson_rows(classes, start_date, end_date, selected_blocks)

    if not rows:
        block_text = ", ".join(selected_blocks)
        status_text = ", ".join(selected_statuses)
        excluded = ", ".join(map(str, sorted(EXCLUDED_SESSIONS)))
        print(
            f"⚠️ Không có lớp khối {block_text}, trạng thái {status_text} "
            f"nào có buổi {MIN_SESSION}-{MAX_SESSION}, bỏ buổi {excluded}"
        )
        return None

    print_rows(rows, start_date, end_date, selected_blocks)

    output_label = label or f"{start_date}_to_{end_date}"
    output_file = build_output_path(output_label, selected_blocks, output_file)
    df = pd.DataFrame(rows)
    df = df.reindex(columns=EXPORT_COLUMNS).rename(columns=CSV_HEADERS)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")

    print(f"\n📁 Đã lưu {len(df)} buổi học vào '{output_file}'")
    return df


def build_parser():
    parser = argparse.ArgumentParser(
        description="Xuất buổi học lớp PXL, PVT, TK với giáo viên role LEC theo từng buổi."
    )
    parser.add_argument("period", nargs="?", help="YYYY-MM-DD, YYYY-MM hoặc YYYY")
    parser.add_argument("--date", help="Lấy theo một ngày, format YYYY-MM-DD")
    parser.add_argument("--month", help="Lấy theo một tháng, format YYYY-MM")
    parser.add_argument("--year", help="Lấy theo một năm, format YYYY")
    parser.add_argument("--start", help="Ngày bắt đầu, format YYYY-MM-DD")
    parser.add_argument("--end", help="Ngày kết thúc, format YYYY-MM-DD")
    parser.add_argument("--blocks", default=",".join(DEFAULT_BLOCKS), help="Khối cần lấy: XART,C4K,ROB")
    parser.add_argument("--class-id", action="append", dest="class_ids", default=None, help="Lọc theo class id từ LMS")
    parser.add_argument(
        "--statuses",
        default=",".join(DEFAULT_CLASS_STATUSES),
        help="Trạng thái lớp, ví dụ pending,open,running,finish",
    )
    parser.add_argument("--output", help="Tên file CSV output")
    parser.add_argument("--login", action="store_true", help="Mở web LMS để đăng nhập/lấy token nếu cache chưa có")
    parser.add_argument("--force-refresh", action="store_true", help="Bỏ qua id token hiện tại và refresh/lấy token mới")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        start_date, end_date, label = resolve_period_range(args)
        export_lessons(
            start_date,
            end_date,
            label,
            blocks=parse_csv_values(args.blocks, upper=True),
            class_ids=args.class_ids,
            output_file=args.output,
            statuses=parse_status_values(args.statuses),
            auto_login=args.login,
            force_refresh=args.force_refresh,
        )
    except Exception as exc:
        print(f"❌ {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
