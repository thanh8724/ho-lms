from __future__ import annotations

from datetime import date
from pathlib import Path

from pulldata.legacy import (
    attendance_module,
    class_observe_module,
    completion_module,
    office_hours_module,
    products_module,
    request_module,
    survey_module,
)


def _iso(value):
    return value.isoformat() if isinstance(value, date) else str(value)


def export(module_name: str, values: dict, output_dir: Path):
    start, end = _iso(values["start"]), _iso(values["end"])
    output_dir.mkdir(parents=True, exist_ok=True)

    if module_name == "request":
        path = output_dir / "request_teacher.csv"
        request_module().export_request_teachers_by_date(
            start_date=start, end_date=end, output_file=str(path),
            course_lines=values.get("course_lines"), courses=values.get("courses"),
            centres=values.get("centres"), class_ids=values.get("class_ids"),
            date_field=values.get("date_field", "startDate"),
            request_types=values.get("request_types"),
            statuses=values.get("request_statuses"),
            is_satisfied=values.get("satisfaction"),
            text_search=values.get("search", ""),
            auto_login=False, force_refresh=False,
        )
        return [path], str(path)

    if module_name == "survey":
        path = output_dir / "response_survey.csv"
        result = survey_module().export_survey(
            output_file=str(path), question_ids=values.get("question_ids"),
            survey_ids=values.get("survey_ids"), centres=values.get("centres"),
            class_ids=values.get("class_ids"), course_lines=values.get("course_lines"),
            courses=values.get("courses"), submitted_from=start, submitted_to=end,
            auto_login=False, force_refresh=False,
        )
        if not result:
            raise ValueError("Không có dữ liệu Survey phù hợp với bộ lọc đã chọn.")
        return [path], str(path)

    if module_name == "products":
        detail = output_dir / "student_products_detail.csv"
        summary = output_dir / "student_products_summary.csv"
        product = products_module()
        product.export_products(
            product.parse_vn_date(start), product.parse_vn_date(end),
            values.get("sessions") or product.DEFAULT_SESSION_NUMBERS,
            values.get("statuses") or product.DEFAULT_CLASS_STATUSES,
            output=str(detail), summary_output=str(summary),
            class_ids=values.get("class_ids"), search_text=values.get("search", ""),
            course_lines=values.get("course_lines"), courses=values.get("courses"),
            centres=values.get("centres"), auto_login=False, force_refresh=False,
        )
        return [detail, summary], "Hai file sản phẩm đã sẵn sàng."

    if module_name == "completion":
        path = output_dir / "students_completion_status.csv"
        completion_module().export_completion_status(
            start_date=start, end_date=end, output_file=str(path),
            statuses=values.get("statuses"), class_ids=values.get("class_ids"),
            course_lines=values.get("course_lines"), courses=values.get("courses"),
            centres=values.get("centres"), search_text=values.get("search", ""),
            date_field=values.get("date_field", "startDate"), auto_login=False,
            force_refresh=False,
        )
        return [path], str(path)

    if module_name == "teacher_attendance":
        path = output_dir / "teacher_attendance.csv"
        attendance_module().export_teacher_attendance(
            start_date=start, end_date=end, output_file=str(path),
            sessions=values.get("sessions"), statuses=values.get("statuses"),
            class_ids=values.get("class_ids"), course_lines=values.get("course_lines"),
            courses=values.get("courses"), centres=values.get("centres"),
            search_text=values.get("search", ""), auto_login=False, force_refresh=False,
        )
        return [path], str(path)

    if module_name == "office_hours":
        path = output_dir / "office_hours.csv"
        office_hours_module().export_office_hours(
            start_date=start, end_date=end, output_file=str(path),
            centre_ids=values.get("centres"), office_hour_types=values.get("types"),
            auto_login=False, force_refresh=False,
        )
        return [path], str(path)

    if module_name == "class_observe":
        path = output_dir / "class_observe.csv"
        observer = class_observe_module()
        observer.export_lessons(
            start_date=start, end_date=end, label=f"{start}_to_{end}",
            blocks=values.get("blocks"), class_ids=values.get("class_ids"),
            output_file=str(path), statuses=values.get("statuses"),
            auto_login=False, force_refresh=False,
        )
        return [path], str(path)

    raise ValueError(f"Module không được hỗ trợ: {module_name}")
