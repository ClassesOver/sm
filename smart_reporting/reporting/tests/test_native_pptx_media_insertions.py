"""音视频 journal 在调用真实 writer 前拒绝损坏输入，不改现有草稿。"""
import base64

import pytest

from smart_reporting.report_editor.pptx_media import native_media_insertions


def media(**patch):
    return {"slideIndex": 0, "kind": "audio", "extension": "wav", "bytesBase64": base64.b64encode(b"RIFFfixture").decode(), "name": "样例.wav", **patch}


def test_media_journal_preserves_original_bytes_and_accepts_source_containers():
    for kind, extensions in (("video", ["mp4", "m4v", "mov", "webm", "avi"]), ("audio", ["mp3", "wav", "m4a", "aac", "ogg"])):
        item = media(kind=kind, extension=extensions[0])
        for extension in extensions:
            item = {**item, "extension": extension}
            assert native_media_insertions({"mediaInsertions": [item]}) == [item]


@pytest.mark.parametrize("patch", [{"kind": "video"}, {"extension": "exe"}, {"bytesBase64": "UklGRg==\n"}, {"bytesBase64": "Zh=="}, {"bytesBase64": ""}, {"slideIndex": True}, {"slideIndex": -1}, {"path": "/tmp/media.wav"}, {"name": "bad\nname"}, {"center": {"x": float("inf"), "y": 1}}])
def test_media_journal_rejects_invalid_requests(patch):
    with pytest.raises(ValueError, match="native_office_operations_invalid"):
        native_media_insertions({"mediaInsertions": [media(**patch)]})


def test_media_and_images_share_eight_mib_budget():
    large = base64.b64encode(b"x" * (5 * 1024 * 1024)).decode()
    with pytest.raises(ValueError):
        native_media_insertions({"mediaInsertions": [media(bytesBase64=large)], "images": [{"bytesBase64": large}]})
    with pytest.raises(ValueError):
        native_media_insertions({"mediaInsertions": [media(bytesBase64=base64.b64encode(b"x" * (6 * 1024 * 1024 + 1)).decode())]})


def test_recording_poster_requires_real_png_and_matching_identity():
    import hashlib
    from io import BytesIO
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (8, 4), 'red').save(image, format='PNG')
    data = image.getvalue()
    poster = {'bytesBase64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}
    item = media(kind='video', extension='webm', poster=poster)
    assert native_media_insertions({'mediaInsertions': [item]}) == [item]
    for bad in ({**poster, 'sha256': '0' * 64}, {'bytesBase64': base64.b64encode(data[:24]).decode(), 'sha256': hashlib.sha256(data[:24]).hexdigest()}):
        with pytest.raises(ValueError):
            native_media_insertions({'mediaInsertions': [{**item, 'poster': bad}]})
    with pytest.raises(ValueError):
        native_media_insertions({'mediaInsertions': [media(poster=poster)]})


def test_recording_poster_counts_towards_combined_model_asset_budget():
    from smart_reporting.report_editor.pptx_model3d import native_model_edits
    data = base64.b64encode(b'x' * (4 * 1024 * 1024)).decode()
    # 两组各 4MiB 字节已用满共享预算，录制首帧不能游离在预算之外。
    with pytest.raises(ValueError):
        native_model_edits({'images': [{'bytesBase64': data}], 'mediaInsertions': [media(bytesBase64=data, poster={'bytesBase64': base64.b64encode(b'png').decode()})]})
