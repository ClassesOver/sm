import re


def normalize_data_type(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()
