import pickle
import numpy as np
import pandas as pd

from tqdm import tqdm
from scipy import integrate, interpolate, stats
from scipy.special import erf
import numericalunits as nu

# For loading data files
import os
import inspect
THIS_DIR = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
def data_file(path):
    """Convert path in wimprates' data directory to absolute path"""
    return os.path.join(THIS_DIR, 'data', path) 

##
# Halo model
##

# Local dark matter density
rho_dm = 0.3 * nu.GeV/nu.c0**2 /nu.cm**3 

# Most common velocity of WIMPs in the halo, relative to galactic center (asymptotic)
v_0 = 220 * nu.km/nu.s       

# Velocity of earth/sun relative to gal. center (eccentric orbit, so not equal to v_0)
v_earth = 232 * nu.km/nu.s   

# Galactic escape velocity
v_esc = 544 * nu.km/nu.s     

# Maximum dark matter velocity observable on earth
v_max = v_esc + v_earth

def observed_speed_dist(v):
    """Observed distribution of dark matter particle speeds on earth under the SHM
    See my thesis for derivation ;-)
    If you find a paper where this formula is written out explicitly, please let me know. 
    I spend a lot of time looking for this in vain.
    """
    # Normalization constant, see Lewin&Smith appendix 1a
    _w = v_esc/v_0
    k = erf(_w) - 2/np.pi**0.5 * _w * np.exp(-_w**2)

    # Maximum cos(angle) for this velocity, otherwise v0
    xmax = np.minimum(1, (v_esc**2 - v_earth**2 - v**2)/(2 * v_earth * v))
    
    y =  (k * v / (np.pi**0.5 * v_0 * v_earth) *
             (np.exp(-((v-v_earth)/v_0)**2) - 
              np.exp(-1/v_0**2 * (v**2 + v_earth**2 + 2 * v * v_earth * xmax))))
    
    # Zero if v > v_max
    try:
        len(v)
    except TypeError:
        # Scalar argument
        if v > v_max:
            return 0
        else:
            return y
        
    # Array argument
    y[v > v_max] = 0
    return y


##
# Detector properties
##

spin_isotopes = [
    # A, mass, J (nuclear spin), abundance
    # Data from Wikipedia (Jelle, 12 January 2018)
    (129, 128.9047794 * nu.amu, 1/2, 26.401e-2),
    (131, 130.9050824 * nu.amu, 3/2, 21.232e-2),   
]

# Load spin-dependent structure functions
with open(data_file('sd/structure_f_erec_xe.pkl'), mode='rb') as infile:
    s_data = pickle.load(infile)
s_energies = s_data['_energies'] * nu.keV
structure_functions = {}
for _k, _v in s_data.items():       # Don't use k, v; we use v later for velocity...
    if _k == '_energies':
        continue
    structure_functions[_k] = interpolate.interp1d(s_energies, _v,
                                                   bounds_error=False, fill_value=0)
      
# Standard atomic weight of target (averaged across all isotopes)
# Used for spin-indepdendent scattering
An = 131.293  
mn = An * nu.amu    # Mass of nucleus (not nucleon!)

def mu_nucleon(mw):
    """Wimp-nucleon reduced mass.
    :param mw: Wimp mass
    """
    return mw * nu.amu / (mw + nu.amu)

def mu_proton(mw):
    """Wimp-proton reduced mass.
    :param mw: Wimp mass
    """
    return mw * nu.mp / (mw + nu.mp)

def mu_neutron(mw):
    """Wimp-neutron reduced mass.
    :param mw: Wimp mass
    """
    return mw * nu.mn / (mw + nu.mn)

def mu_nucleus(mw, mn=mn):
    """Wimp-nucleus reduced mass
    :param mw: Wimp mass
    :param mn: Nucleus mass. Defaults to standard atomic mass.
    """
    return mw * mn / (mw + mn)

def e_max(mw, v, mn=mn):
    """Kinematic nuclear recoil energy maximum
    :param mw: Wimp mass
    :param mn: Nucleus mass. Defaults to standard atomic mass.
    """
    return 2 * mu_nucleus(mw, mn=mn)**2 * v**2 / mn

def spherical_bessel_j1(x):
    """Spherical Bessel function j1 according to Wolfram Alpha"""
    return np.sin(x)/x**2 + - np.cos(x)/x

