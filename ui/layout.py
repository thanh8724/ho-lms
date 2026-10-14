from __future__ import annotations

import streamlit as st

from pulldata.runtime.job_manager import Job
from pulldata.services.artifact_service import zip_artifacts


def render_job(job: Job | None) -> None:
    if not job:
        st.markdown(
            """
            <div class="ho-empty-job-card">
              <div class="ho-empty-icon">⏳</div>
              <div>
                <div class="ho-empty-title">Chưa có tác vụ nào đang chạy</div>
                <div class="ho-empty-desc">Cấu hình bộ lọc ở trên và nhấn <strong>Xuất dữ liệu</strong> để bắt đầu quá trình trích xuất LMS.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    status = job.status
    if status == "queued":
        status_badge = '<span class="ho-badge ho-badge-warning"><span class="ho-dot ho-dot-warning"></span> Đang chờ</span>'
    elif status == "running":
        status_badge = '<span class="ho-badge ho-badge-primary"><span class="ho-dot ho-dot-primary"></span> Đang xử lý</span>'
    elif status == "success":
        status_badge = '<span class="ho-badge ho-badge-success"><span class="ho-dot ho-dot-success"></span> Hoàn tất</span>'
    elif status == "failed":
        status_badge = '<span class="ho-badge ho-badge-error"><span class="ho-dot ho-dot-error"></span> Thất bại</span>'
    else:
        status_badge = f'<span class="ho-badge ho-badge-neutral">{status}</span>'

    time_info = []
    if job.started_at:
        time_info.append(f"Bắt đầu: {job.started_at}")
    if job.finished_at:
        time_info.append(f"Hoàn thành: {job.finished_at}")
    time_str = " · ".join(time_info) if time_info else "Đang khởi tạo"

    st.markdown(
        f"""
        <div class="ho-job-card">
          <div class="ho-job-card-header">
            <div>
              <div class="ho-job-name">{job.label}</div>
              <div class="ho-job-time">{time_str}</div>
            </div>
            <div>{status_badge}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if job.error:
        st.error(job.error, icon=":material/error:")
    elif job.status in {"queued", "running"}:
        st.info("Đang xử lý truy vấn LMS và kết xuất dữ liệu. Vui lòng giữ phiên làm việc.", icon=":material/sync:")
    elif job.status == "success":
        st.success("Tác vụ đã hoàn tất. Các tệp dữ liệu đã sẵn sàng để tải xuống.", icon=":material/check_circle:")

    with st.expander(f"Nhật ký xử lý ({len(job.logs)} dòng)", expanded=job.status in {"queued", "running", "failed"}):
        if job.logs:
            st.code("\n".join(job.logs[-120:]), language="text", height=240)
        elif job.status in {"queued", "running"}:
            st.caption("Đang chờ log từ hệ thống trích xuất LMS...")
        else:
            st.caption("Không có log nào được ghi nhận.")

    if job.status == "success" and job.artifacts:
        st.markdown(
            f'<div style="color:var(--ho-text);font-size:0.9rem;font-weight:700;margin:1rem 0 0.5rem;">Tệp kết quả ({len(job.artifacts)} tệp)</div>',
            unsafe_allow_html=True,
        )
        columns = st.columns(min(3, len(job.artifacts)))
        for column, artifact in zip(columns, job.artifacts):
            with column:
                st.download_button(
                    f"Tải {artifact.name}",
                    data=artifact.data,
                    file_name=artifact.name,
                    mime=artifact.content_type,
                    width="stretch",
                    key=f"download-{job.id}-{artifact.name}",
                )
        if len(job.artifacts) > 1:
            st.download_button(
                "Tải toàn bộ file (.zip)",
                data=zip_artifacts(job.artifacts),
                file_name=f"ho-pulldata-{job.id[:8]}.zip",
                mime="application/zip",
                width="stretch",
                key=f"download-zip-{job.id}",
            )
