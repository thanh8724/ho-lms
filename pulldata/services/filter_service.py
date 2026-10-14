from __future__ import annotations

from pulldata.legacy import request_module


def load_catalog_options():
    request = request_module()
    return {
        "centres": request.fetch_centre_filter_options(),
        "course_lines": request.fetch_course_line_filter_options(),
        "courses": request.fetch_course_and_line_filter_options(),
    }


def option_values(items):
    values = []
    for item in items or []:
        if isinstance(item, dict):
            value = item.get("value") or item.get("id") or item.get("name")
        else:
            value = item
        if value and value not in values:
            values.append(str(value))
    return values
