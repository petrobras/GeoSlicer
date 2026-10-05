# Folder Monitor

Import a folder without loading it, and keep the listing in step with what is written into it.

Each dataset found inside becomes an ordinary node — a table, a scalar volume, a label map, a vector volume
— holding only a *sample* of the data: the first rows of a table, a downsampled read of an image. The
source stays on disk, and the full data is read on demand. Samples are cheap enough that a folder of any
size can be listed in a moment, and small enough that the scene stays light.

## Deferred loading

*Deferred loading* (checked by default) is what creates samples instead of loading everything. A deferred
node knows where it came from: the Explorer shows what it holds, how much of the original that is, and
offers **Refresh** (re-read the sample) and **Load full data / Load full resolution** (read everything into
a new node). Unchecking the option loads the folder eagerly instead.

Supported sources: TIFF/PNG/JPEG stacks (a folder of planes is one volume), multi-page TIFFs, NetCDF-4 and
HDF5, LBPM per-rank HDF5 frame folders, RAW volumes (geometry from the filename convention or from a
neighbouring LBPM `*.db`), and CSV/TSV tables — including whitespace-separated logs whose extension says
otherwise.

## Keeping in sync

*Keep in sync with the folder* watches it and lists datasets as they appear or change. Use it while an
acquisition or a simulation is still writing. A source that disappears is marked as unavailable rather
than deleted, because the usual reason is an unmounted share, not a decision to discard data.

## Time sequences (4D)

Numbered entries — `vis10000`, `recon_0`, `frame_0001.tif` — are offered as the frames of one time
sequence rather than as separate datasets. Patterns are suggested from the names actually present; the
field selector appears when a frame holds several (LBPM writes phase, pressure and velocity together).

A sequence is surfaced as a single proxy node, and selecting it in the Explorer shows the player:

- **back / play-pause / next**, with a configurable **step**;
- **loop** playback, and **follow latest** to track a folder that is still being written;
- a **1:N preview** of every frame, built in the background into a cache on disk, which is what keeps
  scrubbing smooth and memory flat regardless of frame count or size;
- **Load full resolution** for the frame you have settled on (at most a couple are kept in memory, and
  they fall back to the preview when evicted);
- **Reload frames** for frames that were rewritten in place.

Preview and full resolution share the same physical geometry, so promoting a frame changes the detail
without moving what you are looking at.
