import base64
import io

import pytest
from PIL import Image

from smart_reporting.reporting.delivery.docx_ink_validation import validate_docx_ink_pngs


def test_source_png_is_fully_decoded_and_explicit_clear_is_valid():
    stream = io.BytesIO()
    Image.new('RGBA', (8, 8), (0, 0, 0, 0)).save(stream, format='PNG')
    encoded = base64.b64encode(stream.getvalue()).decode()
    validate_docx_ink_pngs([{'kind': 'setInk', 'inks': [{'base64': encoded}]}])
    validate_docx_ink_pngs([{'kind': 'setInk', 'inks': []}])
    for data in (stream.getvalue()[:24], b'not png'):
        with pytest.raises(ValueError, match='docx_ink_png_invalid'):
            validate_docx_ink_pngs([{'kind': 'setInk', 'inks': [{'base64': base64.b64encode(data).decode()}]}])
