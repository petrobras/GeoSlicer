"""
Render a multi-page PDF explaining how a segmentation preview was computed,
from a debug capture written by ltrace.interactive.seg_consumer
(`debug_capture.npz`).

The capture records the REAL preview computation (the consumer runs its normal
code path with a capture sink), so the report reflects production behavior.

A capture is tagged 2D or 3D. The 3D report is intentionally simpler: the
preview always covers a single slice (the one being viewed), so it just shows
each feature on that preview plane plus the resulting segmentation (no
whole-image overview or training-coverage map).

2D pages:
  - Overview: the source thumbnail with the training annotation points, the
    requested preview rectangle, and the region the preview path actually
    touched (a filtered sample rect for the contiguous branch, or the sampled
    output grid for the large-region / pyramid branch), plus a text box that
    explains which branch ran and why.
  - Feature pages: one row per feature, one column per input image, drawn at (at
    least) the preview's native resolution. Each input image is shown as a single
    picture: RGB inputs render as RGB feature views, single-channel inputs as
    grayscale. Stacks of co-registered images (e.g. three RGB thin sections, or
    three single-channel logs) show one image per column for every feature.
  - Result: the predicted labelmap and the uncertainty overlay.

PDF is the natural format here: multi-page, portable, embeds the per-feature
rasters at full resolution, and opens anywhere. (A folder of PNGs or a
self-contained HTML page would also work; PDF wins for a single shareable file.)

Usable standalone for offline iteration:
    python seg_debug_render.py debug_capture.npz [out.pdf] [images_per_page]
"""

import json
import sys
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patches
from matplotlib.backends.backend_pdf import PdfPages

# Page geometry (inches). Letter width; margins leave room for titles.
PAGE_W = 8.5
MARGIN = 0.45
AXES_W = PAGE_W - 2 * MARGIN
TITLE_H = 0.5  # vertical space reserved per panel title
BASE_DPI = 150  # floor; bumped per page so embedded rasters are never below native


def _scalar(capture, key, default=None):
    if key not in capture:
        return default
    value = capture[key]
    return value.item() if getattr(value, "ndim", None) == 0 else value


def _as_str(value, default="?"):
    if value is None:
        return default
    return value.decode() if isinstance(value, bytes) else str(value)


def _normalize01(img):
    """Min-max an arbitrary-range plane into [0, 1] for display (flat -> zeros)."""
    img = np.asarray(img, dtype=np.float32)
    lo, hi = float(np.min(img)), float(np.max(img))
    if hi <= lo:
        return np.zeros_like(img)
    return (img - lo) / (hi - lo)


def _image_display(planes):
    """
    Turn ONE input image's (channels, h, w) planes into something imshow draws:
      - 1 channel  -> (h, w) grayscale, viridis colormap
      - 3 channels -> (h, w, 3) RGB (jointly normalized to keep color relations)
      - otherwise  -> channels tiled side by side, grayscale
    Returns (array, cmap).
    """
    n_channels = planes.shape[0]
    if n_channels == 1:
        return _normalize01(planes[0]), "viridis"
    if n_channels == 3:
        rgb = np.stack([planes[c] for c in range(3)], axis=-1)
        return _normalize01(rgb), None
    sep = np.full((planes.shape[1], 4), np.nan, dtype=np.float32)
    tiles = []
    for c in range(n_channels):
        if c:
            tiles.append(sep)
        tiles.append(_normalize01(planes[c]))
    return np.concatenate(tiles, axis=1), "viridis"


def _split_into_images(feature_planes, image_channels):
    """
    Split a feature's flat channel stack (total_channels, h, w) into one display
    per input image, using the per-image channel counts (in the same order the
    source channels were stacked). Returns a list of (array, cmap).
    """
    images = []
    offset = 0
    for count in image_channels:
        images.append(_image_display(feature_planes[offset : offset + count]))
        offset += count
    return images


def _required_dpi(native_widths, axis_width):
    """DPI so the widest cell embeds at least its native pixels across `axis_width` inches."""
    widest = max(native_widths) if native_widths else 1
    return max(BASE_DPI, int(np.ceil(1.1 * widest / max(axis_width, 0.1))))


