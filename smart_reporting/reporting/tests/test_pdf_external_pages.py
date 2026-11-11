"""真实固定源写入后，独立 pypdf 校验正文页序及页面几何。"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

def pdf(prefix, count):
    stream=BytesIO();canvas=Canvas(stream,pagesize=(300,400),invariant=True)
    for index in range(count):canvas.drawString(30,300,f'{prefix} {index+1}');canvas.showPage()
    canvas.save();return stream.getvalue()

@pytest.mark.parametrize('action,options,expected',[
    ('insert',{'afterPageIndex':0},['source 1','external 1','external 2','source 2','source 3']),
    ('replace',{'pages':[2,0]},['external 1','external 2','source 2']),
])
def test_external_page_actual_output_independent_reader(tmp_path,action,options,expected):
    root=Path(__file__).resolve().parents[1]/'pdf_engine'
    source,external=pdf('source',3),pdf('external',2)
    source_path=tmp_path/'source.pdf';output=tmp_path/'output.pdf';request=tmp_path/'request.json'
    source_path.write_bytes(source)
    operation={'kind':'externalPages','action':action,'sourceSha256':hashlib.sha256(source).hexdigest(),'externalSha256':hashlib.sha256(external).hexdigest(),'bytesBase64':base64.b64encode(external).decode(),**options}
    request.write_text(json.dumps(operation))
    script="import{readFile,writeFile}from'node:fs/promises';import{patchExternalPages}from'./bridge/external-pages.ts';const op=JSON.parse(await readFile(process.argv[1],'utf8'));const result=await patchExternalPages(new Uint8Array(await readFile(process.argv[2])),op,op.sourceSha256);await writeFile(process.argv[3],result.bytes);console.log(JSON.stringify({sha256:result.sha256,size:result.size}));"
    completed=subprocess.run(['node','--import','tsx','--input-type=module','-e',script,str(request),str(source_path),str(output)],cwd=root,capture_output=True,text=True,timeout=120,check=True)
    receipt=json.loads(completed.stdout.strip().splitlines()[-1]);content=output.read_bytes();reader=PdfReader(BytesIO(content))
    assert [page.extract_text().strip() for page in reader.pages]==expected
    assert all(list(page.mediabox)==[0,0,300,400] for page in reader.pages)
    assert all(not page.get('/Annots') for page in reader.pages)
    assert not reader.get_fields()
    assert hashlib.sha256(content).hexdigest()==receipt['sha256']
    assert len(content)==receipt['size']
    assert source_path.read_bytes()==source
