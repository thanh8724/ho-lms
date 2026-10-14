from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def load_module(filename: str, module_name: str | None = None) -> ModuleType:
    path = ROOT / filename
    name = module_name or path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Không thể tải module nghiệp vụ: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request_module():
    return load_module("requestTC_fetch.py", "pulldata_request")


def survey_module():
    return load_module("export_survey.py", "pulldata_survey")


def products_module():
    return load_module("getproductb12-13.py", "pulldata_products")


def completion_module():
    return load_module("completion_export.py", "pulldata_completion")


def attendance_module():
    return load_module("teacher_attendance_export.py", "pulldata_teacher_attendance")


def office_hours_module():
    return load_module("office_hours.py", "pulldata_office_hours")


def class_observe_module():
    return load_module("get_class.py", "pulldata_class_observe")
