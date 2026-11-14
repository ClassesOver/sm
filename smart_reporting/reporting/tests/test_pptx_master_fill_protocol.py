"""母版实色/none填充仍沿既有有限部件结构协议传递。"""
from copy import deepcopy
import pytest
from smart_reporting.report_editor.native_office import _pptx_arguments

FILL={'kind':'setFill','partPath':'ppt/slideMasters/slideMaster1.xml','spid':7,'fill':'#1A73E8'}

def test_master_fill_and_none_keep_other_part_edits_and_source_input():
    edits=[FILL,{**FILL,'partPath':'ppt/slideLayouts/slideLayout1.xml','fill':'none'}]
    source=deepcopy(edits)
    assert _pptx_arguments({'kind':'editSlides','masterElementEdits':edits})['master_element_edits']==source
    assert edits==source

@pytest.mark.parametrize('patch',[{'fill':'red'},{'fill':'#12345678'},{'fill':'#12345'},{'fill':None},{'fill':{'stops':[]}},{'fill':'NONE'},{'spid':True},{'spid':0},{'spid':4294967296},{'partPath':'ppt/slides/slide1.xml'},{'xml':'<a:solidFill/>'}])
def test_master_fill_rejects_unknown_colour_identity_and_client_xml(patch):
    with pytest.raises(ValueError):_pptx_arguments({'kind':'editSlides','masterElementEdits':[{**FILL,**patch}]})

@pytest.mark.parametrize('second',[FILL,{'kind':'delete','partPath':FILL['partPath'],'spid':7}])
def test_master_fill_rejects_duplicate_and_fill_delete_conflict(second):
    with pytest.raises(ValueError):_pptx_arguments({'kind':'editSlides','masterElementEdits':[FILL,second]})
