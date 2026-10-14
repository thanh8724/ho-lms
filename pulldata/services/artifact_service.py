from __future__ import annotations

import io
import zipfile

from pulldata.runtime.job_manager import Artifact


def zip_artifacts(artifacts: list[Artifact]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            archive.writestr(artifact.name, artifact.data)
    return output.getvalue()
