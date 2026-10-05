# Two-phase Simulation Diagnostics

Per-element inspection of a two-phase pore-network simulation. Written by the simulation,
read by a PySide2 viewer embedded in GeoSlicer.

## Where the code lives

Almost everything is in the `py_pore_flow` submodule (`src/submodules/py_pore_flow`, a
separate Bitbucket repo — changes there need a submodule pointer bump):

- `src/py_pore_flow/output/diagnostics.py` — `DiagnosticsWriter` dumps every property of
  every element each step into preallocated `np.memmap` chunk files
  (`diagnostics_<storer>_<chunk>.dat`), plus `info.dat` (element and per-cycle step counts),
  `step_scalars.dat` (`STEP_SCALAR_NAMES`: Pc and Sw once per step) and `network.npz`
  (static properties). Reading goes `Diagnostics` → `DiagnosticsCycles` →
  `DiagnosticsCycle` → `DiagnosticsCycleStep` over one shared `DiagnosticsFileCache`;
  `ChunkedRows` addresses a global step without concatenating chunks. Call
  `Diagnostics.close()` to release the mappings — Windows locks them and the directory moves
  on project save.
- `src/py_pore_flow/output/diagnostics_aggregate.py` — `AggregateDiagnosticsWriter` spools
  only the scalars its curated `DEFAULT_PAIRS` need, then at `close()` bins them into
  `(n_steps, n_bins)` sum and count matrices (`aggregates.npz`) and deletes the spool. A
  linear and a log bin set are stored per property (log only where it stays positive):
  neither spacing can be merged into the other. `DiagnosticsAggregates` reads them back and
  merges the fine bins down to the requested bin count. `diagnostics_manifest.json` records
  the level.
- `src/py_pore_flow/graphic/diagnostics/` — the viewer. `DiagnosticsWidget` builds the tabs
  the level supports; `DiagnosticsProperties` is the catalogue every view reads through
  (step and cycle loaders, the static network dump, the derived `CONVERSORS`).
  Tabs: `diagnostics_tabs.py` (tables), `diagnostics_element_widget.py` +
  `diagnostics_network_widget.py` (element view and the embedded VTK network),
  `diagnostics_crossplot_widget.py`, `diagnostics_heatmap_widget.py`.

On the GeoSlicer side: `src/modules/PoreNetworkKrelEda/PoreNetworkKrelEdaLib/diagnostics_container.py`
selects a `DirectoryNode` and hosts the widget in a dedicated Slicer layout (id 16001),
bridging PythonQt to PySide2 with `shiboken2.wrapInstance`.

## Levels

`diagnostics_level` (`src/ltrace/ltrace/pore_networks/pnflow_parameter_defs.py`) is `off`,
`basic` (aggregates only, Heatmap tab) or `complete` (raw data, all five tabs). It flows
through `pore_flow_subprocess.py` into `run_two_phase_simulation`. Only subprocess id 0
writes diagnostics (`without_diagnostics`); the CLI promotes that directory into a
`DirectoryNode`.

## Making changes

Add a per-step property: extend the `*_NDATA` count and the `save_state`/loader pair in
`diagnostics.py` — the combos pick it up automatically. Add a heatmap aggregate: append a
`(element_type, y_property, color_property)` triple to `DEFAULT_PAIRS`. The heatmap's X axis
is the step index, Pc or Sw (`X_AXIS_SOURCES`; the latter two are resampled onto a uniform
grid, since an ImageItem draws evenly spaced rows), and its three `Log` checkboxes cover the
X spacing, the Y bin spacing (`SCALE_LOG`, disabled when no log bins were stored) and
colouring by `log10`. `DIRECTIONAL_SPECS` derives the throat flow components and angles from
`pore.coords` and `throat.conns`; go through `zero_based_conns`, which guards the convention
— py_pore_flow holds 0-based pore indices, the GeoSlicer throat table 1-based labels. Tests:
`tests/unit/output/diagnostics*_test.py` and `tests/unit/graphic/` in the submodule,
`tests/unit/ltrace/pore_networks/test_diagnostics_level.py` here.
