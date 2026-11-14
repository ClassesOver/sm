"""符号窗口夹具：原生 XLSX 保存与独立 openpyxl/ZIP 核对。"""
from __future__ import annotations

import json
import sys
from copy import copy
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from smart_reporting.report_editor.native_office import patch_office


def run(payload: dict) -> dict:
    mode, directory = payload["mode"], Path(payload["directory"])
    if mode == "create":
        book = Workbook()
        sheet = book.active
        sheet.title = "Data"
        sheet["A1"] = "价格 & <保真> 😀"
        sheet["A1"].font = Font(name="Calibri", size=12, bold=True, color="FF1F4FD8")
        sheet["A1"].fill = PatternFill("solid", fgColor="FFF2F5FA")
        sheet["A2"] = 12.5
        sheet["A2"].number_format = "0.00"
        sheet["B1"] = "H2O"
        sheet["C1"] = "=A2*2"
        sheet.column_dimensions["A"].width = 28
        locked = book.create_sheet("Locked")
        locked["A1"] = "private"
        locked.protection.sheet = True
        book.save(directory / "source.xlsx")
        return {"sourceSha256": sha256((directory / "source.xlsx").read_bytes()).hexdigest()}
    if mode == "patch":
        source = (directory / "source.xlsx").read_bytes()
        output = patch_office("xlsx", source, payload["operations"])
        (directory / "revision-2.xlsx").write_bytes(output)
        return {"size": len(output), "sha256": sha256(output).hexdigest()}
    source = load_workbook(directory / "source.xlsx")
    output = load_workbook(directory / "downloaded.xlsx")
    assert source.sheetnames == output.sheetnames == ["Data", "Locked"]
    assert output["Data"]["A1"].value == "价格 & <保真> 😀€→"
    cells = []
    for name in source.sheetnames:
        a, b = source[name], output[name]
        assert (a.max_row, a.max_column) == (b.max_row, b.max_column)
        assert a.protection == b.protection
        assert a.column_dimensions["A"].width == b.column_dimensions["A"].width
        for row in a:
            for original in row:
                saved = b[original.coordinate]
                if (name, original.coordinate) != ("Data", "A1"):
                    assert original.value == saved.value, (name, original.coordinate)
                for attribute in ["font", "fill", "border", "alignment", "protection"]:
                    assert copy(getattr(original, attribute)) == copy(getattr(saved, attribute)), (name, original.coordinate, attribute)
                assert original.number_format == saved.number_format
                cells.append([name, original.coordinate])
    with ZipFile(directory / "source.xlsx") as a, ZipFile(directory / "downloaded.xlsx") as b:
        assert b.testzip() is None
        assert set(a.namelist()) == set(b.namelist())
        changed = [name for name in a.namelist() if a.read(name) != b.read(name)]
        assert a.read("xl/worksheets/sheet2.xml") == b.read("xl/worksheets/sheet2.xml")
    result = {
        "ok": True,
        "sourceSha256": sha256((directory / "source.xlsx").read_bytes()).hexdigest(),
        "outputSha256": sha256((directory / "downloaded.xlsx").read_bytes()).hexdigest(),
        "outputBytes": (directory / "downloaded.xlsx").stat().st_size,
        "value": output["Data"]["A1"].value,
        "formula": output["Data"]["C1"].value,
        "cellsChecked": cells,
        "cellStylesAndOtherValuesPreserved": True,
        "lockedSheetBytesPreserved": True,
        "changedParts": changed,
    }
    (directory / "independent-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
