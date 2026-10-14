from __future__ import annotations

import os
from datetime import date, datetime

import streamlit as st

from pulldata.bootstrap import configure_from_streamlit_secrets

configure_from_streamlit_secrets()

from pulldata.auth.service import AuthService  # noqa: E402
from pulldata.legacy import (  # noqa: E402
    attendance_module,
    class_observe_module,
    completion_module,
    office_hours_module,
    products_module,
    request_module,
    survey_module,
)
from pulldata.runtime.job_manager import manager  # noqa: E402
from pulldata.services.export_service import export  # noqa: E402
from pulldata.services.filter_service import load_catalog_options, option_values  # noqa: E402
from ui.layout import render_job  # noqa: E402
from ui.components import (  # noqa: E402
    render_context_panel,
    render_summary_cards,
    render_workflow,
    workflow_step_for_job,
)
from ui.theme import inject_app_css, render_header  # noqa: E402


st.set_page_config(
    page_title="Ho PullData – Enterprise Workspace",
    page_icon=":material/database:",
    layout="wide",
    initial_sidebar_state="expanded",
)

MODULES = {
    "request": ("Request Teacher", "VẬN HÀNH LỚP HỌC", "Xuất yêu cầu giáo viên theo thời gian, trung tâm và trạng thái.", "request_teacher.csv"),
    "survey": ("Survey", "PHẢN HỒI HỌC VIÊN", "Xuất dữ liệu khảo sát theo bộ câu hỏi đã cấu hình.", "response_survey.csv"),
    "products": ("Sản phẩm học viên", "KẾT QUẢ HỌC TẬP", "Xuất dữ liệu sản phẩm học viên theo ngày và buổi học.", "student_products_detail.csv"),
    "completion": ("Completion", "HOÀN THÀNH KHÓA HỌC", "Xuất trạng thái completion của học viên theo lớp.", "students_completion_status.csv"),
    "teacher_attendance": ("Điểm danh giáo viên", "VẬN HÀNH LỚP HỌC", "Xuất trạng thái điểm danh giáo viên theo từng buổi.", "teacher_attendance.csv"),
    "office_hours": ("Office Hours", "LỊCH TƯ VẤN", "Xuất lịch office hour theo ngày, cơ sở và loại.", "office_hours.csv"),
    "class_observe": ("Class Observe", "QUAN SÁT LỚP HỌC", "Xuất danh sách buổi học theo khối lớp.", "class_observe.csv"),
}

THEME_MODES = ("auto", "dark", "light")
THEME_LABELS = {"auto": "Theo hệ thống", "dark": "Tối (Enterprise)", "light": "Sáng"}

MODULE_ICONS = {
    "request": ":material/support_agent:",
    "survey": ":material/feedback:",
    "products": ":material/school:",
    "completion": ":material/task_alt:",
    "teacher_attendance": ":material/event_available:",
    "office_hours": ":material/calendar_month:",
    "class_observe": ":material/visibility:",
}


def state(key, default):
    return st.session_state.setdefault(key, default)


def csv_values(value, upper=False):
    values = [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]
    return [item.upper() if upper else item for item in values]


def default_dates(module_name):
    if module_name == "products":
        module = products_module()
        return date.fromisoformat(module.DEFAULT_START_DATE), module.get_today_vn()
    if module_name == "survey":
        module = survey_module()
        return date.fromisoformat(module.DEFAULT_SUBMITTED_FROM), date.today()
    if module_name == "completion":
        module = completion_module()
        return date.fromisoformat(module.DEFAULT_START_DATE), date.today()
    if module_name == "teacher_attendance":
        module = attendance_module()
        return date.fromisoformat(module.DEFAULT_START_DATE), date.today()
    if module_name == "office_hours":
        module = office_hours_module()
        return date.fromisoformat(module.DEFAULT_START_DATE), date.fromisoformat(module.DEFAULT_END_DATE)
    if module_name == "class_observe":
        module = class_observe_module()
        return date.fromisoformat(module.START_DATE), date.fromisoformat(module.END_DATE)
    module = request_module()
    return date.fromisoformat(module.DEFAULT_START_DATE), date.today()


