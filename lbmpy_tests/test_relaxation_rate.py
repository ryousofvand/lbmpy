import pytest

from lbmpy.creationfunctions import create_lb_method
from lbmpy.relaxationrates import get_shear_relaxation_rate


def test_relaxation_rate():
    method = create_lb_method(stencil="D3Q19", method='mrt_raw',
                              relaxation_rates=[1 + i / 10 for i in range(19)])
    with pytest.raises(ValueError) as e:
        get_shear_relaxation_rate(method)
    assert 'Shear moments are relaxed with different relaxation' in str(e.value)

    method = create_lb_method(stencil="D2Q9", method='mrt_raw',
                              relaxation_rates=[1 + i / 10 for i in range(9)])
    assert get_shear_relaxation_rate(method) == 1.5
