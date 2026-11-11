"""需核对真实 PDF 的编辑种类与必须保留实际产物的执行回执。"""
PDF_CONFIRMATION_KINDS=frozenset({'replaceText','insertText','transformExistingImage','createFormField','editFormFieldRequired','editFormWidget','arrangeFormWidgets','appendRadioWidget','editFormTextProperties'})
PDF_RECEIPT_KINDS=PDF_CONFIRMATION_KINDS|{'externalPages','removeFormWidget','setFormValue'}


def pdf_review_issues(receipt: dict) -> list[dict]:
    """附加复核元数据失效只产生告警，不能丢弃已核验身份的实际 PDF。"""
    issues = receipt.get('reviewIssues', [])
    if isinstance(issues, list) and all(
        isinstance(issue, dict)
        and type(issue.get('operationIndex')) is int and issue['operationIndex'] >= 0
        and all(isinstance(issue.get(key), str) for key in ('kind', 'fieldName', 'code', 'message'))
        and issue['code'] and issue['message']
        for issue in issues
    ):
        return issues
    return [{'operationIndex': 0, 'kind': 'pdfOutput', 'fieldName': '',
        'code': 'native_pdf_review_issues_invalid',
        'message': 'PDF 内容或版式复核回执无效；已保留实际生成文件，请人工核对。'}]
