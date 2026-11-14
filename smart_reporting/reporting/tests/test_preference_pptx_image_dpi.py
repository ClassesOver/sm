from __future__ import annotations

from hashlib import sha256
from io import BytesIO

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import _apply_chart_image_dpi, build_editable_pptx


def test_pptx_chart_dpi_downsamples_only_frozen_chart_media_and_reads_back_actual_file(tmp_path):
    chart = tmp_path / 'chart.png'
    source = Image.new('RGB', (2400, 1200), '#1B776F')
    source.save(chart)
    source_sha = sha256(chart.read_bytes()).hexdigest()
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'DPI reviewer'},
        'pptx': {'charts': {'imageDpi': 120}},
    }), 'pptx')
    destination = tmp_path / 'image-dpi.pptx'

    result = build_editable_pptx(
        output_path=destination,
        title='Image DPI report',
        period='2026',
        theme='executive',
        slides=({'title': 'Chart source', 'bullets': ['Chart remains editable as a picture.'],
            'chartPath': str(chart)},),
        preferences=preferences,
        generated_date='2026-11-13',
    )

    actual = Presentation(destination)
    picture = next(shape for slide in actual.slides for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    record = next(item for item in result.image_derivations if item['slide'] == 2)
    with Image.open(chart) as original, Image.open(BytesIO(picture.image.blob)) as embedded:
        assert original.size == (2400, 1200)
        assert embedded.width < original.width
        assert embedded.height < original.height
        embedded_size = embedded.size
    assert sha256(chart.read_bytes()).hexdigest() == source_sha
    assert record['sourceSha256'] == source_sha
    assert record['sourcePart'] != record['embeddedPart']
    assert record['embeddedSha256'] == sha256(picture.image.blob).hexdigest()
    assert record['pixelWidth'] == embedded_size[0]
    assert record['pixelHeight'] == embedded_size[1]
    assert record['extentWidthEmu'] == picture.width
    assert record['extentHeightEmu'] == picture.height
    assert record['effectiveDpiX'] <= 120.01
    assert record['effectiveDpiY'] <= 120.01
    assert record['withinLimit'] is True
    assert not any(issue['code'].startswith('pptx_chart_image_dpi') for issue in result.issues)


def test_pptx_chart_dpi_does_not_upscale_low_resolution_or_rewrite_other_media(tmp_path):
    chart = tmp_path / 'chart.png'
    other = tmp_path / 'other.png'
    Image.new('RGB', (100, 100), '#1B776F').save(chart)
    Image.new('RGB', (100, 100), '#CE5B3A').save(other)
    path = tmp_path / 'source.pptx'
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_picture(str(chart), 0, 0, width=2 * 914400, height=2 * 914400)
    other_shape = slide.shapes.add_picture(str(other), 3 * 914400, 0, width=1 * 914400, height=1 * 914400)
    deck.save(path)
    source = Presentation(path)
    original_chart = next(shape for shape in source.slides[0].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    original_other = next(shape for shape in source.slides[0].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
        and shape.left == other_shape.left)
    chart_bytes = original_chart.image.blob
    other_bytes = original_other.image.blob

    evidence, warnings = _apply_chart_image_dpi(path, ({
        'slide': 1, 'sourceSha256': sha256(chart.read_bytes()).hexdigest(),
    },), 72)

    actual = Presentation(path)
    actual_chart = next(shape for shape in actual.slides[0].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    actual_other = next(shape for shape in actual.slides[0].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
        and shape.left == other_shape.left)
    assert actual_chart.image.blob == chart_bytes
    assert actual_other.image.blob == other_bytes
    assert evidence[0]['sourceSha256'] == sha256(chart_bytes).hexdigest()
    assert evidence[0]['embeddedSha256'] == sha256(chart_bytes).hexdigest()
    assert evidence[0]['withinLimit'] is True
    assert warnings == ()


def test_pptx_chart_dpi_keeps_shared_source_media_when_non_chart_object_reuses_it(tmp_path):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (1200, 600), '#1B776F').save(chart)
    path = tmp_path / 'shared-media.pptx'
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    chart_shape = slide.shapes.add_picture(str(chart), 0, 0, width=2 * 914400, height=1 * 914400)
    other_shape = slide.shapes.add_picture(str(chart), 3 * 914400, 0, width=2 * 914400, height=1 * 914400)
    chart_part = chart_shape.part.related_part(chart_shape._element.blipFill.blip.rEmbed).partname
    other_part = other_shape.part.related_part(other_shape._element.blipFill.blip.rEmbed).partname
    assert chart_part == other_part
    deck.save(path)
    source = Presentation(path)
    original = [shape.image.blob for shape in source.slides[0].shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE]

    evidence, warnings = _apply_chart_image_dpi(path, ({
        'slide': 1, 'sourceSha256': sha256(chart.read_bytes()).hexdigest(),
    },), 72)

    actual = Presentation(path)
    embedded = [shape.image.blob for shape in actual.slides[0].shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert embedded == original
    assert evidence == ()
    assert warnings[0]['code'] == 'pptx_chart_image_dpi_binding_ambiguous'
