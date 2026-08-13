import os
import logging

import numpy as np
import qt
import slicer
import vtk
import vtk.util.numpy_support as vn
import vtkITK

from SegmentEditorEffects import *

from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    """PeriodicLevelTracingEffect traces closed intensity contours with horizontal periodic
    boundary conditions — useful for cylindrical/unwrapped images where the right edge
    connects to the left edge (e.g. ImageLog). Regions that straddle the boundary are
    correctly handled via tiling.
    """

    def __init__(self, scriptedEffect):
        scriptedEffect.name = "Periodic level tracing"
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)

        self.levelTracingPipelines = {}
        self.lastXY = None

    def clone(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as effects

        clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
        clonedEffect.setPythonSource(__file__.replace("\\", "/"))
        return clonedEffect

    def icon(self):
        iconPath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "Resources",
            "Icons",
            "PeriodicLevelTracing.png",
        )
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def helpText(self):
        return """<html>Add uniform intensity region to selected segment using periodic (wrap-around) boundary conditions.<br>
<p><ul style="margin: 0">
<li><b>Mouse move:</b> traces a closed intensity contour. Regions that straddle the left/right
image boundary are correctly handled — the image wraps horizontally.</li>
<li><b>Left-click:</b> fill the previewed region (always the smaller of the two enclosed areas).</li>
</ul><p></html>"""

    def setupOptionsFrame(self):
        pass

    def activate(self):
        self.SetSourceVolumeIntensityMaskOff()

    def deactivate(self):
        for sliceWidget, pipeline in self.levelTracingPipelines.items():
            self.scriptedEffect.removeActor2D(sliceWidget, pipeline.actor)
        self.levelTracingPipelines = {}
        self.lastXY = None

    def processInteractionEvents(self, callerInteractor, eventId, viewWidget):
        abortEvent = False

        if viewWidget.className() != "qMRMLSliceWidget":
            return abortEvent

        pipeline = self.pipelineForWidget(viewWidget)
        if pipeline is None:
            return abortEvent

        if eventId == vtk.vtkCommand.LeftButtonPressEvent:
            if not self.scriptedEffect.confirmCurrentSegmentVisible():
                return abortEvent

            self.scriptedEffect.saveStateForUndo()

            modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
            pipeline.applyMask(modifierLabelmap)
            self.scriptedEffect.modifySelectedSegmentByLabelmap(
                modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeAdd
            )
            abortEvent = True
        elif eventId == vtk.vtkCommand.MouseMoveEvent:
            if pipeline.actionState == "":  # Check if it isn't a composed interaction (Right/Middle click + Drag)
                xy = callerInteractor.GetEventPosition()
                pipeline.preview(xy)
                abortEvent = True
                self.lastXY = xy
        elif eventId == vtk.vtkCommand.RightButtonPressEvent or eventId == vtk.vtkCommand.MiddleButtonPressEvent:
            pipeline.actionState = "interacting"
        elif eventId == vtk.vtkCommand.RightButtonReleaseEvent or eventId == vtk.vtkCommand.MiddleButtonReleaseEvent:
            pipeline.actionState = ""
        elif eventId == vtk.vtkCommand.EnterEvent:
            pipeline.actor.VisibilityOn()
        elif eventId == vtk.vtkCommand.LeaveEvent:
            pipeline.actor.VisibilityOff()
            self.lastXY = None

        return abortEvent

    def processViewNodeEvents(self, callerViewNode, eventId, viewWidget):
        """Redraws the contour at the last known mouse position when the view changes (scroll, zoom, pan)."""
        if callerViewNode and callerViewNode.IsA("vtkMRMLSliceNode"):
            pipeline = self.pipelineForWidget(viewWidget)
            if pipeline is None:
                logging.error("processViewNodeEvents: Invalid pipeline")
                return
            if pipeline.actionState == "" and self.lastXY:
                pipeline.preview(self.lastXY)

    def pipelineForWidget(self, sliceWidget):
        """Return the existing pipeline for a slice widget, or create a new one if needed.
        Each widget has its own pipeline so multiple open views work independently.
        """
        if sliceWidget in self.levelTracingPipelines:
            return self.levelTracingPipelines[sliceWidget]

        pipeline = PeriodicLevelTracingPipeline(self, sliceWidget)

        # Check that sliceWidget is ready before adding the actor to it
        renderer = self.scriptedEffect.renderer(sliceWidget)
        if renderer is None:
            logging.error("setupPreviewDisplay: Failed to get renderer!")
            return None

        self.scriptedEffect.addActor2D(sliceWidget, pipeline.actor)

        self.levelTracingPipelines[sliceWidget] = pipeline
        return pipeline


