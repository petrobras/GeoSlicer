import openpnm as op
import numpy as np


from commons.pore_networks.functions_simulation import (
    manual_valvatne_blunt,
    set_subresolution_conductance,
)


def test_set_subresolution_conductance():
    manual_valvatne_conductance_template = np.array((7.4713401e-17, 3.341455e-16, 1.534730e10))

    Nx, Ny, Nz = 4, 1, 1
    Lc = 1e-4
    pn = op.network.Cubic([Nx, Ny, Nz], spacing=Lc)
    pn.add_model_collection(op.models.collections.geometry.spheres_and_cylinders)
    pn.regenerate_models()
    pn["pore.diameter"] = np.ones(4) * 5e-5
    pn["throat.diameter"] = np.ones(3) * 2e-5
    pn["throat.mid_length"] = np.ones(3) * 5e-5
    pn["throat.conns_0_length"] = np.ones(3) * 2.5e-5
    pn["throat.conns_1_length"] = np.ones(3) * 2.5e-5
    pn["throat.cross_sectional_area"] = np.pi * (pn["throat.diameter"] / 2) ** 2

    pn["throat.shape_factor"] = np.ones(3) * 0.0796
    pn["throat.inscribed_diameter"] = pn["throat.diameter"]
    pn["throat.conns_0_length"] = pn["pore.diameter"][pn["throat.conns"][:, 0]]
    pn["throat.conns_1_length"] = pn["pore.diameter"][pn["throat.conns"][:, 1]]
    pn["pore.shape_factor"] = np.ones(4) * 0.0796
    pn["pore.extended_diameter"] = pn["pore.diameter"]
    manual_valvatne_blunt(pn)

    pn["pore.subresolution_porosity"] = np.ones(4) * 0.5
    pn["pore.volume"] = np.pi * pn["pore.diameter"] ** 3 / 6
    pn["pore.equivalent_diameter"] = pn["pore.diameter"]
    pn["throat.equivalent_diameter"] = pn["throat.diameter"]
    pn["throat.conns_0"] = pn["throat.conns"][:, 0]
    pn["throat.conns_1"] = pn["throat.conns"][:, 1]
    pn["throat.phases"] = (np.array([1, 1]), np.array([1, 2]), np.array([2, 2]))
    pn["throat.subresolution_porosity"] = np.array([1, 1, 0.5])
    pn["throat.total_length"] = np.array([0.01, 0.02, 0.03])

    pn["pore.xmin"] = np.ones(4, dtype=bool)
    pn["pore.xmax"] = np.ones(4, dtype=bool)
    pn["pore.ymin"] = np.ones(4, dtype=bool)
    pn["pore.ymax"] = np.ones(4, dtype=bool)
    pn["pore.zmin"] = np.ones(4, dtype=bool)
    pn["pore.zmax"] = np.ones(4, dtype=bool)

    def subresolution_function(phi):
        return 1.47e8

    set_subresolution_conductance(pn, subresolution_function, 1.0, 0.04)

    assert np.allclose(
        manual_valvatne_conductance_template,
        pn["throat.manual_valvatne_conductance"],
        atol=1e-05,
    )
