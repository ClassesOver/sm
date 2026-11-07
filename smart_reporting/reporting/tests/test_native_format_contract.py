import pytest
from pydantic import ValidationError
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile

@pytest.mark.parametrize('mime',[
'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
'application/vnd.openxmlformats-officedocument.presentationml.presentation',
])
def test_native_office_identity_accepts_standard_spreadsheet_and_slide_mime(mime):
    identity=ArtifactFile(path='native/original.office',mediaType=mime,size=1,sha256='a'*64)
    assert identity.media_type==mime
    with pytest.raises(ValidationError):
        ArtifactFile(path='native/original.office',mediaType='application/octet-stream',size=1,sha256='a'*64)
