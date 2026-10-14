from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from pulldata.auth.service import AuthState
from pulldata.runtime.job_manager import Artifact, Job, JobManager


def test_initial_app_loads():
    at = AppTest.from_file("../app.py", default_timeout=10)
    at.run()
    assert not at.exception, f"App threw exception: {at.exception}"
    # Verify module navigation buttons exist
    sidebar_buttons = [b.label for b in at.sidebar.button]
    assert "Request Teacher" in sidebar_buttons
    assert "Survey" in sidebar_buttons
    assert "Sản phẩm học viên" in sidebar_buttons
    assert "Completion" in sidebar_buttons
    assert "Điểm danh giáo viên" in sidebar_buttons
    assert "Office Hours" in sidebar_buttons
    assert "Class Observe" in sidebar_buttons
    # Verify auth buttons in sidebar expander
    assert "Kiểm tra token" in sidebar_buttons
    assert "Refresh token" in sidebar_buttons
    assert "Đăng xuất session" in sidebar_buttons


def test_all_modules_render():
    modules = [
        "request",
        "survey",
        "products",
        "completion",
        "teacher_attendance",
        "office_hours",
        "class_observe",
    ]
    for mod in modules:
        at = AppTest.from_file("../app.py", default_timeout=10)
        at.run()
        # Find the nav button for this module and click it
        for btn in at.sidebar.button:
            if btn.key == f"nav-{mod}":
                btn.click().run()
                break
        assert not at.exception, f"Module {mod} threw exception: {at.exception}"


def test_authenticated_state_ui():
    at = AppTest.from_file("../app.py", default_timeout=10)
    at.session_state["auth_state"] = AuthState(
        token="mock_valid_token_12345",
        email="developer@mindx.edu.vn",
        expiry="2026-12-31 23:59:59",
    )
    at.run()
    assert not at.exception


def test_job_states_rendering():
    manager = JobManager()

    # 1. Running job
    running_job = Job(id="run123", label="Request Teacher", status="running", started_at="14:00:00")
    running_job.logs.append("Querying GraphQL endpoint...")
    manager._jobs["run123"] = running_job

    at_run = AppTest.from_file("../app.py", default_timeout=10)
    at_run.session_state["job_manager"] = manager
    at_run.session_state["active_job"] = "run123"
    at_run.run()
    assert not at_run.exception

    # 2. Success job with artifacts
    success_job = Job(
        id="succ123",
        label="Request Teacher",
        status="success",
        started_at="14:00:00",
        finished_at="14:00:05",
        artifacts=[Artifact(name="request_teacher.csv", data=b"col1,col2\n1,2\n")],
    )
    manager._jobs["succ123"] = success_job

    at_succ = AppTest.from_file("../app.py", default_timeout=10)
    at_succ.session_state["job_manager"] = manager
    at_succ.session_state["active_job"] = "succ123"
    at_succ.run()
    assert not at_succ.exception

    # 3. Failed job
    failed_job = Job(
        id="fail123",
        label="Request Teacher",
        status="failed",
        started_at="14:00:00",
        error="GraphQLAuthError: Token expired",
    )
    manager._jobs["fail123"] = failed_job

    at_fail = AppTest.from_file("../app.py", default_timeout=10)
    at_fail.session_state["job_manager"] = manager
    at_fail.session_state["active_job"] = "fail123"
    at_fail.run()
    assert not at_fail.exception


def test_form_validation_and_submission():
    at = AppTest.from_file("../app.py", default_timeout=10)
    at.run()
    # Set invalid date range: start after end
    at.date_input(key="request-start").set_value(date(2026, 10, 15))
    at.date_input(key="request-end").set_value(date(2026, 10, 10))
    for b in at.button:
        if b.label == "Xuất dữ liệu":
            b.click().run()
            break
    # Check that error is rendered
    assert len(at.error) > 0, "Expected date validation error"
    assert "Ngày bắt đầu không được sau ngày kết thúc" in at.error[0].value


if __name__ == "__main__":
    test_initial_app_loads()
    test_all_modules_render()
    test_authenticated_state_ui()
    test_job_states_rendering()
    test_form_validation_and_submission()
    print("All enterprise UI tests passed successfully!")