def _image_page(pdf, panels):
    """
    Render `panels` (list of dicts: array, cmap, title, optional draw) stacked
    vertically on one page, each at native resolution. `draw(ax)` may add
    overlays after the image is shown.
    """
    heights = []
    native_widths = []
    for panel in panels:
        arr = panel["array"]
        h, w = arr.shape[0], arr.shape[1]
        native_widths.append(w)
        heights.append(AXES_W * (h / w) + TITLE_H)

    fig_h = sum(heights) + 2 * MARGIN
    fig = plt.figure(figsize=(PAGE_W, fig_h))
    gs = fig.add_gridspec(
        len(panels),
        1,
        height_ratios=heights,
        hspace=0.18,
        left=MARGIN / PAGE_W,
        right=1 - MARGIN / PAGE_W,
        top=1 - MARGIN / fig_h,
        bottom=MARGIN / fig_h,
    )
    for k, panel in enumerate(panels):
        ax = fig.add_subplot(gs[k])
        cmap = panel.get("cmap")
        ax.imshow(panel["array"], cmap=cmap, interpolation="nearest")
        ax.set_title(panel.get("title", ""), fontsize=11)
        ax.set_axis_off()
        if panel.get("draw"):
            panel["draw"](ax)
    pdf.savefig(fig, dpi=_required_dpi(native_widths, AXES_W))
    plt.close(fig)


def _feature_page(pdf, blocks, image_names):
    """
    Render `blocks` (list of {name, images: [(array, cmap), ...]}) as a grid:
    one row per feature, one column per input image, every cell at native
    resolution. The feature name labels the row; image names title the columns
    on the first row.
    """
    ncols = max(len(block["images"]) for block in blocks)
    cell_w = AXES_W / ncols
    # Row height tracks the tallest cell in that row (cells share aspect closely).
    row_heights = []
    native_widths = []
    for block in blocks:
        tallest = 0.0
        for array, _ in block["images"]:
            h, w = array.shape[0], array.shape[1]
            native_widths.append(w)
            tallest = max(tallest, cell_w * (h / w))
        row_heights.append(tallest + TITLE_H)

    fig_h = sum(row_heights) + 2 * MARGIN
    fig = plt.figure(figsize=(PAGE_W, fig_h))
    gs = fig.add_gridspec(
        len(blocks),
        ncols,
        height_ratios=row_heights,
        hspace=0.28,
        wspace=0.08,
        left=MARGIN / PAGE_W,
        right=1 - MARGIN / PAGE_W,
        top=1 - MARGIN / fig_h,
        bottom=MARGIN / fig_h,
    )
    for r, block in enumerate(blocks):
        for c in range(ncols):
            ax = fig.add_subplot(gs[r, c])
            if c < len(block["images"]):
                array, cmap = block["images"][c]
                ax.imshow(array, cmap=cmap, interpolation="nearest")
                if r == 0 and c < len(image_names):
                    ax.set_title(image_names[c], fontsize=10)
            # Keep the feature name as a row label on the first column; hide ticks
            # and frame but leave the label visible (set_axis_off would drop it).
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            if c == 0:
                ax.set_ylabel(block["name"], fontsize=10, rotation=90, labelpad=8)
    pdf.savefig(fig, dpi=_required_dpi(native_widths, cell_w))
    plt.close(fig)


def _annotation_rgba(overlay):
    """
    Turn a thumbnail-resolution label overlay (0 = unannotated, c+1 = class c)
    into an RGBA image: each class gets a distinct opaque-ish color, unannotated
    pixels are fully transparent. Returns (rgba, {class: color}) for the legend.
    """
    classes = np.unique(overlay)
    classes = classes[classes > 0]
    cmap = plt.get_cmap("tab10")
    rgba = np.zeros(overlay.shape + (4,), dtype=np.float32)
    colors = {}
    for c in classes:
        color = cmap((int(c) - 1) % 10)
        colors[int(c) - 1] = color
        mask = overlay == c
        rgba[mask] = (color[0], color[1], color[2], 0.85)
    return rgba, colors


