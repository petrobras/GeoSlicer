# PoreStats test templates regeneration (PL-3053)

When the PL-3053 branch upgraded to a new Python / numpy / torch / sklearn
stack, every PoreStatsTest case that checks output against a template file
started to fail. The pipeline itself still worked — the outputs just drifted
slightly because the underlying math libraries and model runtimes are not
bit-for-bit compatible across versions.

This document records what was regenerated, how, and how much each template
moved from the previous committed version. It is intended to be read when
reviewing the regeneration commit.

The comparison was produced with `agent_tmp/diff_templates.py` against the
templates at HEAD (pre-regeneration) vs. the files currently on disk.

## How templates were regenerated

Each template was rebuilt by running
`src/modules/PoreStats/PoreStatsCLI/Libs/pore_stats/pore_stats.py` directly
with the same arguments the corresponding `PoreStatsTest` case drives through
the widget. No test logic changed; only the reference outputs were refreshed.

## Per-template summary

### NetCDF templates (pore instance masks, `int16` labels)

| Template | Pore pixels differing | Binary-mask diff | Pore count (old → new) | Notes |
|---|---|---|---|---|
| `bayesian_small_kernel_template` | 2,800 / 1.58M (0.18%) | 117 (0.007%) | 201 → 205 (+4) | Boundary noise from Bayesian `sbayes` model. |
| `bayesian_big_kernel_template` | 185 / 1.58M (0.01%) | 13 (0.001%) | 85 → 86 (+1) | Nearly identical. |
| `carbonate_u_net_template` | 20,876 / 1.58M (1.32%) | 2,190 (0.14%) | 465 → 564 (+99) | U-net less stable across torch versions than Bayesian. The +99 pores are mostly very small: most are in the existing rock area and the binary mask moved by only 0.14%. Tiny threshold-boundary pixels that used to belong to one blob now fragment into several. |
| `clean_resin_no_px_template` | 2,621 / 1.58M (0.17%) | 109 (0.007%) | 146 → 153 (+7) | |
| `clean_resin_px_template` | 4,516 / 1.58M (0.29%) | 136 (0.009%) | 197 → 202 (+5) | |
| `clean_resin_px_smart_reg_template` | same as above | | | Centralized and auto registration happen to produce identical output for this input — PX is naturally aligned. |
| `clean_resin_do_not_use_px_template` | same as `clean_resin_no_px` | | | Test's "don't use PX" branch behaves like "no PX at all" for this input. |
| `single_frag_template` | 180 / 1.58M (0.01%) | 63 (0.004%) | 96 → 97 (+1) | `max_frags=1` limits to one fragment; nearly identical. |
| `watershed_template` | 24,661 / 1.58M (1.56%) | 117 (0.007%) | 2 → 3 (+1) | Watershed labels the same set of pixels but partitions them slightly differently (the binary mask barely moved). |
| `no_spurious_template` | 70,663 / 1.49M (4.76%) | 10,739 (0.72%) | 669 → 763 (+94) | Largest change. U-net segmentation plus the re-pickled `RandomForestClassifier` (see `migrate_spurious_pkls.py`) combine here. The binary mask is still within ~0.7% of the old one. |

The "binary pore mask diff" column compares `Pores > 0` between old and new.
The low values there (≤ 0.15% everywhere except `no_spurious` at 0.72%) show
that the segmentation is picking the same rock pixels — most of the higher
"Pore pixels differing" numbers come from label renumbering when pore count
changes, not from actual pore placement drift.

### Sheet templates (`pores/…/{All,Groups}Stats_…_pores.xlsx`)

The sheets come from the `sbayes` run (same as `bayesian_small_kernel`), so the
same 201 → 205 pore count shows up here. Because there is no stable pore ID to
match rows across runs, the comparison uses aggregate statistics per column:

`AllStats_…`, top 5 per-column deltas:

| Column | Stat | Old | New | Delta |
|---|---|---|---|---|
| `ellipse_area (mm^2)` | max | 213.7 | 178.5 | 16.48% |
| `min_feret (mm)` | max | 6.49 | 5.47 | 15.70% |
| `ellipse_perimeter_over_ellipse_area (1/mm)` | min | 0.1382 | 0.1587 | 14.89% |
| `ellipse_area (mm^2)` | std | 21.01 | 19.18 | 8.68% |
| `ellipse_perimeter_over_ellipse_area (1/mm)` | median | 2.55 | 2.67 | 4.85% |

`GroupsStats_…` has 9 rows (bucket groups) in both versions; top deltas are
dominated by the same single-outlier effect as the LAS `max.las` (below).

### LAS templates (`pores/LAS/las_*.las`)

| File | Max relative diff across numeric curves |
|---|---|
| `las_max.las` | 16.48% |
| `las_mean.las` | 4.72% |
| `las_median.las` | 4.85% |
| `las_min.las` | 14.89% |
| `las_std.las` | 8.68% |

The large deltas on `las_max.las` (16.5%) and `las_min.las` (14.9%) come from
the same pore that was the ellipse-area max in the sheets (213.7 → 178.5 mm²).
"max" and "min" statistics are single-value and therefore the most sensitive
to any one pore changing shape across library versions; "mean" and "median"
track to within 5%.

## Regeneration provenance

The diff report above was produced by `agent_tmp/diff_templates.py`, comparing
templates extracted from HEAD (via `.git/lfs/objects/…`) against the
regenerated files on disk.

The CLI invocations were:

- Input datasets from `src/modules/PoreStats/Test/Resources/datasets/`.
- Models from the user's local
  `C:/ltrace/Models_Petro_updated/ThinSectionEnv/PoreStats/`: `bayes_3px/model.pth`
  (sbayes / Bayesian small kernel — also used by the sheets/LAS tests),
  `bayes_7px/model.pth` (bbayes / Bayesian big kernel),
  `carb_pore/model.pth` (U-net).
- All tests run with `pixel_size=0.1`, `--netcdf --exclude-ooids`, algorithm
  `islands` except `watershed_template` which uses `watershed`.
- `--keep-spurious` everywhere except `no_spurious_template` (`remove_spurious=True`).
- `--keep-residues` everywhere except the four `clean_resin_*` templates
  (`clean_resin=True`).
- `--use-px all` for `clean_resin_px*`; `none` elsewhere.
- `--reg-method auto` for `clean_resin_px_smart_reg`; `centralized` elsewhere.
- `--max-frags 1` for `single_frag_template`.
- `--no-sheets --no-las --no-images` for NetCDF-only templates.
- `--no-las --no-images` (keep sheets) for `sheets_template`.
- `--no-sheets --no-images` + `--no-las` omitted for `las_template`.
