from smart_reporting.reporting.workflow.runtime.standard_chart_numeric import is_finite_number


def test_is_finite_number_accepts_finite_builtin_numbers_only():
    assert is_finite_number(1)
    assert is_finite_number(1.5)
    assert not is_finite_number(True)
    assert not is_finite_number(float("inf"))
    assert not is_finite_number(float("nan"))
    assert not is_finite_number("1")
