# Pore Scale Modelling

Configure, run and read an [LBPM](https://github.com/opm/lbpm) colour simulation — two-phase flow through
a segmented rock image — from inside GeoSlicer.

## Case

A case is a folder holding LBPM's input database (`waterflow.db`) and the image it reads. Selecting a
folder without one creates it with documented defaults. Selecting an input image does not change the case
by itself — reusing a case keeps the image it already reads until you press **Write image into the case**.
That saves the image as the headerless RAW file LBPM expects, fills in the domain size, the process grid,
the voxel length and the label mapping to match — the part that is easy to get wrong by hand — and saves
`waterflow.db`.

## Configuration

The form exposes the parameters that are usually tuned: relaxation times and densities, surface tension
and interface width, inlet flux, wetting affinity, analysis and visualization intervals, and the flow
adaptor's steady-state controls. It also shows which image the case reads and its size. Saving preserves
the file's comments and layout, rewriting only the values that changed.

For anything the form does not cover, **Edit in text editor** saves the form into `waterflow.db` and opens
the file in the system's text editor. Save it there and press **Reload from file** to bring the changes
back into the module. If the file was changed outside GeoSlicer and not reloaded, saving, writing an image
or running asks first whether to reload it or overwrite it, so edits made in the editor are never lost
silently.

## Execution

*Run on* chooses where the simulation happens. **Automatic** prefers a configured cluster and falls back to
this computer; the cluster path submits through SLURM, the local path runs the simulator detached. Either
way the run becomes a managed job: progress is reported, it can be cancelled, and it survives closing and
reopening the application (see the Job Monitor). Local runs need LBPM installed — point *LBPM program* at
the executable or at its Apptainer/Singularity image if it is not on the `PATH`.

On a cluster the job is submitted with the script LBPM is run with by hand on Atena. A CPU run asks for one
core per process. A GPU run (*Use GPUs*) asks for one GPU and two cores per process on nodes of its own, and
pins each process with `mpirun`. What the cluster runs LBPM from — its container image, the folders bound
into it, the environment modules — is set with the account, partition and walltime under *Settings…*, and
starts out as Atena's.

Every run gets its own `simNNN` folder inside the case, so results never mix.

## Monitoring

While the simulation writes its frames, *Create a time sequence for this run* surfaces them as a time
sequence (see the Folder Monitor module) and follows the newest one. Frames are shown from a downsampled
preview, so watching a running simulation costs neither the memory nor the wait that loading the frames
themselves would.

Starting another run clears the player and the report, so nothing on screen belongs to an earlier run.
Leave the checkbox on to have each run tracked as it starts, or turn it off and press **Track simNNN now**
when you want to watch it. A cluster run writes into its copy of the case on the shared folder, so that is
the folder tracked and reported; `simNNN/geoslicer_run.json` records where it is, so selecting the case
again later still finds it.

## Results

The report reads the simulation's own logs — `timelog.csv` and `subphase.csv` — and shows the endpoints
plus the curves that describe the flow: relative permeability against saturation, saturation and capillary
pressure histories, interfacial area, and the Euler characteristic of each phase. **Create table nodes**
puts the same data in the scene for plotting in Charts or exporting. It works on a run in progress too.
