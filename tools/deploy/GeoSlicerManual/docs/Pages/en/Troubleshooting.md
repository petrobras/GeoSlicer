# Troubleshooting & FAQ

This page collects common questions, error messages, and workarounds reported by GeoSlicer users. If your issue isn't listed, please follow the [bug reporting](#reporting-bugs) instructions at the bottom of the page.

---

## Installation & First Run

### Where should I install GeoSlicer?

GeoSlicer is a self-contained application that ships as a `.exe` (Windows) or `.sfx` (Linux) archive.

!!! warning "Do NOT install on synchronized folders"
    Avoid installing GeoSlicer inside **Dropbox**, **OneDrive**, **Google Drive**, **iCloud**, or any corporate file-sync share. The sync agent fights the application files, causes intermittent corruption, and dramatically slows startup.

!!! warning "Do NOT install on a network / mapped drive"
    Mapped drives (e.g., `Z:\...`) introduce latency that makes startup and module loading painfully slow. They can also produce confusing errors at launch (for example, `OSError: [WinError 112] Espaço insuficiente no disco` when GeoSlicer probes a stale path).

!!! tip "Recommended setup"
    Install GeoSlicer on a **local SSD**, in a short path with no spaces (e.g., `C:\GeoSlicer-x.y.z` or `~/GeoSlicer-x.y.z`). On VMs with periodic user-folder wipes (e.g., CIRRUS-like environments), reinstall to a persistent location.

### GeoSlicer won't start, modules fail to import, or files appear corrupted

If you see a traceback during startup mentioning missing modules or paths that don't exist, the install is most likely corrupted or sitting on a flaky filesystem.

1. Delete the GeoSlicer folder entirely.
2. Re-download and re-extract from the official source.
3. Extract to a local SSD path (not OneDrive/Dropbox/network share).
4. Disconnect any mapped drives that are offline or out of space before launching — GeoSlicer probes recent paths at startup and may hang or crash on a dead path.

---

## General & Performance

### Why does GeoSlicer take so long to open?

Startup is affected by hardware, install location, and the recent-files history. Check these in order.

!!! warning "Power plan / Economy mode (very common)"
    Laptops often default to a power-saving profile that throttles the CPU well below its base clock (e.g., 1.6 GHz instead of 2.1 GHz). This dramatically slows GeoSlicer's load. Switch the OS power plan to **High Performance / Performance / Maximum Performance** and plug the machine into AC power.

**Other things to try:**

1. **Clear the recent-files list.** GeoSlicer inherits a 3D Slicer behavior where every entry in *recent files* is probed at startup. If any of those entries lived on a network share that is now slow or offline, startup can balloon from ~20 s to several minutes. Open *File → Recent → Clear History* and restart.
2. **Run from a local SSD** — not OneDrive/Dropbox, not a mapped network drive.
3. **Advanced — edit `slicerrc.py`:** In the GeoSlicer root directory, open `slicerrc.py` and comment out optional modules inside the `loadFoundations` function. Save before relaunching. Contact the dev team for a recommended snippet.

### My project loading is stuck (e.g., at 57%). What should I do?

Almost always network latency when opening a large project (90 GB+) stored on a standard network share.

- **Use fast storage.** Move heavy datasets to a high-performance filesystem (e.g., Lustre on a corporate cluster). It is dramatically faster than a typical research drive.
- **Trim the project.** Remove unused images, intermediate volumes, and old segmentations before saving.
- **Be patient on first open.** Even a healthy 90 GB project on the network may take ~1 hour to load. Check the logs to confirm the load is still progressing.
- **Reconnect to your session.** With GeoSlicer Cloud you can reconnect to the same session instead of starting over.

### How do I clear "stuck" or "zombie" remote jobs?

If a remote simulation hangs after a connection drop, or you see `paramiko.ssh_exception.SSHException: SSH session not active` in the console, the local job manifest is desynchronized from the cluster.

