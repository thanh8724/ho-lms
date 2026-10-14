from __future__ import annotations

import streamlit as st


def render_workflow(current_step: int) -> None:
    steps = (
        ("01", "Chọn module", "Chọn nghiệp vụ cần xuất"),
        ("02", "Cấu hình bộ lọc", "Xác định phạm vi dữ liệu"),
        ("03", "Đang xử lý", "Theo dõi log và trạng thái"),
        ("04", "Tải kết quả", "Nhận CSV hoặc ZIP"),
    )
    columns = st.columns(4, gap="small")
    for index, (number, title, description) in enumerate(steps, start=1):
        state = "complete" if index < current_step else ("active" if index == current_step else "pending")
        with columns[index - 1]:
            st.markdown(
                f'<div class="ho-step ho-step-{state}">'
                f'<div class="ho-step-number">{number}</div>'
                f'<div><div class="ho-step-title">{title}</div>'
                f'<div class="ho-step-description">{description}</div></div></div>',
                unsafe_allow_html=True,
            )


def render_context_panel(title: str, output_name: str, auth_state, job=None) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="ho-panel-title">{title}</div>', unsafe_allow_html=True)
        st.caption("Thông tin phiên làm việc")
        if auth_state.token:
            st.success("LMS đã sẵn sàng", icon=":material/check_circle:")
            st.caption(auth_state.email or "Token hiện tại")
        else:
            st.warning("Chưa kết nối LMS", icon=":material/warning:")
            st.caption("Mở Kết nối LMS ở sidebar để kiểm tra token.")
        st.divider()
        st.markdown("**Tệp đầu ra**")
        st.code(output_name, language="text")
        st.markdown("**Trạng thái tác vụ**")
        status = getattr(job, "status", "ready")
        status_label = {
            "queued": "Đang chờ",
            "running": "Đang xử lý",
            "success": "Hoàn tất",
            "failed": "Thất bại",
            "ready": "Sẵn sàng",
        }.get(status, status)
        st.metric("Hiện tại", status_label)


def workflow_step_for_job(job) -> int:
    if not job:
        return 2
    if job.status in {"queued", "running"}:
        return 3
    if job.status == "success":
        return 4
    return 3
