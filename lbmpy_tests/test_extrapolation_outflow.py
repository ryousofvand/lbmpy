from pystencils.stencil import inverse_direction

from lbmpy.stencils import get_stencil
from lbmpy.advanced_streaming.utility import AccessPdfValues, get_timesteps
import pytest
import numpy as np

from pystencils.datahandling import create_data_handling
from lbmpy.boundaries import LatticeBoltzmannBoundaryHandling, SimpleExtrapolationOutflow, ExtrapolationOutflow
from lbmpy.creationfunctions import create_lb_method
from lbmpy.advanced_streaming.utility import streaming_patterns
from pystencils.slicing import get_ghost_region_slice

from itertools import product


@pytest.mark.parametrize('stencil', ['D2Q9', 'D3Q27'])
@pytest.mark.parametrize('streaming_pattern', streaming_patterns)
def test_pdf_simple_extrapolation(stencil, streaming_pattern):
    stencil = get_stencil(stencil)
    dim = len(stencil[0])
    values_per_cell = len(stencil)

    #   Field contains exactly one fluid cell
    domain_size = (3,) * dim
    for timestep in get_timesteps(streaming_pattern):
        dh = create_data_handling(domain_size, default_target='cpu')
        lb_method = create_lb_method(stencil=stencil)
        pdf_field = dh.add_array('f', values_per_cell=values_per_cell)
        dh.fill(pdf_field.name, np.nan, ghost_layers=True)
        bh = LatticeBoltzmannBoundaryHandling(lb_method, dh, pdf_field.name, streaming_pattern, target='cpu')

        #   Set up outflows in all directions
        for normal_dir in stencil[1:]:
            boundary_obj = SimpleExtrapolationOutflow(normal_dir, stencil)
            boundary_slice = get_ghost_region_slice(normal_dir)
            bh.set_boundary(boundary_obj, boundary_slice)

        pdf_arr = dh.cpu_arrays[pdf_field.name]

        #   Set up the domain with artificial PDF values
        # center = (1,) * dim
        out_access = AccessPdfValues(stencil, streaming_pattern, timestep, 'out')
        for cell in product(*(range(1, 4) for _ in range(dim))):
            for q in range(values_per_cell):
                out_access.write_pdf(pdf_arr, cell, q, q)

        #   Do boundary handling
        bh(prev_timestep=timestep)

        #   Check PDF values
        in_access = AccessPdfValues(stencil, streaming_pattern, timestep.next(), 'in')

        #   Inbound in center cell
        for cell in product(*(range(1, 4) for _ in range(dim))):
            for q in range(values_per_cell):
                f = in_access.read_pdf(pdf_arr, cell, q)
                assert f == q


def test_extrapolation_outflow_initialization_by_copy():
    stencil = get_stencil('D2Q9')
    values_per_cell = len(stencil)
    domain_size = (1, 5)

    streaming_pattern = 'esotwist'
    zeroth_timestep = 'even'

    pdf_acc = AccessPdfValues(stencil, streaming_pattern=streaming_pattern,
                              timestep=zeroth_timestep, streaming_dir='out')

    dh = create_data_handling(domain_size, default_target='cpu')
    lb_method = create_lb_method(stencil=stencil)
    pdf_field = dh.add_array('f', values_per_cell=values_per_cell)
    dh.fill(pdf_field.name, np.nan, ghost_layers=True)
    pdf_arr = dh.cpu_arrays[pdf_field.name]
    bh = LatticeBoltzmannBoundaryHandling(lb_method, dh, pdf_field.name,
                                          streaming_pattern=streaming_pattern, target='cpu')

    for y in range(1, 6):
        for j in range(values_per_cell):
            pdf_acc.write_pdf(pdf_arr, (1, y), j, j)

    normal_dir = (1, 0)
    outflow = ExtrapolationOutflow(normal_dir, lb_method, streaming_pattern=streaming_pattern,
                                   zeroth_timestep=zeroth_timestep)
    boundary_slice = get_ghost_region_slice(normal_dir)
    bh.set_boundary(outflow, boundary_slice)
    bh.prepare()

    blocks = list(dh.iterate())
    index_list = blocks[0][bh._index_array_name].boundary_object_to_index_list[outflow]
    assert len(index_list) == 13
    for entry in index_list:
        direction = stencil[entry["dir"]]
        inv_dir = stencil.index(inverse_direction(direction))
        assert entry[f'pdf'] == inv_dir
        assert entry[f'pdf_nd'] == inv_dir


def test_extrapolation_outflow_initialization_by_callback():
    stencil = get_stencil('D2Q9')
    values_per_cell = len(stencil)
    domain_size = (1, 5)

    streaming_pattern = 'esotwist'
    zeroth_timestep = 'even'

    dh = create_data_handling(domain_size, default_target='cpu')
    lb_method = create_lb_method(stencil=stencil)
    pdf_field = dh.add_array('f', values_per_cell=values_per_cell)
    dh.fill(pdf_field.name, np.nan, ghost_layers=True)
    bh = LatticeBoltzmannBoundaryHandling(lb_method, dh, pdf_field.name,
                                          streaming_pattern=streaming_pattern, target='cpu')

    normal_dir = (1, 0)
    density_callback = lambda x, y: 1
    velocity_callback = lambda x, y: (0, 0)
    outflow = ExtrapolationOutflow(normal_dir, lb_method,
                                   streaming_pattern=streaming_pattern,
                                   zeroth_timestep=zeroth_timestep,
                                   initial_density=density_callback,
                                   initial_velocity=velocity_callback)
    boundary_slice = get_ghost_region_slice(normal_dir)
    bh.set_boundary(outflow, boundary_slice)
    bh.prepare()

    weights = [w.evalf() for w in lb_method.weights]

    blocks = list(dh.iterate())
    index_list = blocks[0][bh._index_array_name].boundary_object_to_index_list[outflow]
    assert len(index_list) == 13
    for entry in index_list:
        direction = stencil[entry["dir"]]
        inv_dir = stencil.index(inverse_direction(direction))
        assert entry[f'pdf_nd'] == weights[inv_dir]