@np.vectorize
def helm_form_factor_squared(erec, anucl=An):
    """Return Helm form factor squared from Lewin & Smith
    
    Lifted from Andrew Brown's code with minor edits
    
    :param erec: nuclear recoil energy
    """
    en = erec / nu.keV
    if anucl <= 0:
        raise ValueError("Invalid value of A!")

    # TODO: Rewrite this so it doesn't use its internal unit system and hardcoded constants...
    
    # First we get rn squared, in fm
    mnucl = nu.amu/(nu.GeV/nu.c0**2)    # Mass of a nucleon, in GeV/c^2
    pi = np.pi
    c = 1.23*anucl**(1/3)-0.60
    a = 0.52
    s = 0.9
    rn_sq = c**2 + (7.0/3.0) * pi**2 * a**2 - 5 * s**2
    rn = np.sqrt(rn_sq)  # units fm
    mass_kev = anucl * mnucl * 1e6
    hbarc_kevfm = 197327  # hbar * c in keV *fm (from Wolfram alpha)

    # E in units keV, rn in units fm, hbarc_kev units keV.fm
    # Formula is spherical bessel fn of Q=sqrt(E*2*Mn_keV)*rn
    q = np.sqrt(en*2.*mass_kev)
    qrn_over_hbarc = q*rn/hbarc_kevfm
    sph_bess = spherical_bessel_j1(qrn_over_hbarc)
    retval = 9. * sph_bess * sph_bess / (qrn_over_hbarc*qrn_over_hbarc)
    qs_over_hbarc = q*s/hbarc_kevfm
    retval *= np.exp(-qs_over_hbarc*qs_over_hbarc)
    return retval

def sigma_erec(erec, v, mw, sigma_nucleon, interaction='SI'):
    """Differential elastic WIMP-nucleus cross section (dependent on recoil energy and wimp-earth speed v)
    
    :param erec: recoil energy
    :param v: WIMP speed (earth/detector frame)
    :param mw: Mass of WIMP
    :param sigma_nucleon: WIMP-nucleon cross-section
    :param interaction: string describing DM-nucleus interaction. Options:
        'SI' for spin-independent scattering, equal coupling to protons and neutrons)
        'SD_n_xxx' for spin-dependent scattering
            n can be 'n' or 'p' for neutron or proton coupling (at first order)
            x can be 'central', 'up' or 'down' for theoretical uncertainty on structure function
    """
    if interaction == 'SI':
        # Still assumes heavy mediator? McCabe mentions this in his Bremsstrahlung paper
        sigma_nucleus = sigma_nucleon * (mu_nucleus(mw) / mu_nucleon(mw))**2 * An**2
        return sigma_nucleus / e_max(mw, v) * helm_form_factor_squared(erec, anucl=An)

    elif interaction.startswith('SD'):
        _, coupling, s_assumption = interaction.split('_')
            
        result = np.zeros_like(erec)
        for A, mn_isotope, J, abundance in spin_isotopes:
            s = structure_functions[(A, coupling, s_assumption)]
            # x isn't quite sigma_nucleus: you'd have to multilpy by structure(0), then divide by it in the next line
            # Obviously there's no point to this, so let's not.
            x = sigma_nucleon * 4 * np.pi * mu_nucleus(mw, mn=mn_isotope)**2 / (3 * mu_proton(mw)**2 * (2 * J + 1))
            result += abundance * x / e_max(mw, v, mn=mn_isotope) * s(erec)
            
        return result
    
    raise ValueError("Unsupported DM-nucleus interaction '%s'" % interaction)


##
# Elastic nuclear recoil
##

def vmin_elastic(erec, mw):
    """Minimum WIMP velocity that can produce a recoil of energy erec
    :param erec: recoil energy
    :param mw: Wimp mass
    """
    return np.sqrt(mn * erec / (2 * mu_nucleus(mw)**2))

def rate_elastic(erec, mw, sigma_nucleon, interaction='SI', progress_bar=False, **kwargs):
    """Differential rate per unit detector mass and recoil energy of elastic WIMP scattering 
    
    :param erec: recoil energy
    :param mw: WIMP mass
    :param sigma_nucleon: WIMP/nucleon cross-section
    :param interaction: string describing DM-nucleus interaction, see sigma_erec for options
    :param progress_bar: if True, show a progress bar during evaluation (if erec is an array)

    Further kwargs are passed to scipy.integrate.quad numeric integrator (e.g. error tolerance). 
    
    Analytic expressions are known for this rate, but they are not used here.
    See Andrew's code (or its python translation in laidbax.wimps) if you really need <1% error.
    """
    if isinstance(erec, (list, np.ndarray)) and len(erec):
        return np.array([rate_elastic(erec=e, mw=mw, sigma_nucleon=sigma_nucleon,
                                      interaction=interaction, progress_bar=progress_bar, **kwargs)
                        for e in (tqdm if progress_bar else lambda x: x)(erec)
                        ])
    
    v_min = vmin_elastic(erec, mw)
    
    if v_min >= v_max:
        return 0

    return rho_dm / mw * (1 / mn) * integrate.quad(
        lambda v: sigma_erec(erec, v, mw, sigma_nucleon, interaction) * v * observed_speed_dist(v),
        v_min, v_max, **kwargs
    )[0]