!!! warning
    Before deleting anything, verify that no simulations are actually running on the cluster (`squeue -u <your_user>` on the head node). Otherwise you will lose track of live results.

1. Close GeoSlicer.
2. Navigate to `%AppData%\Roaming\lib\remote\` on Windows or the equivalent path on Linux.
3. Manually delete `jobs.json`.
4. Reopen GeoSlicer and re-fetch any expected results.

You can also try the recovery snippet in the Python Console before deleting the file:

```python
def restart_jobs():
    from lib.remote.jobs import JobManager
    for uid in JobManager.jobs:
        JobManager.schedule(uid, "PROGRESS")
    print(JobManager.agenda.qsize())

restart_jobs()
```

### Memory is not being released

GeoSlicer keeps per-node undo/redo history, which can grow quickly on large volumes.

- Delete temporary nodes you no longer need from the Data module.
- Close the project (*File → Close Scene*) before loading a second large dataset.
- Use crops / sub-volumes when iterating on parameters.

---

## Data Import & Export

### "Wrong array size" error when loading a `.raw` file

This happens when the X/Y/Z dimensions or the data type (Int16, Float, UInt8, …) do not match the actual headerless content of the file — for example, after re-cropping a volume and forgetting that the data type changed to `float32`.

!!! tip
    Enable **Real-time update** in the RAW loader, set **Z to 1**, and iterate through X/Y and the data type until the preview slice looks correct. Only then set the final Z value.

Porosity maps are usually `float`, even when the binary volume they came from was integer.

### `AttributeError: 'NoneType' object has no attribute 'GetDimensions'`

This is a follow-on of the wrong-array-size error: because the RAW loader never produced a valid image, the post-processing step (auto-crop) crashes. Fix the dimensions and data type first; the preview will then work.

### Why is the "Export" button greyed out?

Known UI refresh bug.

- **Workaround:** Re-select the output directory or the volume node. Toggling the destination folder usually "wakes up" the button.
- Confirm the destination drive isn't a disconnected network mount.

### Encoding errors when importing CSV files (PcHg, SIRR data, …)

GeoSlicer expects CSV files in **UTF-8** with a consistent decimal/separator convention.

- **Fix the encoding:** Open the file in a text editor such as **Notepad++**, choose *Encoding → Convert to UTF-8*, and save.
- **Separator:** Excel commonly saves CSVs with `;` as the column separator and `,` as decimal. GeoSlicer's CSV loader expects **comma-separated** values with consistent numeric format. Re-save with `,` as the separator, or swap delimiters in a text editor.
- **Strip junk:** Remove trailing delimiters, merged headers, and any non-printable characters that Excel sometimes leaves behind.

### Why use the netCDF (`.nc`) format?

`.nc` is the recommended container for porosity maps and multi-scale (registered hi-res + low-res) datasets.

- It preserves spatial registration and metadata, so consistent crops and high-resolution simulations across different sessions just work.
- Medical CT `.nc` files are also supported by the standard Loader (a dedicated medical loader is on the roadmap).

### Sample names sent to the cluster: avoid spaces and dashes

When submitting jobs through the Microtom / Remote modules, file or sample names containing **spaces** or **leading `-`** are interpreted as shell flags and cause the job to fail silently. Stick to ASCII letters, digits, underscores, and dots.

---

## Visualization

### My image disappeared (turned black/invisible) after applying a filter

Some filters (e.g., **Gradient Anisotropic Diffusion**, **Median**) occasionally cause the "Gray" lookup table to reset or vanish on the filtered output. The histogram still looks correct — the issue is purely the colormap.

**Fix:** Open the **Volumes** module and change the **Lookup Table** from "Gray" to **"Viridis"** (or anything else). Switching back to "Gray" usually works after that.

### How do I remove the grid lines / boxes / slice intersections in the 3D view?

Those lines are slice intersections introduced by the newer 3D Slicer base.

- **Easiest:** In the toolbar of the 3D view, click the button to disable **Slice Intersections**. A small dropdown next to it lets you keep the slice visible while hiding the border.
- **Alternative:** Toggle the eye icon for the slice nodes in the Data module — note this also hides the slice plane itself in 3D.

### The 3D view color map doesn't change when I adjust the 2D sliders

In 3D Slicer (and GeoSlicer), 2D slice leveling and 3D volume rendering are handled separately — the histogram sliders below the 2D viewer **do not** retint the 3D volume.

**Solution:** Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> and search for **Volume Rendering**. Adjust the transfer functions (opacity/color) for the 3D model there.

### Quickly improve contrast to highlight a phase

Hold <kbd>Ctrl</kbd> and drag the mouse over a region of interest in a 2D slice. GeoSlicer auto-fits the window/level to that region, which makes mineral phases pop and makes manual thresholding much easier.

### Render a large segmentation in 3D without freezing GeoSlicer

"Show 3D" on a complex segmentation tries to mesh every segment, which can run out of memory on big volumes.

**Workaround:** In the Data tree, right-click the segmentation → **Export visible segments to binary labelmap** → select the resulting labelmap → check **Render in 3D**. This volume-renders the labelmap directly, skipping surface generation, and is much faster.

---

## Segmentation & Registration

### Correct workflow for manual Registration / Transform

When aligning "Dry" vs. "Saturated" samples:

!!! warning "Order matters"
    Always perform **Rotation first**, then **Translation**.

- Changing the axis or using the arrow buttons after a partial transform can reset values to origin if the steps are applied out of sequence. Follow the order strictly and click *Apply* before switching between rotation and translation.
- For final fine alignment, do a coarse manual placement and let the **automatic registration** do the last refinement — automatic alone rarely converges on heterogeneous rocks.
- Automatic registration is unreliable across resolutions (high-res vs. low-res of the same plug). Use coordinated metadata (e.g., bounding box from `.am` / `.nc`) instead.

### Can I use AI Segmenter for Rock Types / Textures?

Yes. The **Bayesian** and **Random Forest** segmenters are effective for partitioning rock types, facies, or zones of varying porosity. See the [AI Segmenter](/Volumes/Segmentation/Segmentation.md#ai-segmenter) section of the manual.

!!! warning "Memory"
    On large volumes (~1000³ and above) the feature step alone can require dozens of GB. Attempting to allocate 80+ TiB will crash the app. Use crops for training.

**Train on a crop, infer on the full volume:** Set the cropped image in *Input Image*, annotate, then set the full-resolution image in *Inference Image* (near *Apply to Full Image*) and click apply.

### Variogram Analysis parameters are greyed out

You must set a **SOI (Segment Of Interest)** to unlock the optional parameters. The constraint exists to avoid running variograms over background voxels, which can ruin the run.

Quick reference for the parameters:

| Parameter | Meaning |
|-----------|---------|
| Sampling rate | Fraction of voxels used; lower = faster, less accurate. |
| Maximum number of samples | Hard cap on points; trade speed for accuracy. |
| Number of lags | Like histogram bins on the X axis (distance). |
| Directional tolerance | Angular window around X/Y/Z. For dense micro-CT data, keep it small (< 60°). |
| Maximum distance | Manual cap (mm) on the variogram range. |

### My Inspector "Sphere diameter" values look wrong (huge)

Almost always a **voxel-size / spacing** mistake at import time. Even if the sample box in the 3D view looks right, an incorrect pixel size silently scales every length-derived metric.

- Re-check the volume's spacing in the Volumes module.
- Confirm the import used the correct units (µm vs. mm).
- Re-import if needed and re-run the Inspector.

Definitions of the main Inspector metrics:

- `voxelCount` — number of voxels in the pore.
- `volume` — `voxelCount × voxel volume`.
- `sphere_diameter_from_volume` — diameter of the sphere with the same volume as the pore.
- `ellipsoid_volume` — volume of the smallest ellipsoid sharing the pore's moment of inertia.
- `max_feret` — maximum Feret diameter.
- `pore_size_class` — categorical class (megapore / macropore / mesopore / micropore). Limits follow Choquette & Pray (1970), AAPG Bulletin 54, pp. 207–250.

### Coverage values in the Porosity Map report don't match the segment proportions

Known quirk: the *Coverage* lines in the porosity-map report are currently normalized over the **full volume**, not the SOI, while the segment-proportion table is normalized inside the SOI. They will only match when the SOI equals the full volume. A fix is on the roadmap.

---

## Simulations (PNM, Kabs, MICP, Krel)

### Kabs (Permeability) results are off by a factor of 10 (or more)

Almost always a **unit-consistency** issue:

- **Pressure drop** must match the simulator's expectation (typically **Pascal**). In some 2.8.x versions a pressure-drop scaling bug made the result depend linearly on the input pressure — fixed in **2.8.2**. Upgrade if you are below that.
- **Length units** in sub-resolution models should be **micrometers**, not millimeters. The default mean radius of 100 µm is too coarse for high-resolution imagery (e.g., 4 µm); set it close to your pixel size. Newer versions auto-read the volume's pixel size.
- **Washburn / capillary pressure (Hg):** use contact angle ≈ 140°, interfacial tension ≈ 470 mN/m, and stay consistent on length scale (µm vs. mm) when converting psi ↔ Pa.

### PNM simulation finished, but results are blank / zero

In order of likelihood:

1. **Porosity-map scale (2.8.0 only).** In 2.8.0 the extractor only accepted microporosity in the **[0..100]** range. If your map is in [0..1], multiply by 100 (Volume Calculator) or cast the array:
    ```python
    import numpy as np
    node = slicer.mrmlScene.GetFirstNodeByName('Porosity_map_100')
    arr  = slicer.util.arrayFromVolume(node).astype(np.uint8)
    slicer.util.addVolumeFromArray(arr, name='Porosity_map_int')
    ```
    Then run the extraction on `Porosity_map_int`. **2.8.1+** auto-detects the scale.
2. **All pores marked as sub-resolution / unresolved.** Affected 2.8.0; fixed in **2.8.1**. Upgrade.
3. **No percolation.** If there is no connected path from inlet to outlet, Kabs = 0 by construction.
4. **Remote / cluster glitch.** The cluster image may have been updated mid-run. Re-submit. "Completed with empty results" is the typical signature.
5. **Software version.** Confirm you are on the latest stable (**2.8.2+** for the pressure-drop fix, **2.8.7+** for additional MICP and remote fixes).

### My multi-scale PNM looks "pessimistic" (microporosity dominates)

Two common causes:

- **Sub-resolution model parameters in the wrong units** — micrometers, not millimeters.
- **Truncated Gaussian vs. MICP-fitted distribution:** if MICP returns an extremely fine pore-throat distribution, the subscale model overweights tiny pores. Switch to **Log-Truncated Gaussian** (2.8.7+) or relax the lower cutoff so the microporosity range overlaps the resolved-network range.

### Krel cycle 3 (second drainage) doesn't respect Swi

Known bug — in some 2.8.x builds the second drainage cycle drove water saturation toward 0 regardless of the Swi target. Fixed; confirm you are on **2.8.2+** and rerun.

### Points per pore / throat in the VTK output

- **Pore:** 50 points per sphere — `NumberOfPoints / 50` = number of pores.
- **Throat:** 12 points per throat — `NumberOfPoints / 12` = number of throats.
- The size of the spheres in the model cannot be edited interactively yet, but from **2.8.0** onward they are auto-rescaled relative to the pore radius.

### Automating simulations for multiple crops

The UI is designed for manual interaction, but you can drive it from the **Python Console**.

For **REV-style stacked / juxtaposed cubes**, modify the cropping loop in `PoreNetworkKabsREVCLI.py` (around line 151 of the upstream module — see the [public GeoSlicer repository on GitHub](https://github.com/petrobras/GeoSlicer)). You can also edit the file directly inside your installation:

```
GeoSlicer-x.y.z/lib/GeoSlicer-5.8/qt-scripted-modules/PoreNetworkKabsREV/PoreNetworkKabsREVCLI/PoreNetworkKabsREVCLI.py
```

For batch Kabs over arbitrary sub-volumes, ask the development team for a script template. **Pore Network KABS REV** in newer versions supports remote execution — use it for multi-scale jobs that would otherwise take hours locally.

### Where do I save / reload simulation parameters?

The explicit *Save parameters* button was removed because parameters are now **always auto-saved** alongside the simulation node. To recover an old setup, click **Load parameters** and pick the `simulation_parameters` node inside the previous completed simulation's folder; the form will repopulate.

---

## GeoSlicer Cloud / Remote

### Sessions hang at "Launching session…"

Usually a transient cluster filesystem issue (Lustre stripe contention, `/server` not mounting on some nodes).

- Retry after a couple of minutes.
- Check with the cluster admin whether the shared filesystem is accessible from the launcher node.
- The Cloud launcher v1.1+ has a fallback for these outages.

### Remote jobs end with "Completed" but no results returned

Most common reasons:

- A GeoSlicer cluster image update happened during the job (look at the submission timestamp).
- Job names containing **spaces** or **leading `-`** are eaten by shell parsing.
- The PNM remote path needs `partition=gpu` only, not `partition=gpu,cdi_server_gpu` — older configs may produce a job that sits forever in PENDING.

If you suspect a silent failure, leave the job in the GeoSlicer list (don't cancel or delete it) and contact the dev team so they can inspect the cluster artifacts.

### Running multiple GeoSlicer instances in one Cloud session

Today, Cloud opens one GeoSlicer per key per session. While doing slow processing in one project, you can dispatch a remote PNM/Kabs job, then close the project and open another — the job keeps running on the cluster. Multi-instance support (multiple GeoSlicers in the same Slurm session) is in development.

### Animations from "Create animation node" don't appear in the Remote

Known issue — animation export currently doesn't propagate back from Cloud. Run the animation locally for now.

### Run GeoSlicer Cloud full-screen

Cloud is a web app. In Edge / Chrome, hit <kbd>F11</kbd> or open the browser menu (⋮) and choose *Full screen*. On some browsers <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> is the shortcut. Hover the very top of the screen to bring the browser bar back, or hold <kbd>Esc</kbd> to exit.

---

## Citation & References

### How do I cite GeoSlicer in a paper?

Cite the project repository directly:

> Passos de Figueiredo, L., et al. (2025). *GeoSlicer — Integrated Open-Source Digital Rocks Platform* [Computer software]. https://github.com/petrobras/GeoSlicer

GitHub also auto-generates citations under **Cite this repository** on the right side of the repo page in BibTeX, APA, and other formats.

### Citing the Inspector pore-size classes

The class limits follow Choquette, P. W., & Pray, L. C. (1970), *Geologic Nomenclature and Classification of Porosity in Sedimentary Carbonates*, AAPG Bulletin 54, 207–250.
DOI: <https://doi.org/10.1306/5D25C98B-16C1-11D7-8645000102C1865D>

### Documentation for filters not described in the manual

The **Simple Filters** module wraps SimpleITK filters and inherits their documentation:

- [3D Slicer Simple Filters reference](https://slicer.readthedocs.io/en/latest/user_guide/modules/simplefilters.html)

---

## Reporting Bugs

If you encounter an error you cannot resolve:

1. Click the **Bug icon** (insect) on the right sidebar.
2. Add a short description of what you were doing and what you expected.
3. GeoSlicer generates a `.zip` containing recent logs — send it to the LTrace support team along with the project (`.mrml` + data folder) if it can be shared.
4. Whenever possible, prepare a **minimal reproduction**: a small crop of the data that still triggers the bug. Most issues get fixed within one or two release cycles once they're reproducible.

For longer discussions and to search past issues, see the public forum: <https://discourse.ltrace.com.br/>.
