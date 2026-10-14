from __future__ import annotations

import streamlit as st

from pulldata.services.artifact_service import zip_artifacts
from pulldata.runtime.job_manager import Job


def render_job(job: Job | None) -> None:
    if not job:
        return
    state = "running" if job.status in {"queued", "running"} else ("complete" if job.status == "success" else "error")
    status_label = {"queued": "Đang chờ", "running": "Đang xử lý", "success": "Hoàn tất", "failed": "Thất bại"}.get(job.status, job.status)
    with st.status(f"{job.label} · {status_label}", state=state, expanded=job.status != "success"):
        if job.error:
            st.error(job.error)
        if job.status == "success":
            st.success("Đã hoàn tất. Các tệp đã sẵn sàng để tải xuống.")
    with st.expander(f"Nhật ký xử lý ({len(job.logs)} dòng)", expanded=job.status in {"queued", "running", "failed"}):
        if job.logs:
            st.code("\n".join(job.logs[-120:]), language="text", height=240)
        elif job.status in {"queued", "running"}:
            st.caption("Đang chờ log từ exporter...")
        else:
            st.caption("Không có log.")
    if job.status == "success" and job.artifacts:
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
