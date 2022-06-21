# microtom

> Manipulation of Microtomography images in python

## Installation

Install directly from the repo:

```bash
pip install git+http://git.ep.petrobras.com.br/DRP/microtom.git
```

## Usage

Describe how to use the package:

```bash
import microtom

ds = microtom.read_tarfile('LL36A_V011830H_LIMPA_P_41220nm.tar')
ds
```

```
<xarray.Dataset>
Dimensions:   (x: 1183, y: 972, z: 982)
Coordinates:
  * x         (x) float64 0.0 0.04125 0.08251 0.1238 ... 48.64 48.68 48.72 48.76
  * y         (y) float64 0.0 0.04126 0.08252 0.1238 ... 39.94 39.98 40.02 40.07
  * z         (z) float64 0.0 0.04126 0.08252 0.1238 ... 40.35 40.4 40.44 40.48
Data variables:
    microtom  (x, y, z) uint16 1756 1866 2208 2391 2383 ... 1894 2041 2015 1963
Attributes:
    well:         LL36A
    sample_name:  V011830H
    condition:    LIMPA
    sample_type:  P
    resolution:   0.04122
    dimx:         1183
    dimy:         972
    dimz:         982
    length:       48.76326
```

