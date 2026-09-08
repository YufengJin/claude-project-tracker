import pytest
from calc import add, divide


def test_add():
    assert add(2, 3) == 5


def test_divide_exact():
    assert divide(6, 3) == 2


def test_divide_fraction():
    assert divide(7, 2) == 3.5


def test_divide_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
