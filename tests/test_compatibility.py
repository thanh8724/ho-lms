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
from pulldata.runtime.job_manager import JobManager


def test_legacy_csv_schemas_are_available():
    assert len(request_module().CSV_COLUMNS) == 31
    assert len(survey_module().BASE_COLUMNS) == 10
    assert len(products_module().DETAIL_COLUMNS) == 32
    assert len(completion_module().EXPORT_COLUMNS) == 21
    assert len(attendance_module().EXPORT_COLUMNS) == 17
    assert len(office_hours_module().OUTPUT_COLUMNS) == 16
    assert len(class_observe_module().EXPORT_COLUMNS) == 8


def test_job_manager_collects_csv_artifact(tmp_path: Path):
    manager = JobManager()

    def worker(output_dir: Path):
        output = output_dir / "sample.csv"
        output.write_text("a,b\n1,2\n", encoding="utf-8")
        return [output], "sample.csv"

    job_id = manager.start("Compatibility test", worker)
    job = manager.wait(job_id, timeout=5)

    assert job.status == "success"
    assert job.result == "sample.csv"
    assert job.artifacts[0].name == "sample.csv"
    assert job.artifacts[0].data == b"a,b\n1,2\n"
