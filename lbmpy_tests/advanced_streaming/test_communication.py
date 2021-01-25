import pystencils as ps

import numpy as np

from lbmpy.stencils import get_stencil
from pystencils.slicing import get_slice_before_ghost_layer, get_ghost_region_slice
from lbmpy.creationfunctions import create_lb_update_rule
from lbmpy.advanced_streaming.communication import get_communication_slices, _fix_length_one_slices, \
    LBMPeriodicityHandling
from lbmpy.advanced_streaming.utility import streaming_patterns, Timestep

import pytest


@pytest.mark.parametrize('stencil', ['D2Q9', 'D3Q15', 'D3Q19', 'D3Q27'])
@pytest.mark.parametrize('streaming_pattern', streaming_patterns)
@pytest.mark.parametrize('timestep', [Timestep.EVEN, Timestep.ODD])
def test_slices_not_empty(stencil, streaming_pattern, timestep):
    stencil = get_stencil(stencil)
    dim = len(stencil[0])
    q = len(stencil)
    arr = np.zeros((4,) * dim + (q,))
    slices = get_communication_slices(stencil, streaming_pattern=streaming_pattern, prev_timestep=timestep,
                                      ghost_layers=1)
    for _, slices_list in slices.items():
        for src, dst in slices_list:
            assert all(s != 0 for s in arr[src].shape)
            assert all(s != 0 for s in arr[dst].shape)


@pytest.mark.parametrize('stencil', ['D2Q9', 'D3Q15', 'D3Q19', 'D3Q27'])
@pytest.mark.parametrize('streaming_pattern', streaming_patterns)
@pytest.mark.parametrize('timestep', [Timestep.EVEN, Timestep.ODD])
def test_src_dst_same_shape(stencil, streaming_pattern, timestep):
    stencil = get_stencil(stencil)
    dim = len(stencil[0])
    q = len(stencil)
    arr = np.zeros((4,) * dim + (q,))
    slices = get_communication_slices(stencil, streaming_pattern=streaming_pattern, prev_timestep=timestep,
                                      ghost_layers=1)
    for _, slices_list in slices.items():
        for src, dst in slices_list:
            src_shape = arr[src].shape
            dst_shape = arr[dst].shape
            assert src_shape == dst_shape


@pytest.mark.parametrize('stencil', ['D2Q9', 'D3Q15', 'D3Q19', 'D3Q27'])
def test_pull_communication_slices(stencil):
    stencil = get_stencil(stencil)

    slices = get_communication_slices(
        stencil, streaming_pattern='pull', prev_timestep=Timestep.BOTH, ghost_layers=1)
    for i, d in enumerate(stencil):
        if i == 0:
            continue

        for s in slices[d]:
            if s[0][-1] == i:
                src = s[0][:-1]
                dst = s[1][:-1]
                break

        inner_slice = _fix_length_one_slices(get_slice_before_ghost_layer(d, ghost_layers=1))
        inv_dir = (-e for e in d)
        gl_slice = _fix_length_one_slices(get_ghost_region_slice(inv_dir, ghost_layers=1))
        assert src == inner_slice
        assert dst == gl_slice


@pytest.mark.parametrize('stencil_name', ['D2Q9', 'D3Q15', 'D3Q19', 'D3Q27'])
def test_optimised_and_full_communication_equivalence(stencil_name):
    target = 'cpu'
    stencil = get_stencil(stencil_name)
    dim = len(stencil[0])
    domain_size = (4, ) * dim

    dh = ps.create_data_handling(domain_size, periodicity=(True, ) * dim,
                                 parallel=False, default_target=target)

    pdf = dh.add_array("pdf", values_per_cell=len(stencil), dtype=np.int64)
    dh.fill("pdf", 0, ghost_layers=True)
    pdf_tmp = dh.add_array("pdf_tmp", values_per_cell=len(stencil), dtype=np.int64)
    dh.fill("pdf_tmp", 0, ghost_layers=True)

    gl = dh.ghost_layers_of_field("pdf")

    num = 0
    for idx, x in np.ndenumerate(dh.cpu_arrays['pdf']):
        dh.cpu_arrays['pdf'][idx] = num
        dh.cpu_arrays['pdf_tmp'][idx] = num
        num += 1

    ac = create_lb_update_rule(stencil=stencil,
                               optimization={"symbolic_field": pdf,
                                             "symbolic_temporary_field": pdf_tmp},
                               kernel_type='stream_pull_only')
    ast = ps.create_kernel(ac, target=dh.default_target, cpu_openmp=True)
    stream = ast.compile()

    full_communication = dh.synchronization_function(pdf.name, target=dh.default_target, optimization={"openmp": True})
    full_communication()

    dh.run_kernel(stream)
    dh.swap("pdf", "pdf_tmp")
    pdf_full_communication = np.copy(dh.cpu_arrays['pdf'])

    num = 0
    for idx, x in np.ndenumerate(dh.cpu_arrays['pdf']):
        dh.cpu_arrays['pdf'][idx] = num
        dh.cpu_arrays['pdf_tmp'][idx] = num
        num += 1

    optimised_communication = LBMPeriodicityHandling(stencil=stencil, data_handling=dh, pdf_field_name=pdf.name,
                                                     streaming_pattern='pull')
    optimised_communication()
    dh.run_kernel(stream)
    dh.swap("pdf", "pdf_tmp")

    if dim == 3:
        for i in range(gl, domain_size[0]):
            for j in range(gl, domain_size[1]):
                for k in range(gl, domain_size[2]):
                    for f in range(len(stencil)):
                        assert dh.cpu_arrays['pdf'][i, j, k, f] == pdf_full_communication[i, j, k, f], print(f)
    else:
        for i in range(gl, domain_size[0]):
            for j in range(gl, domain_size[1]):
                for f in range(len(stencil)):
                    assert dh.cpu_arrays['pdf'][i, j, f] == pdf_full_communication[i, j, f]
