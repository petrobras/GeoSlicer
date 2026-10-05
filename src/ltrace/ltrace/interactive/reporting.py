"""The progress file and apply log the widget reads, and the phrasing every apply path shares."""

import json
import os
import threading

from humanize import naturalsize

from ltrace.interactive.ipc import safe_dump_json


def update_progress(path, progress, message):
    print(f"[{os.getpid()}] Progress {progress}%: {message}", flush=True)
    safe_dump_json({"progress": progress, "message": message}, path)


_APPLY_LOG_LOCK = threading.Lock()


def log_apply(path, message, **fields):
    """Append one line to the full apply's log. `fields` carries the step the ETA needs."""
    print(f"[{os.getpid()}] {message}", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The widget reads this file by byte offset, so newline="" to keep Windows from
    # translating to CRLF. The lock is needed because the fused apply writes from two
    # threads and a torn line is unparseable.
    with _APPLY_LOG_LOCK, open(path, "a", newline="") as f:
        f.write(json.dumps({"message": message, **fields}) + "\n")


def apply_plan_line(pieces, piece_shape, piece_bytes, threads, unit="slab"):
    """How a full apply was divided. `piece_shape` is (K, J, I); `piece_bytes` is one
    piece's design matrix."""
    K, J, I = piece_shape
    size = f"{I}x{J}x{K} ({naturalsize(piece_bytes, binary=True)} of features)"
    if pieces == 1:
        return f"Fits in a single {unit} of {size}, over {threads}"
    return f"Divided in {pieces} {unit}s, each with size {size}, over {threads}"


def _rate(voxels, seconds):
    return f"{voxels / seconds / 1e6:.1f} Mvoxel/s" if seconds > 0 else "-- Mvoxel/s"


def step_timing_line(label, voxels, seconds):
    """What one piece of work cost, as one wall-clock span -- the fused apply overlaps
    filtering and prediction, so they cannot be attributed separately."""
    return f"{label} - done in {seconds:.1f} s ({_rate(voxels, seconds)})"


def apply_timing_summary(voxels, total_seconds):
    return f"Applied to {voxels / 1e6:.0f} Mvoxels in {total_seconds:.1f} s ({_rate(voxels, total_seconds)})"
