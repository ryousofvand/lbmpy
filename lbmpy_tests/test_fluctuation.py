import numpy as np

from lbmpy.scenarios import create_channel


def test_fluctuating_generation_pipeline():
    ch = create_channel((40, 10), method='mrt3', relaxation_rates=[1.5, 1, 1], force=1e-5,
                        fluctuating={'temperature': 1e-9},
                        kernel_params={'time_step': 1, 'seed': 312},
                        optimization={'cse_global': True})

    ch.run(10)
    assert np.max(ch.velocity[:, :]) < 0.1
