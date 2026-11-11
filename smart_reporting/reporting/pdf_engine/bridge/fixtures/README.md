# PDF conversion fidelity fixture

complex-layout.pdf was generated locally on 2026-11-11 with ReportLab. It
contains two text columns, a ruled 3 × 3 revenue table, a raster chart, a URL
annotation, Helvetica/Times/Courier, and an embedded subset of DejaVu Sans
(including café, naïve, résumé and €). Page size: 600 × 800 pt.

This is test data, not an upstream converter source file. DejaVu Sans was loaded
from the system fonts-dejavu-core package under its permissive font license;
that package's copyright/embedding permission is recorded in
DejaVu-font-copyright.txt. The fixture does not assert pixel-perfect output.
The regression checks editable content/structures; LibreOffice rendering and
pixel comparisons are separate evidence with manual fidelity status retained.

## xlsx-normal-images.pdf

Project-generated test fixture (2026-11-11), created with ReportLab and pypdf;
no external document or image content. Three 420×360pt authored pages contain
editable Helvetica text, a ruled two-column table with numeric revenue, and
three instances of a project-created 80×40px RGBA quadrant image. Quadrants are
red/blue/yellow at alpha 255 and green at alpha 128. One object rotates 90°,
one crosses the visible right edge. Page 2 has a nonzero-origin CropBox
(20,40)–(400,340); page 3 has /Rotate 90. These distinguish actual bitmap
rotation/cropping from assigning a different anchor to unchanged pixels.
The frontend/smoke/pdf-xlsx-images-verify.py independently checks source-space
anchors and interior RGBA values with openpyxl, XML and Pillow.