def sidebar(module_name: str, auth: AuthService) -> str:
    st.sidebar.markdown(
        """
        <div class="ho-brand">
          <div class="ho-brand-icon">H</div>
          <div class="ho-brand-text">
            <div class="ho-brand-title">Ho PullData <span class="ho-brand-badge">SaaS</span></div>
            <div class="ho-brand-subtitle">LMS Data Export Workspace</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown('<div class="ho-sidebar-group">Không gian làm việc</div>', unsafe_allow_html=True)
    selected = module_name
    for key, metadata in MODULES.items():
        is_active = (key == module_name)
        if st.sidebar.button(
            metadata[0],
            icon=MODULE_ICONS[key],
            type="primary" if is_active else "secondary",
            width="stretch",
            key=f"nav-{key}",
        ):
            st.session_state.module = key
            st.rerun()

    st.sidebar.markdown('<div class="ho-sidebar-group">Quản trị</div>', unsafe_allow_html=True)

    with st.sidebar.expander("Cài đặt giao diện", expanded=False):
        st.session_state.theme_mode = st.selectbox(
            "Chế độ màu",
            THEME_MODES,
            index=THEME_MODES.index(st.session_state.get("theme_mode", "auto")),
            format_func=lambda value: THEME_LABELS[value],
            key="theme-mode-setting",
        )
        st.session_state.ui_density = st.selectbox(
            "Mật độ bố cục",
            ("comfortable", "compact"),
            index=0 if st.session_state.get("ui_density", "comfortable") == "comfortable" else 1,
            format_func=lambda value: "Thoáng" if value == "comfortable" else "Gọn",
            key="ui-density-setting",
        )
        st.caption("Giao diện tối ưu hóa cho màn hình laptop & máy trạm dữ liệu.")

    with st.sidebar.expander("Kết nối LMS", expanded=False):
        current = auth.state
        if current.token:
            st.success(f"Đã kết nối LMS\n\n{current.email or 'Tài khoản hiện tại'}")
            st.caption(f"Token hết hạn: {current.expiry or 'không rõ'}")
        else:
            st.warning("Chưa kết nối LMS")
            st.caption("Cấu hình token trong Secrets hoặc biến môi trường.")

        if st.button("Kiểm tra token", icon=":material/verified_user:", width="stretch", key="auth-check-btn"):
            try:
                auth.check()
                st.toast("Token LMS hợp lệ", icon="✅")
            except Exception as exc:
                st.error(str(exc))

        if st.button("Refresh token", icon=":material/refresh:", width="stretch", key="auth-refresh-btn"):
            try:
                auth.check(force_refresh=True)
                st.toast("Đã refresh token thành công", icon="✅")
            except Exception as exc:
                st.error(str(exc))

        if st.button("Đăng xuất session", icon=":material/logout:", width="stretch", key="auth-logout-btn"):
            auth.logout()
            st.rerun()

    st.sidebar.markdown(
        f"""
        <div class="ho-sidebar-footer">
          <div class="ho-footer-tag">Không gian làm việc</div>
          <div class="ho-footer-status">
            <span class="ho-dot {'ho-dot-success' if auth.state.token else 'ho-dot-warning'}"></span>
            <span>{'LMS Sẵn sàng' if auth.state.token else 'Chưa kết nối LMS'}</span>
          </div>
          <div style="color:var(--ho-muted);font-size:0.72rem;margin-top:0.35rem;">Ho PullData Enterprise · v2.0</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return selected


def catalog_options(auth: AuthService, module_name: str):
    catalogs = state("catalogs", {})
    has_catalogs = bool(
        catalogs
        and (catalogs.get("course_lines") or catalogs.get("centres") or catalogs.get("courses"))
    )

    col_info, col_btn = st.columns([3.2, 1.2], gap="small")
    with col_info:
        if not has_catalogs:
            st.markdown(
                """
                <div class="ho-catalog-banner">
                  <div class="ho-catalog-banner-info">
                    <div class="ho-catalog-icon">ℹ️</div>
                    <div>
                      <div class="ho-catalog-text"><strong>Chưa tải danh mục lọc LMS</strong></div>
                      <div class="ho-catalog-sub">Tải danh mục để lọc chính xác theo Course line, Course và Cơ sở từ API.</div>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            c_lines = len(option_values(catalogs.get("course_lines")))
            c_courses = len(option_values((catalogs.get("courses") or {}).get("courses")))
            c_centres = len(option_values(catalogs.get("centres")))
            st.markdown(
                f"""
                <div class="ho-catalog-banner">
                  <div class="ho-catalog-banner-info">
                    <div class="ho-catalog-icon" style="color:var(--ho-success);">✓</div>
                    <div>
                      <div class="ho-catalog-text"><strong>Đã đồng bộ danh mục LMS</strong></div>
                      <div class="ho-catalog-sub">{c_lines} Course lines · {c_courses} Courses · {c_centres} Cơ sở</div>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col_btn:
        btn_label = "Tải bộ lọc LMS" if not has_catalogs else "Làm mới bộ lọc"
        btn_icon = ":material/cloud_download:" if not has_catalogs else ":material/refresh:"
        if st.button(btn_label, icon=btn_icon, width="stretch", key=f"catalog-btn-{module_name}"):
            try:
                with st.spinner("Đang tải danh mục từ LMS..."):
                    auth.ensure_token()
                    st.session_state.catalogs = load_catalog_options()
                st.toast("Đã tải bộ lọc LMS thành công", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Không tải được bộ lọc: {exc}")

    catalogs = st.session_state.get("catalogs", {})
    return (
        option_values(catalogs.get("course_lines")),
        option_values((catalogs.get("courses") or {}).get("courses")),
        option_values(catalogs.get("centres")),
    )


def common_fields(
    module_name: str,
    start: date,
    end: date,
    *,
    sessions=None,
    statuses=None,
    blocks=None,
    date_fields=None,
    office_types=None,
):
    course_lines, courses, centres = catalog_options(st.session_state.auth_service, module_name)

    with st.form(f"filters-{module_name}", border=True):
        st.markdown(
            """
            <div class="ho-form-header">
              <div class="ho-form-title">Bộ lọc dữ liệu</div>
              <div class="ho-form-subtitle">Cấu hình phạm vi thời gian, danh mục học thuật và tiêu chí trích xuất</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="ho-form-section-title"><span class="ho-section-num">A</span> Khoảng thời gian & Tiêu chí ngày</div>',
            unsafe_allow_html=True,
        )

        selected_date_field = date_fields[0][0] if date_fields else None
        if date_fields:
            d1, d2, d3 = st.columns(3)
            with d1:
                selected_start = st.date_input("Từ ngày", start, key=f"{module_name}-start")
            with d2:
                selected_end = st.date_input("Đến ngày", end, key=f"{module_name}-end")
            with d3:
                selected_date_field = st.selectbox(
                    "Lọc theo trường ngày",
                    [item[0] for item in date_fields],
                    format_func=lambda value: dict(date_fields)[value],
                    key=f"{module_name}-date-field",
                )
        else:
            d1, d2 = st.columns(2)
            with d1:
                selected_start = st.date_input("Từ ngày", start, key=f"{module_name}-start")
            with d2:
                selected_end = st.date_input("Đến ngày", end, key=f"{module_name}-end")

        if selected_start > selected_end:
            st.error("Ngày bắt đầu không được sau ngày kết thúc.", icon=":material/warning:")

        st.markdown(
            '<div class="ho-form-section-title"><span class="ho-section-num">B</span> Điều kiện danh mục LMS</div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            selected_lines = st.multiselect("Course line", course_lines, key=f"{module_name}-lines")
        with c2:
            selected_courses = st.multiselect("Course", courses, key=f"{module_name}-courses")
        with c3:
            selected_centres = st.multiselect("Cơ sở", centres, key=f"{module_name}-centres")

        st.markdown(
            '<div class="ho-form-section-title"><span class="ho-section-num">C</span> Thông tin lớp & Tiêu chí bổ sung</div>',
            unsafe_allow_html=True,
        )

        selected_sessions = []
        selected_statuses = []
        selected_blocks = []
        selected_office_types = []

        extra_cols = []
        if sessions:
            extra_cols.append("sessions")
        if statuses:
            extra_cols.append("statuses")
        if blocks:
            extra_cols.append("blocks")
        if office_types:
            extra_cols.append("office_types")

        if extra_cols:
            cols = st.columns(len(extra_cols))
            col_idx = 0
            if sessions:
                with cols[col_idx]:
                    selected_sessions = st.multiselect(
                        "Buổi học",
                        list(range(1, sessions[0] + 1)),
                        default=sessions[1],
                        key=f"{module_name}-sessions",
                    )
                col_idx += 1
            if statuses:
                with cols[col_idx]:
                    selected_statuses = st.multiselect(
                        "Trạng thái lớp",
                        statuses[0],
                        default=statuses[1],
                        key=f"{module_name}-statuses",
                    )
                col_idx += 1
            if blocks:
                with cols[col_idx]:
                    selected_blocks = st.multiselect(
                        "Khối lớp",
                        blocks[0],
                        default=blocks[1],
                        key=f"{module_name}-blocks",
                    )
                col_idx += 1
            if office_types:
                with cols[col_idx]:
                    selected_office_types = st.multiselect(
                        "Loại office hour",
                        office_types,
                        default=list(office_types),
                        key=f"{module_name}-office-types",
                    )
                col_idx += 1

        cl1, cl2 = st.columns(2)
        with cl1:
            class_ids = st.text_input(
                "Mã lớp",
                placeholder="Để trống để lấy tất cả; phân cách bằng dấu phẩy",
                key=f"{module_name}-classids",
                help="Nhập các mã lớp LMS cụ thể, phân cách bằng dấu phẩy",
            )
        with cl2:
            search = st.text_input(
                "Tìm kiếm lớp",
                placeholder="Nhập từ khóa tìm kiếm lớp...",
                key=f"{module_name}-search",
                help="Tìm kiếm tương đối theo tên lớp hoặc từ khóa liên quan",
            )

        st.markdown(
            '<div class="ho-form-section-title"><span class="ho-section-num">D</span> Hành động</div>',
            unsafe_allow_html=True,
        )
        submitted = st.form_submit_button(
            "Xuất dữ liệu",
            type="primary",
            icon=":material/file_download:",
            width="stretch",
        )

    return submitted, {
        "start": selected_start,
        "end": selected_end,
        "sessions": selected_sessions,
        "statuses": selected_statuses,
        "blocks": selected_blocks,
        "course_lines": selected_lines,
        "courses": selected_courses,
        "centres": selected_centres,
        "class_ids": csv_values(class_ids),
        "search": search.strip(),
        "date_field": selected_date_field,
        "types": selected_office_types,
    }


def render_module(module_name: str, auth: AuthService):
    title, eyebrow, description, output_name = MODULES[module_name]
    start, end = default_dates(module_name)

    render_header(eyebrow, title, description, output_name, auth.state)

    job = manager(st.session_state).get(st.session_state.get("active_job"))
    is_job_error = bool(job and job.status == "failed")
    render_workflow(workflow_step_for_job(job), is_error=is_job_error, job=job)

    render_summary_cards(title, output_name, job, icon=MODULE_ICONS.get(module_name, ""))

    if module_name == "products":
        product = products_module()
        kwargs = {
            "sessions": (14, list(product.DEFAULT_SESSION_NUMBERS)),
            "statuses": (list(product.CLASS_STATUS_FILTER_CANDIDATES), list(product.DEFAULT_CLASS_STATUSES)),
        }
    elif module_name == "teacher_attendance":
        attendance = attendance_module()
        kwargs = {
            "sessions": (30, list(attendance.DEFAULT_SESSION_NUMBERS)),
            "statuses": (list(attendance.DEFAULT_CLASS_STATUSES), list(attendance.DEFAULT_CLASS_STATUSES)),
        }
    elif module_name == "class_observe":
        observer = class_observe_module()
        kwargs = {
            "blocks": (list(observer.DEFAULT_BLOCKS), list(observer.DEFAULT_BLOCKS)),
            "statuses": (list(observer.DEFAULT_CLASS_STATUSES), list(observer.DEFAULT_CLASS_STATUSES)),
        }
    elif module_name == "completion":
        completion = completion_module()
        kwargs = {"statuses": (list(completion.DEFAULT_CLASS_STATUSES), list(completion.DEFAULT_CLASS_STATUSES))}
    else:
        kwargs = {}

    if module_name in {"request", "completion"}:
        kwargs["date_fields"] = [("startDate", "Ngày bắt đầu"), ("endDate", "Ngày kết thúc")]
    if module_name == "office_hours":
        kwargs["office_types"] = ["Trial", "Fixed"]

    main_column, context_column = st.columns([2.35, 0.95], gap="large")

    with main_column:
        submitted, values = common_fields(module_name, start, end, **kwargs)

    if module_name == "request":
        values["request_statuses"] = []
        values["satisfaction"] = None
    elif module_name == "survey":
        survey = survey_module()
        values["question_ids"] = list(survey.QUESTION_IDS)
        values["survey_ids"] = list(survey.SURVEY_IDS)
    elif module_name == "completion":
        pass

    with context_column:
        render_context_panel("Tổng quan phiên", output_name, auth.state, job)

    if submitted:
        if values["start"] > values["end"]:
            st.error("Khoảng ngày không hợp lệ. Ngày bắt đầu không thể sau ngày kết thúc.")
        else:
            try:
                auth.ensure_token()
                job_manager = manager(st.session_state)
                job_id = job_manager.start(
                    title,
                    lambda directory: export(module_name, values, directory),
                )
                st.session_state.active_job = job_id
                st.toast("Đã bắt đầu tác vụ xuất dữ liệu", icon="🚀")
                st.rerun()
            except Exception as exc:
                st.error(f"Không thể bắt đầu tác vụ xuất: {exc}")


def render_active_job():
    job_id = st.session_state.get("active_job")
    job = manager(st.session_state).get(job_id) if job_id else None
    render_job(job)


def main():
    auth = AuthService(st.session_state)
    st.session_state.auth_service = auth
    st.session_state.setdefault("theme_mode", "auto")
    st.session_state.setdefault("ui_density", "comfortable")

    inject_app_css(st.session_state.theme_mode, st.session_state.ui_density)

    module_name = sidebar(st.session_state.get("module", "request"), auth)
    if module_name != st.session_state.get("module"):
        st.session_state.module = module_name

    render_module(module_name, auth)

    st.markdown(
        """
        <div class="ho-job-section">
          <div class="ho-job-heading">
            <div class="ho-job-title">Tác vụ hiện tại</div>
            <div class="ho-muted" style="font-size:0.8rem;">Theo dõi tiến trình và tải tệp kết quả</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if hasattr(st, "fragment"):
        @st.fragment(run_every="2s")
        def live_job():
            render_active_job()
        live_job()
    else:
        render_active_job()


if __name__ == "__main__":
    main()
