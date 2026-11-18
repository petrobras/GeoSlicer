# Ring Artifact Removal

Removes ring artifacts from already reconstructed CT/micro-CT volumes. The
correction is done slice by slice, around one or more centers marked by the
user, isolating the systematic bias that is constant at a given radius
(equal at every angle) and subtracting it — without resampling the image, so
the real texture is not blurred.

See the module UI for the usage flow (mark centers, preview on a single
slice, apply to the entire volume). The module is available in the
**Filters** tool, under _Ring Artifact Removal_.

## Known limitation: "spider web" / radiating streak patterns

Not every visible radial pattern is a classic ring artifact. In an
investigation with real data (volume `microtom - Cylinder`), a pattern of
thin lines radiating from a point ("spider web") proved **resistant to all
correction approaches in the reconstructed image domain** that were tested:

1. **Classic radial removal** (fixed or shifted center, with/without
   automatic center refinement) — almost no correction; circular sampling
   confirmed that the pattern is not constant along the radius, hence it is
   not a true ring artifact.
2. **Angular removal** (bias constant along the angle, varying with the
   radius) — also almost no correction.
3. **Adaptive angular filter** (window proportional to 1/radius, to follow
   the increasing angular frequency) — unstable, absurd correction peaks, no
   visual improvement.
4. **2D notch via FFT** — discarded before implementing: the magnitude
   spectrum of the region is diffuse, with no narrow peaks a notch could
   target (the pattern is not stationary — the local frequency changes with
   position, so it has no compact representation in global Fourier space).
5. **Local inpainting** (`cv2.inpaint` and median filling) — Telea
   generated its own fan pattern (an artifact of the directional propagation
   algorithm itself); median filling even erases the central knot, but
   destroys real texture over a considerable area and does not touch the
   wider pattern that spreads across the slice.

**Most likely diagnosis:** a "zinger"-type artifact — a defective detector
pixel or a very high-contrast inclusion in a single (or a few) projection(s),
which the FBP reconstruction ramp filter spreads radially into a
non-separable 2D structure (local frequency grows with the distance to the
focus). This kind of artifact can only be properly corrected by treating the
source point in the **sinogram** (raw projections, before reconstruction)
and reconstructing again — there is no post-reconstruction correction in the
image domain that solves it without destroying real texture.

**If this pattern shows up in your data:** first confirm that it is this
kind of pattern (test the classic radial removal — if the correction is
negligible even with a well-adjusted center, it is a sign that it is not a
true ring artifact). If so, this module's correction will not help; consider
reprocessing the reconstruction from the sinogram, if available.
