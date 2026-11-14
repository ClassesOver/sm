import pytest
from smart_reporting.report_editor.native_office import _pptx_arguments
from .test_native_pptx_model3d_package import item, glb


def test_native_model_protocol_reaches_service_and_binds_identity():
    model=item()
    args=_pptx_arguments({'kind':'editSlides','modelInsertions':[model]})
    assert args['model_insertions']==[model]
    with pytest.raises(ValueError):
        _pptx_arguments({'kind':'editSlides','modelInsertions':[item(glb('https://example.invalid/a'))]})
    with pytest.raises(ValueError):
        _pptx_arguments({'kind':'editSlides','modelViews':[{'slideIndex':0,'elementId':'1','expectedSha256':'bad','rot':{'ax':0,'ay':0,'az':0},'posterBase64':model['posterBase64']}]})
