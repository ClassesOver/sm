"""背景原图复用入口只接收实际字节身份，不接收媒体路径。"""
import pytest
from smart_reporting.report_editor.native_office import _pptx_arguments

def record():
    return dict(sourceSlideIndex=0, expectedSha256='a'*64, expectedSize=100, slideIndices=[0,1], tile=True)

def test_background_reuse_is_forwarded_without_accepting_paths():
    item=record()
    assert _pptx_arguments({'kind':'editSlides','backgroundImageReuses':[item]})['background_image_reuses']==[item]

@pytest.mark.parametrize('patch',[{'mediaPath':'/tmp/foreign.png'},{'expectedSha256':'bad'},{'expectedSize':True},{'slideIndices':[0,0]},{'sourceSlideIndex':True},{'tile':'yes'}])
def test_background_reuse_rejects_invalid_identity_and_path(patch):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind':'editSlides','backgroundImageReuses':[{**record(),**patch}]})
