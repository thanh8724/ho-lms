from __future__ import annotations

import streamlit as st


def render_workflow(current_step: int, is_error: bool = False, job=None) -> None:
    steps = (
        ("01", "Chọn module", "Chọn nghiệp vụ xuất"),
        ("02", "Cấu hình bộ lọc", "Xác định phạm vi dữ liệu"),
        ("03", "Đang xử lý", "Theo dõi log và trạng thái"),
        ("04", "Tải kết quả", "Nhận CSV hoặc ZIP"),
    )
    
    cards_html = []
    for index, (number, title, description) in enumerate(steps, start=1):
        if is_error and index == 3:
            state = "error"
            badge_icon = "✕"
            status_text = "Thất bại"
            status_badge_class = "ho-badge ho-badge-error"
        elif index < current_step:
            state = "complete"
            badge_icon = "✓"
            status_text = "Hoàn tất"
            status_badge_class = "ho-badge ho-badge-success"
        elif index == current_step:
            state = "active"
            badge_icon = number
            if index == 1:
                status_text = "Đã chọn"
            elif index == 2:
                status_text = "Đang cấu hình"
            elif index == 3:
                status_text = "Đang xử lý"
            else:
                status_text = "Sẵn sàng tải"
            status_badge_class = "ho-badge ho-badge-primary"
        else:
            state = "pending"
            badge_icon = number
            status_text = "Chờ lệnh" if index == 3 else "Chờ xuất"
            status_badge_class = "ho-badge ho-badge-neutral"

        card = f"""
        <div class="ho-step ho-step-{state}">
          <div class="ho-step-header">
            <div class="ho-step-badge ho-step-badge-{state}">{badge_icon}</div>
            <span class="{status_badge_class}">{status_text}</span>
          </div>
          <div class="ho-step-body">
            <div class="ho-step-title">{title}</div>
            <div class="ho-step-description">{description}</div>
          </div>
        </div>
        """
        cards_html.append(card)

    st.markdown(
        f"""
        <div class="ho-stepper-container">
          <div class="ho-stepper-grid">
            {''.join(cards_html)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary_cards(
    title: str,
    output_name: str,
    job=None,
    icon: str = "",
) -> None:
    status = getattr(job, "status", "ready")
    if status == "queued":
        status_label = "Đang chờ"
        status_badge = '<span class="ho-badge ho-badge-warning"><span class="ho-dot ho-dot-warning"></span> Đang chờ</span>'
        status_sub = "Tác vụ đã vào hàng đợi"
    elif status == "running":
        status_label = "Đang xử lý"
        status_badge = '<span class="ho-badge ho-badge-primary"><span class="ho-dot ho-dot-primary"></span> Đang xử lý</span>'
        status_sub = "Tiến trình trích xuất đang chạy"
    elif status == "success":
        status_label = "Hoàn tất"
        status_badge = '<span class="ho-badge ho-badge-success"><span class="ho-dot ho-dot-success"></span> Hoàn tất</span>'
        artifact_count = len(getattr(job, "artifacts", []))
        status_sub = f"Đã sẵn sàng ({artifact_count} tệp)" if artifact_count else "Đã xuất dữ liệu thành công"
    elif status == "failed":
        status_label = "Thất bại"
        status_badge = '<span class="ho-badge ho-badge-error"><span class="ho-dot ho-dot-error"></span> Thất bại</span>'
        status_sub = "Gặp lỗi trong quá trình xuất"
    else:
        status_label = "Sẵn sàng"
        status_badge = '<span class="ho-badge ho-badge-neutral"><span class="ho-dot ho-dot-neutral"></span> Sẵn sàng</span>'
        status_sub = "Chờ lệnh xuất dữ liệu"

    st.markdown(
        f"""
        <div class="ho-summary-grid">
          <div class="ho-summary-card">
            <div class="ho-summary-label">Module hiện tại</div>
            <div class="ho-summary-val">{title}</div>
            <div class="ho-summary-sub">Không gian làm việc LMS</div>
          </div>
          <div class="ho-summary-card">
            <div class="ho-summary-label">Tệp đầu ra dự kiến</div>
            <div class="ho-summary-val">
              <code class="ho-code-pill" style="font-size:0.86rem;">{output_name}</code>
            </div>
            <div class="ho-summary-sub">Định dạng bảng mã UTF-8</div>
          </div>
          <div class="ho-summary-card">
            <div class="ho-summary-label">Trạng thái tác vụ</div>
            <div class="ho-summary-val">{status_badge}</div>
            <div class="ho-summary-sub">{status_sub}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_context_panel(
    title: str,
    output_name: str,
    auth_state,
    job=None,
) -> None:
    lms_connected = bool(auth_state and getattr(auth_state, "token", ""))
    if lms_connected:
        email = getattr(auth_state, "email", "") or "Tài khoản hiện tại"
        expiry = getattr(auth_state, "expiry", "")
        expiry_html = f'<div class="ho-context-subtext">Hết hạn: {expiry}</div>' if expiry else ""
        lms_section = f"""
        <div class="ho-context-section">
          <div class="ho-context-section-label">Kết nối LMS</div>
          <div><span class="ho-badge ho-badge-success"><span class="ho-dot ho-dot-success"></span> LMS đã sẵn sàng</span></div>
          <div class="ho-context-meta-text">{email}</div>
          {expiry_html}
        </div>
        """
    else:
        lms_section = """
        <div class="ho-context-section">
          <div class="ho-context-section-label">Kết nối LMS</div>
          <div><span class="ho-badge ho-badge-warning"><span class="ho-dot ho-dot-warning"></span> Chưa kết nối LMS</span></div>
          <div class="ho-context-tip">Mở <strong>Quản trị &gt; Kết nối LMS</strong> ở thanh bên để kích hoạt token.</div>
        </div>
        """

    status = getattr(job, "status", "ready")
    if status == "queued":
        status_badge = '<span class="ho-badge ho-badge-warning"><span class="ho-dot ho-dot-warning"></span> Đang chờ</span>'
    elif status == "running":
        status_badge = '<span class="ho-badge ho-badge-primary"><span class="ho-dot ho-dot-primary"></span> Đang xử lý</span>'
    elif status == "success":
        status_badge = '<span class="ho-badge ho-badge-success"><span class="ho-dot ho-dot-success"></span> Hoàn tất</span>'
    elif status == "failed":
        status_badge = '<span class="ho-badge ho-badge-error"><span class="ho-dot ho-dot-error"></span> Thất bại</span>'
    else:
        status_badge = '<span class="ho-badge ho-badge-neutral"><span class="ho-dot ho-dot-neutral"></span> Sẵn sàng</span>'

    started_time = getattr(job, "started_at", "")
    started_html = f'<div class="ho-context-subtext">Bắt đầu: {started_time}</div>' if started_time else ""

    st.markdown(
        f"""
        <div class="ho-context-card">
          <div class="ho-context-header">
            <div class="ho-context-title">{title}</div>
            <div class="ho-context-caption">Thông tin phiên làm việc</div>
          </div>
          {lms_section}
          <div class="ho-context-section">
            <div class="ho-context-section-label">Tệp đầu ra</div>
            <div class="ho-file-box">
              <span>📄</span>
              <span title="{output_name}">{output_name}</span>
            </div>
          </div>
          <div class="ho-context-section">
            <div class="ho-context-section-label">Trạng thái tác vụ</div>
            <div>{status_badge}</div>
            {started_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def workflow_step_for_job(job) -> int:
    if not job:
        return 2
    if job.status in {"queued", "running"}:
        return 3
    if job.status == "success":
        return 4
    if job.status == "failed":
        return 3
    return 2