def _overview_panels(capture):
    """Build the overview page: annotated thumbnail (with overlays) + info text."""
    thumb = np.asarray(capture["thumb"])
    if thumb.ndim == 3 and thumb.shape[2] == 3 and thumb.dtype != np.uint8:
        thumb = _normalize01(thumb)
    stride = _scalar(capture, "thumb_stride", 1)
    branch = _as_str(_scalar(capture, "branch"))

    def draw(ax):
        handles = []
        # Training feature coverage: every region whose features were computed to
        # train the model. Drawn first (underneath) as a translucent fill so the
        # annotations and rectangles stay readable on top. Regions can lie well
        # outside the preview, wherever the user painted annotations.
        if "train_coverage" in capture:
            cov = np.asarray(capture["train_coverage"]).astype(bool)
            fill = np.zeros(cov.shape + (4,), dtype=np.float32)
            fill[cov] = (1.0, 0.0, 1.0, 0.22)  # translucent magenta
            ax.imshow(fill, interpolation="nearest")
            handles.append(
                patches.Patch(facecolor=(1.0, 0.0, 1.0, 0.35), edgecolor="none", label="training feature regions")
            )
        # Training annotations: the pixels the user painted, as one raster overlay
        # (not per-pixel markers) so the page stays light even for huge selections.
        if "ann_overlay" in capture:
            rgba, colors = _annotation_rgba(np.asarray(capture["ann_overlay"]))
            ax.imshow(rgba, interpolation="nearest")
            for cls, color in sorted(colors.items()):
                handles.append(patches.Patch(facecolor=color, edgecolor="none", label=f"annotated class {cls}"))
        # The visible region this preview predicts.
        i0, i1, j0, j1 = (np.asarray(capture["rect"]) / stride).tolist()
        ax.add_patch(patches.Rectangle((i0, j0), i1 - i0, j1 - j0, fill=False, edgecolor="yellow", lw=2, ls="--"))
        handles.append(patches.Patch(facecolor="none", edgecolor="yellow", ls="--", label="preview region (predicted)"))
        if branch == "contiguous":
            # The slightly larger region actually filtered, so feature values at
            # the preview's edge are correct (the margin covers each filter's reach).
            si0, si1, sj0, sj1 = (np.asarray(capture["sample_rect"]) / stride).tolist()
            ax.add_patch(
                patches.Rectangle((si0, sj0), si1 - si0, sj1 - sj0, fill=False, edgecolor="cyan", lw=1.5, ls=":")
            )
            handles.append(patches.Patch(facecolor="none", edgecolor="cyan", ls=":", label="filtered region (+margin)"))
        ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.85)

    cmap = None if thumb.ndim == 3 else "gray"
    return {
        "array": thumb,
        "cmap": cmap,
        "title": "Source image, training annotations, and preview region",
        "draw": draw,
    }


def _info_text(capture):
    branch = _as_str(_scalar(capture, "branch"))
    factor = int(_scalar(capture, "factor", 1))

    lines = [
        "Training annotations (colored regions above):",
        "  The pixels you painted with the brush, one color",
        "  per class. The model is trained ONLY on the feature",
        "  values at these pixels, then used to classify the",
        "  whole preview region.",
        "",
        "Training feature regions (magenta fill):",
        "  Where features were computed to train the model.",
        "  Features need each pixel's neighborhood, so these",
        "  areas surround the annotations (and can sit far",
        "  outside the preview region).",
        "",
        "Preview region (yellow dashed):",
        "  The visible area this preview predicts and displays.",
        "",
    ]
    if factor > 1:
        lines += [
            f"This preview is downscaled {factor}x: one prediction is",
            f"made per {factor}x{factor} block of source pixels, so it",
            "stays fast to update. Features still use full-resolution",
            "neighborhoods, so the preview matches the final result.",
            "",
        ]
    if branch == "contiguous":
        lines += [
            "How features were computed (contiguous path):",
            "  The region is small enough to filter exactly. One",
            "  contiguous patch (preview region + a margin, the cyan",
            "  dotted box) is filtered at full resolution, then",
            "  sampled onto the output grid.",
        ]
    elif branch == "sampled":
        smallest_sigma = int(_scalar(capture, "feature_scale", 1))  # base sigma-1 scaled
        lines += [
            "How features were computed (sampled path):",
            "  The region is too large to filter in full. Source,",
            f"  sigma-{smallest_sigma} gaussian and window variances are computed",
            "  exactly at the sampled positions; the large gaussians",
            "  are approximated from an image pyramid:",
        ]
        for name, level in json.loads(_as_str(_scalar(capture, "pyramid_levels"), "[]")):
            lines.append(f"    - {name}: pyramid level {level}")
    return "\n".join(lines)


