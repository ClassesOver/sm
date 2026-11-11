"""Compare real browser SVG checkpoints with downloaded native AP instructions."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from pypdf import PdfReader
from pypdf.generic import ContentStream


def near(actual, expected):
    assert len(actual) == len(expected)
    assert all(abs(float(a)-float(b)) < 1e-6 for a,b in zip(actual, expected, strict=True)), (actual, expected)


def verify(directory: Path):
    checkpoints = json.loads((directory/'draft-appearance.json').read_text())
    staged = json.loads((directory/'staged.json').read_text())
    reader = PdfReader(directory/'mixed.pdf')
    assert len(reader.pages) == 3 and reader.pages[0].rotation == 0
    near(list(reader.pages[0].cropbox), [0,0,300,400])
    assert checkpoints['sourceSha256'] == hashlib.sha256((directory/'source.pdf').read_bytes()).hexdigest()
    assert [row['zoom'] for row in checkpoints['checkpoints']] == [.5,2,1]
    annotations = [raw.get_object() for raw in reader.pages[0]['/Annots']]
    assert [str(a['/Subtype']) for a in annotations] == ['/Underline','/Line','/Caret','/Line']
    native_measures = []
    for slot, operation_index, label, line in [(1,0,'3.00 m',[80,200,240,200]),(3,4,'0.04 m',[80,300,82,300])]:
        annotation = annotations[slot]
        path = ContentStream(annotation['/AP']['/N'].get_object(),reader).operations
        assert str(annotation['/Contents']) == label == staged[operation_index]['label']
        near(list(annotation['/L']), line)
        assert path[10][1] == b'Tm' and path[11][1] == b'Tj' and str(path[11][0][0]) == label
        assert str(path[9][0][0]) == '/F1' and float(path[9][0][1]) == 9
        native_measures.append((operation_index, label, list(map(float,path[10][0]))))
    caret = annotations[2]
    assert caret['/F'] == 4
    caret_path = ContentStream(caret['/AP']['/N'].get_object(),reader).operations
    assert [key for _,key in caret_path] == [b'rg',b'm',b'l',b'l',b'f']
    native_vertices = [list(map(float,args)) for args,_ in caret_path[1:4]]
    near([v for point in native_vertices for v in point], [255,300,247,294,263,294])
    color = 'rgb('+','.join(str(int(float(value)*255+.5)) for value in caret_path[0][0])+')'
    for row in checkpoints['checkpoints']:
        zoom = row['zoom']
        assert row['operations'] == staged
        near([row['width'],row['height']],[300*zoom,400*zoom])
        for actual, (operation_index,label,(a,b,c,d,e,f)) in zip(row['measures'],native_measures,strict=True):
            assert actual['operationIndex'] == operation_index and actual['label'] == label
            near(actual['matrix'],[a*zoom,-b*zoom,-c*zoom,d*zoom,e*zoom,(400-f)*zoom])
            assert actual['anchor'] == 'start' and actual['fontSize'] == '9'
            assert actual['fontKerning'] == actual['fontVariantLigatures'] == 'none'
        actual = row['caret']
        near(actual['vertices'],[value for x,y in native_vertices for value in [x*zoom,(400-y)*zoom]])
        assert actual['fill'] == color and actual['stroke'] == 'none' and actual['path'].endswith(' Z')
        assert actual['hitPath'] == actual['path'] and actual['hitFill'] == 'none' and actual['hitStroke'] == 'transparent' and actual['hitWidth'] == '16'
    return {'ok':True,'outputSha256':hashlib.sha256((directory/'mixed.pdf').read_bytes()).hexdigest(),'zooms':[.5,2,1],'rotation':0,'nativeMeasures':native_measures,'nativeCaretVertices':native_vertices,'scope':'Native AP matrix/vertices to SVG geometry, not equality of fallback font ink pixels.'}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])),ensure_ascii=False,indent=2))