##
# Elastic nuclear recoil + Bremsstrahlung
##


# Load the X-ray form factor
def to_itp(fn):
    x, y = np.loadtxt(data_file('bs/' + fn), delimiter=',').T
    return interpolate.interp1d(x, y, fill_value='extrapolate')

f1 = to_itp('atomic_form_1')
f2 = to_itp('atomic_form_2')


def sigma_w_erec(w, erec, v, mw, sigma_nucleon, interaction='SI'):
    """Differential WIMP-nucleus Bremsstrahlung cross section.
    From Kouvaris/Pradler [arxiv:1607.01789v2], eq. 8
    
    :param w: Bremsstrahlung photon energy
    :param mw: WIMP mass
    :param erec: recoil energy
    :param v: WIMP speed (earth/detector frame)
    :param sigma_nucleon: WIMP/nucleon cross-section
    :param interaction: string describing DM-nucleus interaction. Default is 'SI' (spin-independent)
    
    TODO: check for wmax!
    """
    # X-ray form factor
    form_atomic = np.abs(f1(w / nu.keV) + 1j * f2(w / nu.keV))
    
    # Note mn -> mn c^2, Kouvaris/Pradtler and McCabe apparently use natural units...
    return (4 * nu.alphaFS / (3 * np.pi * w) * 
            erec / (mn * nu.c0**2) * 
            form_atomic**2 * 
            sigma_erec(erec, v, mw, sigma_nucleon, interaction))


def vmin_w(w, mw):
    """Minimum wimp velocity to emit a Bremsstrahlung photon w
    
    :param w: Bremsstrahlung photon energy
    :param mw: WIMP mass
    
    From Kouvaris/Pradler [arxiv:1607.01789v2], equation in text below eq. 10
    """
    return (2 * w / mu_nucleus(mw))**0.5


def erec_bound(sign, w, v, mw):
    """Bremsstrahlung scattering recoil energy kinematic limits
    From Kouvaris/Pradler [arxiv:1607.01789v2], eq. between 8 and 9, simplified by vmin (see above)
    
    :param sign: +1 to get upper limit, -1 to get lower limit
    :param w: Bremsstrahlung photon energy
    :param mw: WIMP mass
    :param v: WIMP speed (earth/detector frame)
    """
    return mu_nucleus(mw)**2 * v**2 / mn * \
          (1 - vmin_w(w, mw)**2 / (2 * v**2) + sign * (1 - vmin_w(w, mw)**2 / v**2)**0.5)


def sigma_w(w, v, mw, sigma_nucleon, interaction='SI'):
    """Differential Bremsstrahlung WIMP-nucleus cross section
    
    :param w: Bremsstrahlung photon energy
    :param v: WIMP speed (earth/detector frame)
    :param mw: Mass of WIMP
    :param sigma_nucleon: WIMP-nucleon cross-section
    :param interaction: string describing DM-nucleus interaction. Default is 'SI' (spin-independent)
    """
    return integrate.quad(lambda erec: sigma_w_erec(w, erec, v, mw, sigma_nucleon, interaction), 
                          erec_bound(-1, w, v, mw), 
                          erec_bound(+1, w, v, mw),
                         )[0]


def rate_bremsstrahlung(w, mw, sigma_nucleon, interaction='SI', progress_bar=False, **kwargs):
    """Differential rate per unit detector mass and recoil energy of Bremsstrahlung elastic WIMP-nucleus scattering 
    
    :param w: Bremsstrahlung photon energy
    :param mw: Mass of WIMP
    :param sigma_nucleon: WIMP/nucleon cross-section
    :param interaction: string describing DM-nucleus interaction. See sigma_erec for options
    :param progress_bar: if True, show a progress bar during evaluation (if w is an array)
    
    Further kwargs are passed to scipy.integrate.quad numeric integrator (e.g. error tolerance). 
    """
    # This is duplicated from rate_bremsstrahlung, and it's quite close to just adding a np.vectorize decorator
    # Hm....
    if isinstance(w, (list, np.ndarray)) and len(w):
        return np.array([rate_bremsstrahlung(w=e, mw=mw, sigma_nucleon=sigma_nucleon,
                                             interaction=interaction, progress_bar=progress_bar, **kwargs)
                        for e in (tqdm if progress_bar else lambda x: x)(w)
                        ])

    if vmin_w(w, mw) >= v_max:
        return 0

    return rho_dm / mw * (1 / mn) * integrate.quad(
        lambda v: sigma_w(w, v, mw, sigma_nucleon, interaction) * 
                    v * observed_speed_dist(v),
                    vmin_w(w, mw), v_max, **kwargs
    )[0]
