import base64
from io import BytesIO
import pytest
from PIL import Image
from smart_reporting.report_editor.native_office import _pptx_arguments

def replacement():
    output=BytesIO();Image.new('RGBA',(2,2),'red').save(output,format='PNG')
    return dict(slideIndex=0,elementId='pic',expectedSha256='a'*64,expectedSize=99,bytesBase64=base64.b64encode(output.getvalue()).decode(),extension='png')

def test_cutout_keep_crop_true_forwards_through_existing_native_replacement():
    item={**replacement(),'keepSrcRect':True}
    assert _pptx_arguments(dict(kind='editSlides',pictureReplacements=[item]))['picture_replacements']==[item]

@pytest.mark.parametrize('value',[False,1,'true',None])
def test_cutout_keep_crop_rejects_non_true(value):
    with pytest.raises(ValueError):_pptx_arguments(dict(kind='editSlides',pictureReplacements=[{**replacement(),'keepSrcRect':value}]))
