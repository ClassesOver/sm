import pytest
from smart_reporting.report_editor.native_office import _pptx_arguments

def test_custom_shows_preserves_empty_list_and_repeated_page_order():
    assert _pptx_arguments({'kind':'editSlides','customShows':[]})['custom_shows']==[]
    shows=[{'id':'cs-new','name':'重点 <&>😀','slideIndices':[2,0,2]}]
    assert _pptx_arguments({'kind':'editSlides','customShows':shows})['custom_shows']==shows

@pytest.mark.parametrize('item',[{'id':'cs-a','name':'x','slideIndices':[True]},{'id':'cs-a','name':'x','slideIndices':[0],'path':'x'},{'id':'cs-a','name':'bad\x00','slideIndices':[0]}])
def test_custom_show_invalid_schema_is_rejected(item):
    with pytest.raises(ValueError):_pptx_arguments({'kind':'editSlides','customShows':[item]})