def _info_text_3d(capture):
    scale = int(_scalar(capture, "feature_scale", 1))
    i_min, i_max, j_min, j_max, k_min, k_max = np.asarray(capture["extents"]).tolist()
    lines = [
        "3D segmentation preview.",
        "",
        "Features are precomputed over the whole volume (each filter",
        "applied out-of-core in haloed slabs), then the trained random",
        "forest classifies every voxel in the previewed plane.",
        "",
        "Previewed plane (voxel index ranges):",
        f"  X: {i_min}..{i_max}   Y: {j_min}..{j_max}   Z: {k_min}",
        f"  size: {i_max - i_min} x {j_max - j_min}",
        "",
        "The pages below show each feature on this plane and the",
        "resulting segmentation.",
    ]
    if scale > 1:
        lines += ["", f"Feature kernels are scaled {scale}x for coarser-textured images."]
    return "\n".join(lines)


def _render_capture_3d(capture, out_pdf, features_per_page):
    """Render a 3D debug capture: each feature on the previewed plane and the
    resulting segmentation. Reuses the 2D feature/result page layout."""
    features = np.asarray(capture["features"])
    names = json.loads(_as_str(_scalar(capture, "feature_names"), "[]"))
    n_features = len(names)
    n_channels = int(_scalar(capture, "n_channels", 1))
    # planes are feature-major / channel-minor -> (n_features, n_channels, h, w)
    grouped = features.reshape(n_features, n_channels, features.shape[1], features.shape[2])

    # Per-image channel layout (source first, then extras), same as the 2D path.
    if "image_channels" in capture:
        image_channels = [int(c) for c in np.asarray(capture["image_channels"])]
    else:
        image_channels = [n_channels]
    image_names = json.loads(_as_str(_scalar(capture, "image_names"), "[]"))
    if len(image_names) != len(image_channels):
        image_names = [f"Image {i + 1}" for i in range(len(image_channels))]
    if len(image_channels) == 1:
        image_names = [""]

    with PdfPages(out_pdf) as pdf:
        # Info page (text only; no thumbnail for the 3D report).
        fig = plt.figure(figsize=(PAGE_W, 11))
        ax_txt = fig.add_axes([MARGIN / PAGE_W, 0.05, 1 - 2 * MARGIN / PAGE_W, 0.85])
        ax_txt.text(0.0, 1.0, _info_text_3d(capture), va="top", ha="left", fontsize=10, family="monospace")
        ax_txt.set_axis_off()
        fig.suptitle("3D segmentation preview - how it was computed", fontsize=14, y=0.97)
        pdf.savefig(fig)
        plt.close(fig)

        # Feature pages: one row per feature, one column per input image.
        for start in range(0, n_features, features_per_page):
            blocks = []
            for k in range(start, min(start + features_per_page, n_features)):
                blocks.append({"name": names[k], "images": _split_into_images(grouped[k], image_channels)})
            _feature_page(pdf, blocks, image_names)

        # Result page: predicted labelmap (and uncertainty) on the preview plane.
        panels = [
            {"array": np.asarray(capture["result"]), "cmap": "tab10", "title": "Predicted labelmap (preview plane)"}
        ]
        if "uncertainty" in capture:
            panels.append(
                {
                    "array": np.asarray(capture["uncertainty"]),
                    "cmap": "magma",
                    "title": "Uncertain voxels (model's top two classes nearly tied)",
                }
            )
        _image_page(pdf, panels)

    return out_pdf


