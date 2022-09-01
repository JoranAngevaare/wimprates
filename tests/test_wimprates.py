"""Simple tests to see that the results of the computations do not change.

If you do update a computation, you'll have to change the hardcoded reference
values here.

"""
import numericalunits as nu
import numpy as np

import wimprates as wr


opts = dict(mw=50, sigma_nucleon=1e-45)


def isclose(x, y):
    assert np.abs(x - y)/x < 1e-5


def test_elastic():
    ref = 33.19098343826968

    isclose(wr.rate_wimp_std(1, **opts), ref)

    # Test numericalunits.reset_units() does not affect results
    nu.reset_units(123)
    isclose(wr.rate_wimp_std(1, **opts), ref)

    # Test vectorized call
    energies = np.linspace(0.01, 40, 100)
    dr = wr.rate_wimp_std(energies, **opts)
    assert dr[0] == wr.rate_wimp_std(0.01, **opts)


def test_lightmediator():
    isclose(wr.rate_wimp_std(1, m_med=1e-3, **opts),
            0.0005502663384403058)


def test_spindependent():
    isclose(wr.rate_wimp_std(1, interaction='SD_n_central', **opts),
            0.00021779266679860948)


def test_migdal():
    isclose(wr.rate_wimp_std(1, detection_mechanism='migdal', **opts),
            0.2615654952709099)


def test_brems():
    isclose(wr.rate_wimp_std(1, detection_mechanism='bremsstrahlung', **opts),
            0.00017062652972332665)


def test_dme():
    isclose(
        wr.rate_dme(100* nu.eV, 4, 'd',
                    mw=nu.GeV/nu.c0**2, sigma_dme=4e-44 * nu.cm**2)
            * nu.kg * nu.keV * nu.day,
    2.232912243660405e-06)

def test_halo_scaling():
    #check that passing rho multiplies the rate correctly:
    ref = 33.19098343826968

    isclose(wr.rate_wimp_std(1,halo_model = wr.StandardHaloModel(rho_dm = 0.3 * nu.GeV/nu.c0**2 / nu.cm**3) , **opts), ref)

