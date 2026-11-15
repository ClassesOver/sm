"""Decode editable ink PNGs before passing fixed-source image operations to OOXML."""
from __future__ import annotations

import base64
import binascii
import io

from PIL import Image


def validate_docx_ink_pngs(operations: list[dict]) -> None:
    """Raises ValueError for incomplete/foreign or oversized PNG payloads."""
    for operation in operations:
        if operation.get("kind") != "setInk":
            continue
        inks = operation.get("inks")
        if not isinstance(inks, list) or len(inks) > 2000:
            raise ValueError("docx_ink_operation_invalid")
        total_bytes = 0
        for ink in inks:
            try:
                encoded = ink["base64"]
                if not isinstance(encoded, str) or len(encoded) > 16_000_000:
                    raise ValueError
                data = base64.b64decode(encoded, validate=True)
                total_bytes += len(data)
                if total_bytes > 32_000_000:
                    raise ValueError
                with Image.open(io.BytesIO(data)) as image:
                    if image.format != "PNG" or image.width * image.height > 16_000_000:
                        raise ValueError
                    if image.width > 40_000 or image.height > 40_000:
                        raise ValueError
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
            except (KeyError, TypeError, ValueError, OSError, binascii.Error, Image.DecompressionBombError) as exc:
                raise ValueError("docx_ink_png_invalid") from exc
