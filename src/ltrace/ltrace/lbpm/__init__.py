"""LBPM (https://github.com/opm/lbpm) support: configuration, execution planning and result parsing.

Deliberately free of ``slicer``/``qt``/``vtk`` imports so it can be unit-tested headlessly and reused
outside the application. The Slicer-facing glue lives in ``ltrace.slicer.lbpm``.
"""
