"""从CSV恢复登记的维度标量类型，保留NULL、空串及整数的区别。"""

from decimal import Decimal


def dimension_values(query, row):
    values = []
    for index, data_type in enumerate(query.dimension_types):
        marker, value = row[f"dimension_{index}_is_null"], row[f"dimension_{index}"]
        if marker not in ("0", "1"):
            raise ValueError("invalid dimension null marker")
        kind = data_type.upper().split("(", 1)[0].strip()
        if marker == "1":
            value = None
        elif kind in ("INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "LARGEINT"):
            value = int(value)
        elif kind in ("DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL"):
            value = Decimal(value)
            if not value.is_finite():
                raise ValueError("nonfinite dimension")
        elif kind in ("BOOL", "BOOLEAN"):
            if value.lower() not in ("true", "false", "0", "1"):
                raise ValueError("invalid boolean dimension")
            value = value.lower() in ("true", "1")
        values.append(value)
    return tuple(values)
