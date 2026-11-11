"""Compare independent Chromium SVG/PDF.js raster ink extents, not exact pixels."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image


def ink(image, box):
    left, top, right, bottom = box
    points = [(x, y) for y in range(top, bottom) for x in range(left, right)
              if (lambda rgb: rgb[0] - rgb[1] > 4 and rgb[0] - rgb[2] > 4)(image.getpixel((x, y)))]
    assert points, ('No drawing ink in region', box)
    return [min(x for x, _ in points), min(y for _, y in points),
            max(x for x, _ in points) + 1, max(y for _, y in points) + 1], len(points)


def verify(directory):
    result = json.loads((directory / 'summary.json').read_text())
    checks = []
    for row in result['checkpoints']:
        rotation, zoom = row['rotation'], row['zoom']
        suffix = f'{rotation}-{zoom:g}.png'
        draft = Image.open(directory / f'draft-labels-{suffix}').convert('RGB')
        saved = Image.open(directory / f'saved-labels-{suffix}').convert('RGB')
        assert draft.size == saved.size == (int(row['width']), int(row['height']))
        va, vb, vc, vd, ve, vf = row['viewport']
        for index, label in enumerate(row['labels']):
            # Build an independent generous candidate from native AP Tm and
            # actual PDF.js font advance, then union the draft's own bounds.
            a, b, c, d, e, f = row['evidence']['appearance'][index]['tm']
            corners = []
            for x in (-2, label['pdfAdvance'] + 2):
                for y in (-11, 4):
                    px, py = e + a*x - c*y, f + b*x - d*y
                    corners.append((va*px + vc*py + ve, vb*px + vd*py + vf))
            left, top, right, bottom = label['inkBox']
            region = [max(0, math.floor(min(left, *(x for x, _ in corners))) - 4),
                      max(0, math.floor(min(top, *(y for _, y in corners))) - 4),
                      min(draft.width, math.ceil(max(right, *(x for x, _ in corners))) + 4),
                      min(draft.height, math.ceil(max(bottom, *(y for _, y in corners))) + 4)]
            draft_box, draft_pixels = ink(draft, region)
            saved_box, saved_pixels = ink(saved, region)
            for bounds in (draft_box, saved_box):
                assert bounds[0] > region[0] and bounds[1] > region[1]
                assert bounds[2] < region[2] and bounds[3] < region[3], ('Ink touches diagnostic crop', bounds, region)
            delta = max(abs(a-b) for a, b in zip(draft_box, saved_box, strict=True))
            assert delta <= 2, (rotation, zoom, label['label'], draft_box, saved_box)
            checks.append({'rotation': rotation, 'zoom': zoom, 'label': label['label'],
                           'draftInkBounds': draft_box, 'savedInkBounds': saved_box,
                           'candidateRegion': region, 'maxEdgeDifferencePx': delta, 'draftInkPixels': draft_pixels,
                           'savedInkPixels': saved_pixels})
    return {'ok': True, 'scope': '32 label raster ink extent comparisons against text-only diagnostic preserving actual native AP Tm/Tf/Tj/resources/BBox; lines/caret omitted only for ink isolation. Independent union ROI, no ink touches crop. <=2 CSS px per edge; antialias shapes and pixel counts need not match.', 'checks': checks}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
