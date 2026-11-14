"""PC 字段列表夹具：复用真实签发服务，添加长字段名及只读字段。"""
import argparse
import asyncio
import importlib.util
from io import BytesIO
from pathlib import Path

import uvicorn
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, TextStringObject

spec = importlib.util.spec_from_file_location("form_design_server", Path(__file__).with_name("pdf-form-design-server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
original_form_pdf = server.form_pdf


def desktop_form_pdf():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(original_form_pdf())))
    for ref in writer._root_object["/AcroForm"]["/Fields"]:
        field = ref.get_object()
        if field.get("/T") == "keep":
            field[NameObject("/T")] = TextStringObject("keep_" + "LongFieldName_" * 15)
            field[NameObject("/Ff")] = NumberObject(1)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4381)
    args = parser.parse_args()
    server.form_pdf = desktop_form_pdf
    uvicorn.run(asyncio.run(server.create_app(args.directory, args.port)), host="127.0.0.1", port=args.port, log_level="warning")
