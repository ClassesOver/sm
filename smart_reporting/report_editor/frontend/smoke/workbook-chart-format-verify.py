"""ChartFormatPane 独立 openpyxl/lxml 文件验收，不调用产品 writer/reader。"""
import hashlib,json,sys
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from openpyxl import Workbook,load_workbook
from openpyxl.chart import BarChart,PieChart,DoughnutChart,LineChart,Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import DataPoint
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker,TwoCellAnchor
p=Path(sys.argv[1]);ns={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
if '--fixture' in sys.argv:
 b=Workbook();s=b.active;s.title='Sheet'
 for row in [['分类','收入'],['甲',3],['空',0],['乙',7]]:s.append(row)
 s['D1']='保留来源';b.create_sheet('原件保留')['A1']='不可改变'
 for i,kind in enumerate(['column','pie','doughnut','line']):
  c={'column':BarChart,'pie':PieChart,'doughnut':DoughnutChart,'line':LineChart}[kind]();c.title='Format '+kind;c.legend=None;c.add_data(Reference(s,min_col=2,min_row=1,max_row=4),titles_from_data=True);c.set_categories(Reference(s,min_col=1,min_row=2,max_row=4));c.anchor=TwoCellAnchor(_from=AnchorMarker(col=4,row=i*13+1),to=AnchorMarker(col=13,row=i*13+12));c.dLbls=DataLabelList();c.dLbls.showVal=True
  if kind=='column':c.gapWidth=230;c.y_axis.scaling.min=-5;c.y_axis.scaling.max=25
  if kind in ['pie','doughnut']:c.series[0].explosion=20;c.series[0].data_points=[DataPoint(idx=2,explosion=45)]
  if kind=='doughnut':c.holeSize=70
  s.add_chart(c)
 b.save(p/'fixture.xlsx');print('{}');sys.exit()
b=load_workbook(p/'chart-format.xlsx');assert b['Sheet']['D1'].value=='保留来源';assert b['原件保留']['A1'].value=='不可改变'
with ZipFile(p/'source.xlsx') as old,ZipFile(p/'chart-format.xlsx') as new:
 assert set(old.namelist())==set(new.namelist());changed=[n for n in old.namelist() if old.read(n)!=new.read(n)];assert set(changed)=={'xl/charts/chart1.xml','xl/charts/chart2.xml','xl/charts/chart3.xml','xl/charts/chart4.xml'},changed
 def xml(i):return etree.fromstring(new.read(f'xl/charts/chart{i}.xml'))
 def val(tree,path):return tree.find(path,ns).get('val')
 c=xml(1);assert val(c,'.//c:gapWidth')=='300';assert c.find('.//c:valAx/c:scaling/c:min',ns) is None;assert val(c,'.//c:valAx/c:scaling/c:max')=='30';assert c.find('.//c:valAx/c:majorGridlines',ns) is not None;assert val(c,'.//c:dLblPos')=='ctr';assert c.find('.//c:numFmt',ns).get('formatCode')=='0.00';assert c.find('.//c:ser/c:spPr/a:solidFill/a:srgbClr',ns).get('val')=='FF0000';assert c.find('.//c:ser/c:dPt/c:spPr/a:solidFill/a:srgbClr',ns).get('val')=='0070C0'
 for i in [2,3]:
  c=xml(i);assert val(c,'.//c:ser/c:explosion')=='30';assert val(c,'.//c:ser/c:dPt/c:explosion')=='55'
 assert val(xml(3),'.//c:holeSize')=='60';assert xml(4).find('.//c:dLbls/c:numFmt',ns).get('formatCode')=='0.0'
print(json.dumps({'ok':True,'changedParts':changed,'sha256':hashlib.sha256((p/'chart-format.xlsx').read_bytes()).hexdigest(),'sourceCellsPreserved':True,'independentChartFormatsVerified':True},ensure_ascii=False))
