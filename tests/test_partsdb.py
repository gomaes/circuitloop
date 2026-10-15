from __future__ import annotations

import pytest

from circuitloop.partsdb import PartsDBError, load_db, load_file


def test_bundled_db_loads():
    db = load_db(dirs=None)
    for key in ("NE555", "LM358", "LM2940CT-5.0", "R_1/4W", "1N4007", "LED_RED_5MM"):
        assert key in db
    assert all(p.ratings for p in db.parts.values())


def test_every_bundled_part_is_simulatable():
    db = load_db()
    assert [k for k, p in db.parts.items() if p.spice is None] == []


def test_invalid_rating_pin(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text("""
BAD:
  description: d
  kind: resistor
  package: axial_400
  footprint: x
  mpn: x
  pins: {1: {name: A}, 2: {name: B}}
  ratings: [{type: voltage, pins: [1, 3], max: 5}]
""")
    with pytest.raises(PartsDBError, match="unknown pin"):
        load_file(f)


def test_part_needs_ratings(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text("""
BAD:
  description: d
  kind: resistor
  package: axial_400
  footprint: x
  mpn: x
  pins: {1: {name: A}, 2: {name: B}}
  ratings: []
""")
    with pytest.raises(PartsDBError):
        load_file(f)


def test_project_overrides(tmp_path):
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "local.yaml").write_text("""
MYPART:
  description: custom
  kind: ic
  package: dip8
  footprint: Package_DIP:DIP-8_W7.62mm
  mpn: X
  pins: {1: {name: A, type: power_in}, 2: {name: B, type: power_in}}
  ratings: [{type: voltage, pins: [1, 2], max: 5}]
""")
    db = load_db(tmp_path)
    assert "MYPART" in db and "NE555" in db
