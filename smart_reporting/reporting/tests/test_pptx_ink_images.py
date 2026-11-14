import base64,json
from io import BytesIO
import pytest
from PIL import Image
from smart_reporting.report_editor.native_office import _pptx_arguments

def ink():
    data=BytesIO();Image.new('RGBA',(2,2),'red').save(data,format='PNG')
    return dict(slideIndex=0,bytesBase64=base64.b64encode(data.getvalue()).decode(),extension='png',name='aislides-ink sample',descr=json.dumps(dict(v=1,tool='pen',color='C00000',width=2,points=[[2,2],[20,10]])),geometry=dict(x=-1,y=-1,width=30,height=20))

def test_ink_name_vector_and_edge_geometry_follow_native_images():
    image=ink()
    assert _pptx_arguments(dict(kind='editSlides',images=[image]))['native_images']==[image]

@pytest.mark.parametrize('patch',[{'name':'foreign'},{'descr':'broken'},{'extension':'jpg'},{'name':None},{'descr':'{}'}])
def test_ink_rejects_unreadable_or_foreign_identity(patch):
    with pytest.raises(ValueError):_pptx_arguments(dict(kind='editSlides',images=[{**ink(),**patch}]))
