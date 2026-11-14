"""真实双图 XLSX 的默认/别名命名空间夹具；保留几何及业务值。"""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import sys

from lxml import etree

from smart_reporting.reporting.tests.test_workbook_ai_charts import source_with_two_charts


OPAQUE = '<vendor:payload xmlns:vendor="urn:namespace-fixture"><vendor:title>Keep &amp; opaque</vendor:title></vendor:payload>'


def namespace_source() -> bytes:
    source = source_with_two_charts()
    output = BytesIO()
    with ZipFile(BytesIO(source)) as original, ZipFile(output, 'w', ZIP_DEFLATED) as saved:
        for member in original.infolist():
            data = original.read(member.filename)
            if member.filename.startswith('xl/charts/chart') and member.filename.endswith('.xml'):
                xml = data.decode()
                prefix = '' if member.filename.endswith('chart1.xml') else 'plot'
                xml = xml.replace('xmlns:c=', 'xmlns' + (':' + prefix if prefix else '') + '=')
                xml = xml.replace('<c:', '<' + (prefix + ':' if prefix else '')).replace('</c:', '</' + (prefix + ':' if prefix else ''))
                xml = xml.replace('xmlns:a=', 'xmlns:ink=').replace('<a:', '<ink:').replace('</a:', '</ink:')
                root_end = '</' + (prefix + ':' if prefix else '') + 'chartSpace>'
                extension = '<' + (prefix + ':' if prefix else '') + 'extLst><' + (prefix + ':' if prefix else '') + 'ext uri="fixture">' + OPAQUE + '</' + (prefix + ':' if prefix else '') + 'ext></' + (prefix + ':' if prefix else '') + 'extLst>'
                xml = xml.replace(root_end, extension + root_end)
                data = xml.encode()
            elif member.filename == 'xl/drawings/drawing1.xml':
                xml = data.decode().replace('xmlns:xdr=', 'xmlns=').replace('<xdr:', '<').replace('</xdr:', '</')
                xml = xml.replace('xmlns:a=', 'xmlns:ink=').replace('<a:', '<ink:').replace('</a:', '</ink:')
                xml = xml.replace('xmlns:c=', 'xmlns:part=').replace('<c:', '<part:').replace('</c:', '</part:')
                xml = xml.replace('xmlns:r=', 'xmlns:link=').replace('r:id="rId1"', 'link:id="chart&amp;one"').replace('r:id=', 'link:id=')
                xml = xml.replace('</wsDr>', '<!-- <xdr:graphicFrame><c:chart r:id="keep"/></xdr:graphicFrame> -->' + OPAQUE + '</wsDr>')
                data = xml.encode()
            elif member.filename == 'xl/drawings/_rels/drawing1.xml.rels':
                xml = data.decode().replace('xmlns=', 'xmlns:pkg=').replace('<Relationships', '<pkg:Relationships').replace('</Relationships', '</pkg:Relationships').replace('<Relationship ', '<pkg:Relationship ').replace('Id="rId1"', 'Id="chart&amp;one"')
                data = xml.encode()
            if member.filename.endswith(('.xml', '.rels')):
                etree.fromstring(data)
            saved.writestr(member, data)
        saved.writestr('custom/namespace-sentinel.bin', bytes([0, 255, 41, 128, 0]))
    return output.getvalue()


if __name__ == '__main__':
    Path(sys.argv[1]).write_bytes(namespace_source())
