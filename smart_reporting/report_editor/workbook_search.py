"""Thin Node adapter for source JavaScript find_cells matching semantics."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_SEARCH_TIMEOUT_SECONDS = 5


def find_cell_indexes(cells: list[dict[str, Any]], *, query: str, regex: bool,
                      look_in: str, errors_only: bool, max_results: int) -> dict[str, Any]:
    request = {'cells': cells, 'query': query, 'regex': regex, 'look_in': look_in,
               'errors_only': errors_only, 'max_results': max_results}
    try:
        completed = subprocess.run(
            ['node', str(Path(__file__).with_suffix('.mjs'))],
            input=json.dumps(request, ensure_ascii=True, allow_nan=False),
            text=True, capture_output=True, timeout=_SEARCH_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError('workbook_ai_search_timeout') from error
    except OSError as error:
        raise ValueError('workbook_ai_search_unavailable') from error
    if completed.returncode:
        raise ValueError('workbook_ai_search_failed')
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError('workbook_ai_search_failed') from error
    if isinstance(result, dict) and result.get('error') in {'invalid_regex', 'invalid_query'}:
        raise ValueError('workbook_ai_search_invalid')
    if (not isinstance(result, dict) or not isinstance(result.get('indexes'), list)
            or type(result.get('truncated')) is not bool
            or len(result['indexes']) > max_results
            or any(type(index) is not int or not 0 <= index < len(cells) for index in result['indexes'])
            or result['indexes'] != sorted(set(result['indexes']))):
        raise ValueError('workbook_ai_search_failed')
    return result
