"""Word 编辑候选也必须完整读取，不能只读取长块尾页绕过。"""

import pytest

from smart_reporting.report_editor.native_word_ai import NativeWordAITools
from smart_reporting.reporting.models import ReportingError


def test_word_edit_tool_requires_contiguous_full_read_before_proposal():
    tools = NativeWordAITools([{'blockId': 'p1', 'type': 'paragraph', 'text': '正文' * 15000,
        'expectedObjectSha256': 'a' * 64, 'allowedOperations': ['replaceParagraph']}])
    candidate = [{'kind': 'replaceParagraph', 'blockId': 'p1', 'text': '候选正文'}]
    tail = tools.read_blocks(['p1'], offset=24001)
    assert tail['nextOffset'] is None
    with pytest.raises(ReportingError, match='完整读取'):
        tools.propose_operations('未完整读完', candidate)
    tools.read_blocks(['p1'])
    with pytest.raises(ReportingError, match='完整读取'):
        tools.propose_operations('还差一个字符', candidate)
    tools.read_blocks(['p1'], offset=24000)
    assert tools.propose_operations('已读完', candidate)['operationCount'] == 1
