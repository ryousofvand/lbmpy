import numpy as np
import pytest

from pystencils.backends.simd_instruction_sets import get_supported_instruction_sets
from lbmpy.scenarios import create_lid_driven_cavity


@pytest.mark.skipif(not get_supported_instruction_sets(), reason='cannot detect CPU instruction set')
def test_lbm_vectorization_short():
    print("Computing reference solutions")
    size1 = (64, 32)
    relaxation_rate = 1.8

    ldc1_ref = create_lid_driven_cavity(size1, relaxation_rate=relaxation_rate)
    ldc1_ref.run(10)

    ldc1 = create_lid_driven_cavity(size1, relaxation_rate=relaxation_rate,
                                    optimization={'vectorization': {'instruction_set': get_supported_instruction_sets()[-1],
                                                                    'assume_aligned': True,
                                                                    'nontemporal': True,
                                                                    'assume_inner_stride_one': True,
                                                                    'assume_sufficient_line_padding': False,
                                                                    }},
                                    fixed_loop_sizes=False)
    ldc1.run(10)


@pytest.mark.parametrize('instruction_set', get_supported_instruction_sets())
@pytest.mark.parametrize('aligned_and_padding', [[False, False], [True, False], [True, True]])
@pytest.mark.parametrize('nontemporal', [False, True])
@pytest.mark.parametrize('double_precision', [False, True])
@pytest.mark.parametrize('fixed_loop_sizes', [False, True])
@pytest.mark.longrun
def test_lbm_vectorization(instruction_set, aligned_and_padding, nontemporal, double_precision, fixed_loop_sizes):
    vectorization_options = {'instruction_set': instruction_set,
                              'assume_aligned': aligned_and_padding[0],
                              'nontemporal': nontemporal,
                              'assume_inner_stride_one': True,
                              'assume_sufficient_line_padding': aligned_and_padding[1]}
    time_steps = 100
    size1 = (64, 32)
    size2 = (666, 34)
    relaxation_rate = 1.8

    print("Computing reference solutions")
    ldc1_ref = create_lid_driven_cavity(size1, relaxation_rate=relaxation_rate)
    ldc1_ref.run(time_steps)
    ldc2_ref = create_lid_driven_cavity(size2, relaxation_rate=relaxation_rate)
    ldc2_ref.run(time_steps)

    optimization = {'double_precision': double_precision,
                    'vectorization': vectorization_options,
                    'cse_global': True,
                    }
    print("Vectorization test, double precision {}, vectorization {}, fixed loop sizes {}".format(
        double_precision, vectorization_options, fixed_loop_sizes))
    ldc1 = create_lid_driven_cavity(size1, relaxation_rate=relaxation_rate, optimization=optimization,
                                    fixed_loop_sizes=fixed_loop_sizes)
    ldc1.run(time_steps)
    np.testing.assert_almost_equal(ldc1_ref.velocity[:, :], ldc1.velocity[:, :])

    optimization['split'] = True
    ldc2 = create_lid_driven_cavity(size2, relaxation_rate=relaxation_rate, optimization=optimization,
                                    fixed_loop_sizes=fixed_loop_sizes)
    ldc2.run(time_steps)
    np.testing.assert_almost_equal(ldc2_ref.velocity[:, :], ldc2.velocity[:, :])


if __name__ == '__main__':
    test_lbm_vectorization()