class PeriodicLevelTracingPipeline:
    """Visualization and fill pipeline for a single slice view.

    Manages contour preview and fill for one slice widget. Each instance keeps its own
    tiled image cache and filter results to avoid redundant recomputation.
    """

    def __init__(self, effect, sliceWidget):
        self.effect = effect
        self.sliceWidget = sliceWidget
        self.actionState = ""  # "" = normal, "interacting" = pan/zoom in progress

        self.polyData = vtk.vtkPolyData()

        # Contour in tiled space (I ∈ [0, 3W)), consumed by applyMask().
        # For non-wrapping contours the native result is shifted to the centre tile (I+W).
        self._tiledPolyData = None
        self._tileW = 0  # W = NI of the source volume
        self._lastSeedJ = 0

        # Tiled image cache — rebuilt only when J or the image changes.
        # Avoids recreating the 3x array every frame while the mouse moves along the same row.
        self._cachedTiledImage = None
        self._cachedTiledJ = -1
        self._cachedTiledW = -1
        self._cachedTiledMTime = -1

        # Persistent ITK filters — created once and reused every frame to avoid
        # VTK object construction/destruction overhead on every mouse move.

        # Pass 1: native filter on the original image (1x cost).
        # Covers the common case where the contour does NOT cross the image boundary.
        self._tracingFilterNative = vtkITK.vtkITKLevelTracingImageFilter()
        self._tracingFilterNative.SetPlaneToIK()
        self._lastNativeSeed = None
        self._lastNativeDisplayPD = None
        self._lastNativeIsWrapping = False  # True when the native contour touches the image edges

        # Pass 2: tiled filter (3x cost) — only run when the contour wraps at the I boundary.
        # Uses a 3x wider image with the seed placed in the centre tile.
        self._tracingFilterIK = vtkITK.vtkITKLevelTracingImageFilter()
        self._tracingFilterIK.SetPlaneToIK()

        # Slice-state cache — rebuilt only when the view matrix or image changes.
        # Avoids recomputing the plane and IJK→XY transform every frame.
        self._cachedSliceStateKey = None  # (sliceNode MTime, image MTime)
        self._cachedPlane = None  # 'IJ', 'IK', 'JK', or None
        self._cachedIjkToXy = None  # vtkGeneralTransform: IJK → screen XY

        # Seed cache — filter + display poly rebuilt only when the voxel seed changes.
        self._lastTiledSeed = None
        self._lastDisplayPD = None  # IJK-space display poly for the last seed

        # Full-skip tracking — avoids TransformPoints + render when nothing changed.
        self._lastDrawnSeed = None
        self._lastDrawnStateKey = None

        self.mapper = vtk.vtkPolyDataMapper2D()
        self.actor = vtk.vtkActor2D()
        actorProperty = self.actor.GetProperty()
        actorProperty.SetColor(1, 1, 0)
        actorProperty.SetLineWidth(1)
        self.mapper.SetInputData(self.polyData)
        self.actor.SetMapper(self.mapper)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _determinePlane(self, imageData, parentTransformNode):
        """Return 'IJ', 'IK', 'JK', or None (oblique slice)."""
        sliceNode = self.effect.scriptedEffect.viewNode(self.sliceWidget)
        offset = max(sliceNode.GetDimensions())
        i0, j0, k0 = self.effect.xyToIjk((0, 0), self.sliceWidget, imageData, parentTransformNode)
        i1, j1, k1 = self.effect.xyToIjk((offset, offset), self.sliceWidget, imageData, parentTransformNode)
        if i0 == i1:
            return "JK"
        if j0 == j1:
            return "IK"
        if k0 == k1:
            return "IJ"
        return None

    def _ijkToXyTransform(self, imageData, parentTransformNode):
        """Return a composite transform from IJK voxel indices to screen XY."""
        sliceNode = self.effect.scriptedEffect.viewNode(self.sliceWidget)
        xyToRas = sliceNode.GetXYToRAS()
        rasToIjk = vtk.vtkMatrix4x4()
        imageData.GetImageToWorldMatrix(rasToIjk)
        rasToIjk.Invert()
        xyToIjk = vtk.vtkGeneralTransform()
        xyToIjk.PostMultiply()
        xyToIjk.Concatenate(xyToRas)
        if parentTransformNode:
            worldToSeg = vtk.vtkMatrix4x4()
            parentTransformNode.GetMatrixTransformFromWorld(worldToSeg)
            xyToIjk.Concatenate(worldToSeg)
        xyToIjk.Concatenate(rasToIjk)
        return xyToIjk.GetInverse()

    def _buildDisplayPoly(self, tiledPolyData, W, NK, j):
        """Fold all three tiled tiles into display space [0, W-1] — fully vectorised.

        The ITK filter runs on a 3x wider image (tiles A, B, C with B at centre).
        This function:
          1. Discards filter closing artefacts at the tiled-image boundaries.
          2. Folds all points back to [0, W-1] via x % W.
          3. Drops tile-boundary crossings (they would appear as spurious diagonals)
             but uses their K-values to emit short vertical closing segments at the image edges.
          4. Returns a vtkPolyData in IJK space ready to be transformed to screen XY.

        Args:
            tiledPolyData: ITK filter output in tiled space (x=I_tiled, y=K_voxel)
            W: original image width (NI)
            NK: image height in K
            j: fixed J index of the current slice
        """
        srcPts = tiledPolyData.GetPoints()
        srcLines = tiledPolyData.GetLines()

        # --- Extract all segment pairs as numpy arrays ---
        ptsNp = vn.vtk_to_numpy(srcPts.GetData())  # (N, 3)
        xPts = ptsNp[:, 0]  # I_tiled
        yPts = ptsNp[:, 2]  # K (non-periodic for IK plane)

        linesFlat = vn.vtk_to_numpy(srcLines.GetData())
        id0List, id1List = [], []
        pos = 0
        while pos < len(linesFlat):
            n = linesFlat[pos]
            if n >= 2:
                ids = linesFlat[pos + 1 : pos + 1 + n]
                id0List.append(ids[:-1])
                id1List.append(ids[1:])
            pos += n + 1

        if not id0List:
            return None

        id0 = np.concatenate(id0List)
        id1 = np.concatenate(id1List)
        x0 = xPts[id0]
        y0 = yPts[id0]
        x1 = xPts[id1]
        y1 = yPts[id1]

        # --- Skip tiled-image-boundary segments (filter closing artefacts) ---
        keep = (
            ~((y0 < 1) & (y1 < 1))
            & ~((y0 > NK - 2) & (y1 > NK - 2))
            & ~((x0 < 1) & (x1 < 1))
            & ~((x0 > 3 * W - 2) & (x1 > 3 * W - 2))
        )
        x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]

        if len(x0) == 0:
            return None

        # --- Fold to display space [0, W-1] ---
        x0d = x0 % W
        x1d = x1 % W

        crossing = np.abs(x1d - x0d) > W / 2
        nc = ~crossing

        # Collect K-values at tile boundaries to emit vertical closing segments at the image edges.
        cx = np.concatenate([x0d[crossing], x1d[crossing]])
        cy = np.concatenate([y0[crossing], y1[crossing]])
        leftYs = cy[cx < W / 2]
        rightYs = cy[cx >= W / 2]

        # --- Build output point pairs for non-crossing segments ---
        x0dNc = x0d[nc]
        y0Nc = y0[nc]
        x1dNc = x1d[nc]
        y1Nc = y1[nc]
        nSegs = len(x0dNc)

        ptsNc = np.empty((2 * nSegs, 3), dtype=np.float64)
        ptsNc[0::2, 0] = x0dNc
        ptsNc[0::2, 1] = j
        ptsNc[0::2, 2] = y0Nc
        ptsNc[1::2, 0] = x1dNc
        ptsNc[1::2, 1] = j
        ptsNc[1::2, 2] = y1Nc

        # Vertical closing segments at image edges
        closerPts = []
        for xDisp, ys in ((0.0, leftYs), (float(W - 1), rightYs)):
            if len(ys) >= 2:
                closerPts += [[xDisp, j, float(ys.min())], [xDisp, j, float(ys.max())]]

        if closerPts:
            ptsOut = np.vstack([ptsNc, np.array(closerPts, dtype=np.float64)])
        else:
            ptsOut = ptsNc

        nTotal = len(ptsOut) // 2
        if nTotal == 0:
            return None

        # --- Assemble VTK polydata without Python-level loops ---
        linesOut = np.empty(3 * nTotal, dtype=np.int64)
        linesOut[0::3] = 2
        linesOut[1::3] = np.arange(0, 2 * nTotal, 2)
        linesOut[2::3] = np.arange(1, 2 * nTotal, 2)

        newPts = vtk.vtkPoints()
        newPts.SetData(vn.numpy_to_vtk(ptsOut, deep=True))

        newLines = vtk.vtkCellArray()
        newLines.SetCells(nTotal, vn.numpy_to_vtk(linesOut, deep=True, array_type=vtk.VTK_ID_TYPE))

        pd = vtk.vtkPolyData()
        pd.SetPoints(newPts)
        pd.SetLines(newLines)
        return pd

    def _clearPolyData(self):
        """Reset the preview contour and force a re-render (called on invalid positions)."""
        self.polyData.Reset()
        self._lastDrawnSeed = None
        self._lastDrawnStateKey = None
        self.sliceWidget.sliceView().scheduleRender()

    # ------------------------------------------------------------------
    # preview
    # ------------------------------------------------------------------

    def preview(self, xy):
        """Update the contour preview for the given mouse position xy=(x, y).

        Implements a two-pass strategy with aggressive caching to minimise per-frame cost:

        Pass 1 (fast, 1x cost): run the ITK filter on the original image.
            - If the contour does not touch the edges → final result, no Pass 2 needed.
        Pass 2 (slow, 3x cost, rare): run the ITK filter on a 3x wider tiled image.
            - Only triggered when Pass 1 detects wrapping (contour touches the edges).

        Cache levels:
            - Full skip: if both seed and view state are unchanged, do nothing.
            - Slice-state cache: plane and IJK→XY transform recomputed only on view/image change.
            - Seed cache: ITK filter rerun only when the voxel seed changes.
            - Tiled image cache: 3x array rebuilt only when J or the image changes.
        """
        masterImageData = self.effect.scriptedEffect.sourceVolumeImageData()

        segmentationNode = self.effect.scriptedEffect.parameterSetNode().GetSegmentationNode()
        parentTransformNode = None
        if segmentationNode:
            parentTransformNode = segmentationNode.GetParentTransformNode()

        ijk = self.effect.xyToIjk(xy, self.sliceWidget, masterImageData, parentTransformNode)
        dims = masterImageData.GetDimensions()
        NI, NJ, NK = dims

        # Rebuild view-dependent state only when the slice view or image changes
        sliceNode = self.effect.scriptedEffect.viewNode(self.sliceWidget)
        stateKey = (sliceNode.GetMTime(), masterImageData.GetMTime())
        if stateKey != self._cachedSliceStateKey:
            self._cachedPlane = self._determinePlane(masterImageData, parentTransformNode)
            self._cachedIjkToXy = self._ijkToXyTransform(masterImageData, parentTransformNode)
            self._cachedSliceStateKey = stateKey

        plane = self._cachedPlane
        if plane is None or plane != "IK":
            self._clearPolyData()
            return

        # Reject positions too close to top/bottom — ITK filter needs 1px of margin
        if ijk[2] < 1 or ijk[2] >= NK - 1:
            self._clearPolyData()
            return

        j = int(np.clip(np.round(ijk[1]), 0, NJ - 1)) if NJ > 0 else 0
        W = NI

        # Round IJK position to the nearest voxel (filter seed)
        origSeed = (int(np.round(ijk[0])), j, int(np.round(ijk[2])))
        if origSeed[2] < 1 or origSeed[2] >= NK - 1:
            self._clearPolyData()
            return

        # Full skip: seed voxel and view state are both unchanged since last draw
        if origSeed == self._lastDrawnSeed and stateKey == self._lastDrawnStateKey:
            return

        # Pass 1: run native filter on original image
        if origSeed != self._lastNativeSeed or self._lastNativeDisplayPD is None:
            self._tracingFilterNative.SetInputData(masterImageData)
            self._tracingFilterNative.SetSeed(origSeed)
            self._tracingFilterNative.Update()
            nativeOutput = self._tracingFilterNative.GetOutput()

            isWrapping = False
            if nativeOutput.GetNumberOfPoints() > 0:
                # Check if any contour point is within 5px of the left or right edge.
                # If so, the contour likely crosses the periodic boundary and Pass 2 is needed.
                nPts = vn.vtk_to_numpy(nativeOutput.GetPoints().GetData())
                iCoords = nPts[:, 0]
                isWrapping = bool(np.any(iCoords < 5) or np.any(iCoords > NI - 4))

            self._lastNativeSeed = origSeed
            self._lastNativeIsWrapping = isWrapping
            if nativeOutput.GetNumberOfPoints() > 0:
                nativeCopy = vtk.vtkPolyData()
                nativeCopy.DeepCopy(nativeOutput)
                self._lastNativeDisplayPD = nativeCopy
            else:
                self._lastNativeDisplayPD = None

            if not isWrapping:
                # Fast path: native result is correct, no tiling needed.
                # Shift native contour (I ∈ [0,W)) into the centre tile (I+W) so
                # applyMask can always use the single tiled stencil path.
                if self._lastNativeDisplayPD is not None:
                    nPts2 = vn.vtk_to_numpy(self._lastNativeDisplayPD.GetPoints().GetData())
                    shifted = np.column_stack([nPts2[:, 0] + W, nPts2[:, 2], np.zeros(len(nPts2))])
                    shiftedPts = vtk.vtkPoints()
                    shiftedPts.SetData(vn.numpy_to_vtk(shifted, deep=True))
                    tiledPD = vtk.vtkPolyData()
                    tiledPD.SetPoints(shiftedPts)
                    tiledPD.SetLines(self._lastNativeDisplayPD.GetLines())
                    self._tiledPolyData = tiledPD
                    self._tileW = W
                    self._lastSeedJ = j
                else:
                    self._tiledPolyData = None
                self._lastTiledSeed = None
                self._lastDisplayPD = self._lastNativeDisplayPD

        # Pass 2: wrapping pore — fall back to tiled filter
        if self._lastNativeIsWrapping:
            # Seed placed at the centre tile (I+W) so the filter can expand in both directions.
            tiledSeed = (origSeed[0] + W, 0, origSeed[2])
            if tiledSeed[0] < 1 or tiledSeed[0] >= 3 * W - 1:
                self._clearPolyData()
                return

            if tiledSeed != self._lastTiledSeed or self._lastDisplayPD is None:
                # Rebuild tiled image only when J slice or image changes
                mtime = masterImageData.GetMTime()
                if j != self._cachedTiledJ or W != self._cachedTiledW or mtime != self._cachedTiledMTime:
                    nComp = masterImageData.GetNumberOfScalarComponents()
                    arr = vn.vtk_to_numpy(masterImageData.GetPointData().GetScalars())

                    # Build tiled image: 3x wide in I, 1 row in J (seed at J=0).
                    if nComp > 1:
                        sliceIk = arr.reshape(NK, NJ, NI, nComp)[:, j, :, :]  # (NK, NI, nC)
                        tiledIk = np.tile(sliceIk, (1, 3, 1))  # (NK, 3*NI, nC)
                        tiled3d = tiledIk[:, np.newaxis, :, :]  # (NK, 1, 3*NI, nC)
                    else:
                        sliceIk = arr.reshape(NK, NJ, NI)[:, j, :]  # (NK, NI)
                        tiledIk = np.tile(sliceIk, (1, 3))  # (NK, 3*NI)
                        tiled3d = tiledIk[:, np.newaxis, :]  # (NK, 1, 3*NI)

                    scalars = vn.numpy_to_vtk(
                        tiled3d.reshape(-1), deep=True, array_type=masterImageData.GetScalarType()
                    )
                    scalars.SetNumberOfComponents(nComp)

                    tiledImage = vtk.vtkImageData()
                    tiledImage.SetDimensions(3 * W, 1, NK)
                    tiledImage.SetSpacing(1, 1, 1)
                    tiledImage.SetOrigin(0, 0, 0)
                    tiledImage.GetPointData().SetScalars(scalars)

                    self._cachedTiledImage = tiledImage
                    self._cachedTiledJ = j
                    self._cachedTiledW = W
                    self._cachedTiledMTime = mtime
                    self._tracingFilterIK.SetInputData(tiledImage)

                self._tracingFilterIK.SetSeed(tiledSeed)
                self._tracingFilterIK.Update()
                rawTiled = self._tracingFilterIK.GetOutput()
                if rawTiled.GetNumberOfPoints() == 0:
                    self._clearPolyData()
                    return

                # Save tiled contour: x=I_tiled, y=K, z=0
                ptsNp = vn.vtk_to_numpy(rawTiled.GetPoints().GetData())  # (N, 3)
                flatArr = np.zeros_like(ptsNp)
                flatArr[:, 0] = ptsNp[:, 0]  # I_tiled
                flatArr[:, 1] = ptsNp[:, 2]  # K
                flatPts = vtk.vtkPoints()
                flatPts.SetData(vn.numpy_to_vtk(flatArr, deep=True))

                self._tiledPolyData = vtk.vtkPolyData()
                self._tiledPolyData.SetPoints(flatPts)
                self._tiledPolyData.SetLines(rawTiled.GetLines())
                self._tileW = W
                self._lastSeedJ = j

                displayPD = self._buildDisplayPoly(rawTiled, W, NK, j)
                if displayPD is None:
                    self._clearPolyData()
                    return

                self._lastTiledSeed = tiledSeed
                self._lastDisplayPD = displayPD

        polyData = self._lastDisplayPD
        if polyData is None:
            self._clearPolyData()
            return

        xyPts = vtk.vtkPoints()
        self._cachedIjkToXy.TransformPoints(polyData.GetPoints(), xyPts)

        # Update the 2D actor with the contour geometry in screen coordinates
        self.polyData.DeepCopy(polyData)
        self.polyData.GetPoints().DeepCopy(xyPts)
        self.polyData.Modified()
        self.sliceWidget.sliceView().scheduleRender()

        self._lastDrawnSeed = origSeed
        self._lastDrawnStateKey = stateKey

    # ------------------------------------------------------------------
    # applyMask — fill on click
    # ------------------------------------------------------------------

    def applyMask(self, modifierLabelmap):
        """Fill the region enclosed by the current contour into the modifier labelmap.

        Uses vtkPolyDataToImageStencil for a 2D scan-fill in tiled space, then OR-merges
        the three tiles to correctly reconstruct regions that straddle the periodic boundary.
        Always fills the SMALLER of the two regions enclosed by the contour.
        """
        if self._tiledPolyData is None or self._tiledPolyData.GetNumberOfPoints() == 0:
            return

        masterImageData = self.effect.scriptedEffect.sourceVolumeImageData()
        dims = masterImageData.GetDimensions()
        NI, NJ, NK = dims[0], dims[1], dims[2]
        W = self._tileW
        j = self._lastSeedJ

        # --- Stencil fill in tiled space [0, 3W) × [0, NK) ---
        # _tiledPolyData has x=I_tiled, y=K, z=0 so vtkPolyDataToImageStencil
        # performs a 2-D scan-fill in the IK plane.
        poly2stencil = vtk.vtkPolyDataToImageStencil()
        poly2stencil.SetInputData(self._tiledPolyData)
        poly2stencil.SetOutputOrigin(0.0, 0.0, 0.0)
        poly2stencil.SetOutputSpacing(1.0, 1.0, 1.0)
        poly2stencil.SetOutputWholeExtent(0, 3 * W - 1, 0, NK - 1, 0, 0)
        poly2stencil.Update()

        # Blank image with the same dimensions as the tiled space
        tiledBlank = vtk.vtkImageData()
        tiledBlank.SetDimensions(3 * W, NK, 1)
        tiledBlank.SetSpacing(1.0, 1.0, 1.0)
        tiledBlank.SetOrigin(0.0, 0.0, 0.0)
        tiledBlank.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        tiledBlank.GetPointData().GetScalars().Fill(0)

        # Pixels inside the contour receive value 1
        stencilFill = vtk.vtkImageStencil()
        stencilFill.SetInputData(tiledBlank)
        stencilFill.SetStencilConnection(poly2stencil.GetOutputPort())
        stencilFill.ReverseStencilOn()
        stencilFill.SetBackgroundValue(1)
        stencilFill.Update()

        filledArr = vn.vtk_to_numpy(stencilFill.GetOutput().GetPointData().GetScalars())
        filledSlice = filledArr.reshape(NK, 3 * W)

        # OR-merge all three tiles so that regions straddling the boundary are
        # reconstructed correctly (e.g. a pore split across x=0 / x=NI-1).
        tileA = filledSlice[:, 0:W]
        tileB = filledSlice[:, W : 2 * W]
        tileC = filledSlice[:, 2 * W : 3 * W]
        merged = np.maximum(tileA, np.maximum(tileB, tileC))

        # Always fill the SMALLER of the two regions enclosed by the contour.
        if np.count_nonzero(merged) > (NI * NK) // 2:
            merged = 1 - merged

        modArr = vn.vtk_to_numpy(modifierLabelmap.GetPointData().GetScalars())
        modDims = modifierLabelmap.GetDimensions()
        modArr3d = modArr.reshape(modDims[2], modDims[1], modDims[0])

        # Clamp to the smallest common size between image and labelmap (defensive guard)
        ks = min(NK, modDims[2])
        cols = min(NI, modDims[0])
        if j < modDims[1]:
            modArr3d[:ks, j, :cols] = np.maximum(modArr3d[:ks, j, :cols], merged[:ks, :cols])

        modifierLabelmap.GetPointData().GetScalars().Modified()
        modifierLabelmap.Modified()
