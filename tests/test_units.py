import numpy as np
import pytest

from src.units import is_known_unit, m3_to_mm, mm_to_m3


def test_one_mm_on_one_ha_is_ten_m3():
    # 1 мм = 0.001 м; 1 га = 10 000 м²; 0.001 * 10 000 = 10 м³
    assert mm_to_m3(1, 1) == pytest.approx(10.0)


def test_hand_example_600mm_on_2ha():
    # 600 мм * 2 га * 10 = 12 000 м³
    assert mm_to_m3(600, 2) == pytest.approx(12_000.0)


def test_default_area_gives_m3_per_ha():
    # 500 мм за сезон = 5 000 м³/га
    assert mm_to_m3(500) == pytest.approx(5_000.0)


def test_round_trip_m3_to_mm():
    assert m3_to_mm(12_000, 2) == pytest.approx(600.0)
    values = np.array([0.0, 123.4, 950.0])
    assert m3_to_mm(mm_to_m3(values, 3.5), 3.5) == pytest.approx(values)


def test_m3_to_mm_rejects_zero_area():
    with pytest.raises(ValueError):
        m3_to_mm(100, 0)


def test_known_units():
    assert is_known_unit("ha")
    assert is_known_unit("m3")
    assert is_known_unit("mm")
    assert not is_known_unit("km3")  # объём храним только в м³
    assert not is_known_unit("гектар")
