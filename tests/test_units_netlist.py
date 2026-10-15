from __future__ import annotations

import pytest

from circuitloop.netlist import NetlistError, parse_sexp
from circuitloop.units import fmt_si, parse_value


@pytest.mark.parametrize(
    "text, value",
    [
        ("10k", 1e4),
        ("4k7", 4700),
        ("2R2", 2.2),
        ("100n", 1e-7),
        ("4.7u", 4.7e-6),
        ("1M", 1e6),
        ("1m", 1e-3),
        ("470", 470.0),
        ("10uF", 1e-5),
        ("1.5e3", 1500.0),
        (22, 22.0),
    ],
)
def test_parse_value(text, value):
    assert parse_value(text) == pytest.approx(value)


@pytest.mark.parametrize("bad", ["", "abc", "10x", "k10"])
def test_parse_value_rejects(bad):
    with pytest.raises(ValueError):
        parse_value(bad)


def test_fmt_si():
    assert fmt_si(4.7e-6, "F") == "4.7uF"
    assert fmt_si(1500, "Hz") == "1.5kHz"


def test_sexp():
    assert parse_sexp('(a (b "x y") c)') == ["a", ["b", "x y"], "c"]
    with pytest.raises(NetlistError):
        parse_sexp("(a (b)")