def render_capture(npz_path, out_pdf=None, features_per_page=2):
    """Render the capture at `npz_path` to a multi-page PDF. Returns the PDF path."""
    npz_path = Path(npz_path)
    out_pdf = Path(out_pdf) if out_pdf else npz_path.with_suffix(".pdf")
    features_per_page = max(1, min(3, int(features_per_page)))
    capture = dict(np.load(npz_path, allow_pickle=False))

    if bool(_scalar(capture, "is_3d", False)):
        return _render_capture_3d(capture, out_pdf, features_per_page)

    features = np.asarray(capture["features"])
    names = json.loads(_as_str(_scalar(capture, "feature_names"), "[]"))
    n_channels = int(_scalar(capture, "n_channels", 1))
    n_features = len(names)
    # planes are feature-major / channel-minor -> (n_features, n_channels, h, w)
    grouped = features.reshape(n_features, n_channels, features.shape[1], features.shape[2])

    # Per-image channel layout (source first, then extras). Absent (e.g. a capture
    # taken without image metadata) -> treat the whole stack as a single image.
    if "image_channels" in capture:
        image_channels = [int(c) for c in np.asarray(capture["image_channels"])]
    else:
        image_channels = [n_channels]
    image_names = json.loads(_as_str(_scalar(capture, "image_names"), "[]"))
    if len(image_names) != len(image_channels):
        image_names = [f"Image {i + 1}" for i in range(len(image_channels))]
    # A single image carries no extra info in its name; suppress the header then.
    if len(image_channels) == 1:
        image_names = [""]

    with PdfPages(out_pdf) as pdf:
        # Overview page: thumbnail-with-overlays + an info panel below it.
        overview = _overview_panels(capture)
        fig = plt.figure(figsize=(PAGE_W, 11))
        gs = fig.add_gridspec(
            2,
            1,
            height_ratios=[5, 3],
            hspace=0.12,
            left=MARGIN / PAGE_W,
            right=1 - MARGIN / PAGE_W,
            top=0.92,
            bottom=0.05,
        )
        ax_img = fig.add_subplot(gs[0])
        ax_img.imshow(overview["array"], cmap=overview["cmap"], interpolation="nearest")
        ax_img.set_title(overview["title"], fontsize=12)
        ax_img.set_axis_off()
        overview["draw"](ax_img)
        ax_txt = fig.add_subplot(gs[1])
        ax_txt.text(0.0, 1.0, _info_text(capture), va="top", ha="left", fontsize=9, family="monospace")
        ax_txt.set_axis_off()
        fig.suptitle("2D segmentation preview - how it was computed", fontsize=14, y=0.975)
        pdf.savefig(fig, dpi=_required_dpi([overview["array"].shape[1]], AXES_W))
        plt.close(fig)

        # Feature pages: one row per feature, one column per input image (RGB or
        # grayscale), `features_per_page` features per page, at native resolution.
        for start in range(0, n_features, features_per_page):
            blocks = []
            for k in range(start, min(start + features_per_page, n_features)):
                blocks.append({"name": names[k], "images": _split_into_images(grouped[k], image_channels)})
            _feature_page(pdf, blocks, image_names)

        # Result page: predicted labelmap + uncertainty.
        _image_page(
            pdf,
            [
                {"array": np.asarray(capture["result"]), "cmap": "tab10", "title": "Predicted labelmap"},
                {
                    "array": np.asarray(capture["uncertainty"]),
                    "cmap": "magma",
                    "title": "Uncertain pixels (model's top two classes nearly tied)",
                },
            ],
        )

    return out_pdf


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"usage: {Path(sys.argv[0]).name} debug_capture.npz [out.pdf] [features_per_page]")
        sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else None
    per_page = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    print(f"Wrote {render_capture(sys.argv[1], out, per_page)}")
