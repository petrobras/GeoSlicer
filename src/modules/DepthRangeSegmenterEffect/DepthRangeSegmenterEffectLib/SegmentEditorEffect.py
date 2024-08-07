import os
import vtk, qt, ctk, slicer
import logging
from SegmentEditorEffects import *

import numpy as np
from vtk.util import numpy_support as vtknp


class SegmentEditorEffect(AbstractScriptedSegmentEditorLabelEffect):
    """DrawEffect is a LabelEffect implementing the interactive depth range
    segmenter tool in the segment editor
    """

    def __init__(self, scriptedEffect):
        scriptedEffect.name = "Depth Segmenter"
        self.drawPipelines = {}
        AbstractScriptedSegmentEditorLabelEffect.__init__(self, scriptedEffect)

    def clone(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as effects

        clonedEffect = effects.qSlicerSegmentEditorScriptedLabelEffect(None)
        clonedEffect.setPythonSource(__file__.replace("\\", "/"))
        return clonedEffect

    def icon(self):
        iconPath = os.path.join(os.path.dirname(__file__), "../Resources/SegmentEditorEffect.png")
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def helpText(self):
        return """<html>Draw segment outline in slice viewers<br>.
    <p><ul style="margin: 0">
    <li><b>Click & drag:</b> delimit depth region to be painted.</li>
    </ul><p></html>"""

    def deactivate(self):
        # Clear draw pipelines
        for sliceWidget, pipeline in self.drawPipelines.items():
            self.scriptedEffect.removeActor2D(sliceWidget, pipeline.actor)
        self.drawPipelines = {}

    def setupOptionsFrame(self):
        pass

    def processInteractionEvents(self, callerInteractor, eventId, viewWidget):
        abortEvent = False

        # Only allow for slice views
        if viewWidget.className() != "qMRMLSliceWidget":
            return abortEvent
        # Get draw pipeline for current slice
        pipeline = self.pipelineForWidget(viewWidget)
        if pipeline is None:
            return abortEvent

        anyModifierKeyPressed = (
            callerInteractor.GetShiftKey() or callerInteractor.GetControlKey() or callerInteractor.GetAltKey()
        )

        if eventId == vtk.vtkCommand.LeftButtonPressEvent and not anyModifierKeyPressed:
            # Make sure the user wants to do the operation, even if the segment is not visible
            confirmedEditingAllowed = self.scriptedEffect.confirmCurrentSegmentVisible()
            if (
                confirmedEditingAllowed == self.scriptedEffect.NotConfirmed
                or confirmedEditingAllowed == self.scriptedEffect.ConfirmedWithDialog
            ):
                # If user had to move the mouse to click on the popup, so we cannot continue with painting
                # from the current mouse position. User will need to click again.
                # The dialog is not displayed again for the same segment.
                return abortEvent
            pipeline.actionState = "drawing"
            self.scriptedEffect.cursorOff(viewWidget)
            pipeline._updateColor()
            xy = callerInteractor.GetEventPosition()
            ras = self.xyToRas(xy, viewWidget)
            pipeline.addPoint(ras)
            abortEvent = True
        elif eventId == vtk.vtkCommand.MouseMoveEvent:
            if pipeline.actionState == "drawing":
                xy = callerInteractor.GetEventPosition()
                ras = self.xyToRas(xy, viewWidget)
                pipeline.addPoint(ras)
                abortEvent = True
        elif eventId == vtk.vtkCommand.LeftButtonReleaseEvent:
            if pipeline.actionState == "drawing":
                pipeline.actionState = "finishing"
                pipeline.apply()
                pipeline.actionState = "moving"
                self.scriptedEffect.cursorOn(viewWidget)
                abortEvent = True
        else:
            pass

        pipeline.positionActors()
        return abortEvent

    def processViewNodeEvents(self, callerViewNode, eventId, viewWidget):
        if callerViewNode and callerViewNode.IsA("vtkMRMLSliceNode"):
            # Get draw pipeline for current slice
            pipeline = self.pipelineForWidget(viewWidget)
            if pipeline is None:
                logging.error("processViewNodeEvents: Invalid pipeline")
                return

            # Make sure all points are on the current slice plane.
            # If the SliceToRAS has been modified, then we're on a different plane
            sliceLogic = viewWidget.sliceLogic()
            lineMode = "solid"
            currentSliceOffset = sliceLogic.GetSliceOffset()
            if pipeline.activeSliceOffset:
                offset = abs(currentSliceOffset - pipeline.activeSliceOffset)
                if offset > 0.01:
                    lineMode = "dashed"
            pipeline.setLineMode(lineMode)
            pipeline.positionActors()

    def pipelineForWidget(self, sliceWidget):
        if sliceWidget in self.drawPipelines:
            return self.drawPipelines[sliceWidget]

        # Create pipeline if does not yet exist
        pipeline = DrawPipeline(self.scriptedEffect, sliceWidget)

        # Add actor
        renderer = self.scriptedEffect.renderer(sliceWidget)
        if renderer is None:
            logging.error("pipelineForWidget: Failed to get renderer!")
            return None
        self.scriptedEffect.addActor2D(sliceWidget, pipeline.actor)

        self.drawPipelines[sliceWidget] = pipeline
        return pipeline


#
# DrawPipeline
#
class DrawPipeline:
    """Visualization objects and pipeline for each slice view for drawing"""

    def __init__(self, scriptedEffect, sliceWidget):
        self.scriptedEffect = scriptedEffect
        self.sliceWidget = sliceWidget
        self.activeSliceOffset = None
        self.lastInsertSliceNodeMTime = None
        self.actionState = None

        self.xyPoints = vtk.vtkPoints()
        self.rasPoints = vtk.vtkPoints()
        self.polyData = self.createPolyData()

        self.mapper = vtk.vtkPolyDataMapper2D()
        self.actor = vtk.vtkTexturedActor2D()
        self.mapper.SetInputData(self.polyData)
        self.actor.SetMapper(self.mapper)
        self._updateColor()

        self.createStippleTexture(0xAAAA, 8)

    def _getColor(self):
        color = [0, 0.6, 0.2]
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return color
        # Get color of edited segment
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if not segmentationNode:
            # scene was closed while preview was active
            return color
        displayNode = segmentationNode.GetDisplayNode()
        if displayNode is None:
            return color
        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        if segmentID is None:
            return color

        # Change color hue slightly to make it easier to distinguish filled regions from preview
        r, g, b = segmentationNode.GetSegmentation().GetSegment(segmentID).GetColor()
        return [r, g, b]

    def _updateColor(self, color=None):
        color = self._getColor() if color is None else color
        self.actor.GetProperty().SetColor(*color)

    def createStippleTexture(self, lineStipplePattern, lineStippleRepeat):
        self.tcoords = vtk.vtkDoubleArray()
        self.texture = vtk.vtkTexture()

        # Create texture
        dimension = 16 * lineStippleRepeat

        image = vtk.vtkImageData()
        image.SetDimensions(dimension, 1, 1)
        image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 4)
        image.SetExtent(0, dimension - 1, 0, 0, 0, 0)
        on = 255
        off = 0
        i_dim = 0
        while i_dim < dimension:
            for i in range(0, 16):
                mask = 1 << i
                bit = (lineStipplePattern & mask) >> i
                value = bit
                if value == 0:
                    for j in range(0, lineStippleRepeat):
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 0, on)
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 1, on)
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 2, on)
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 3, off)
                        i_dim += 1
                else:
                    for j in range(0, lineStippleRepeat):
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 0, on)
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 1, on)
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 2, on)
                        image.SetScalarComponentFromFloat(i_dim, 0, 0, 3, on)
                        i_dim += 1
        self.texture.SetInputData(image)
        self.texture.InterpolateOff()
        self.texture.RepeatOn()

    def createPolyData(self):
        # Make an empty single-polyline polydata
        polyData = vtk.vtkPolyData()
        polyData.SetPoints(self.xyPoints)
        lines = vtk.vtkCellArray()
        polyData.SetLines(lines)
        return polyData

    def addPoint(self, ras):
        if self.scriptedEffect.parameterSetNode() is None:
            logging.debug("Segment editor node is not available.")
            return
        # Add a world space point to the current outline

        # Store active slice when first point is added
        sliceLogic = self.sliceWidget.sliceLogic()
        currentSliceOffset = sliceLogic.GetSliceOffset()
        if not self.activeSliceOffset:
            self.activeSliceOffset = currentSliceOffset
            self.setLineMode("solid")

        # Don't allow adding points on except on the active slice
        # (where first point was laid down)
        if self.activeSliceOffset != currentSliceOffset:
            return

        # Keep track of node state (in case of pan/zoom)
        sliceNode = sliceLogic.GetSliceNode()
        self.lastInsertSliceNodeMTime = sliceNode.GetMTime()

        master_node = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        image_bounds = np.empty((3, 2))
        master_node.GetBounds(image_bounds.ravel())
        min_x = image_bounds[0][0]
        max_x = image_bounds[0][1]

        if self.rasPoints.GetNumberOfPoints() == 0:
            self.rasPoints.InsertNextPoint(min_x, ras[1], ras[2])
            self.rasPoints.InsertNextPoint(min_x, ras[1], ras[2])
            self.rasPoints.InsertNextPoint(max_x, ras[1], ras[2])
            self.rasPoints.InsertNextPoint(max_x, ras[1], ras[2])
            self.polyData.Reset()
            self.polyData.Allocate(1)
            self.polyData.InsertNextCell(vtk.VTK_QUAD, 4, [0, 1, 2, 3])
        else:
            p0 = self.rasPoints.GetPoint(0)
            self.rasPoints.SetPoint(0, [min_x, p0[1], p0[2]])
            self.rasPoints.SetPoint(1, [min_x, p0[1], ras[2]])
            self.rasPoints.SetPoint(2, [max_x, p0[1], ras[2]])
            self.rasPoints.SetPoint(3, [max_x, p0[1], p0[2]])

    def setLineMode(self, mode="solid"):
        if mode == "solid":
            self.polyData.GetPointData().SetTCoords(None)
            self.actor.SetTexture(None)
        elif mode == "dashed":
            # Create texture coordinates
            self.tcoords.SetNumberOfComponents(1)
            self.tcoords.SetNumberOfTuples(self.polyData.GetNumberOfPoints())
            for i in range(0, self.polyData.GetNumberOfPoints()):
                value = i * 0.5
                self.tcoords.SetTypedTuple(i, [value])
            self.polyData.GetPointData().SetTCoords(self.tcoords)
            self.actor.SetTexture(self.texture)

    def positionActors(self):
        # Update draw feedback to follow slice node
        sliceLogic = self.sliceWidget.sliceLogic()
        sliceNode = sliceLogic.GetSliceNode()
        rasToXY = vtk.vtkTransform()
        rasToXY.SetMatrix(sliceNode.GetXYToRAS())
        rasToXY.Inverse()
        self.xyPoints.Reset()
        rasToXY.TransformPoints(self.rasPoints, self.xyPoints)
        self.polyData.Modified()
        self.sliceWidget.sliceView().scheduleRender()

    def apply(self):
        if self.scriptedEffect.parameterSetNode() is None:
            slicer.util.errorDisplay("Failed to apply the effect. The selected node is not valid.")

        masterNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()

        anySelection = self.polyData.GetPoints().GetNumberOfPoints() > 1
        if anySelection:
            self.scriptedEffect.saveStateForUndo()

            # getting image boundaries
            xBounds, yBounds, zBounds = imageBounds = np.empty((3, 2))
            masterNode.GetBounds(imageBounds.ravel())

            # getting selection boundaries points
            rasPointsArr = vtknp.vtk_to_numpy(self.rasPoints.GetData())
            xSel, ySel, zSel = np.c_[rasPointsArr.min(axis=0), rasPointsArr.max(axis=0)]

            # making rectangle selection points
            selRasPointsArr = np.asarray(
                [  # rectangle
                    [xBounds[0], ySel[0], zSel[0]],
                    [xBounds[1], ySel[0], zSel[0]],
                    [xBounds[1], ySel[1], zSel[1]],
                    [xBounds[0], ySel[1], zSel[1]],
                ]
            )
            selRasPoints = vtk.vtkPoints()
            selRasPoints.SetData(vtknp.numpy_to_vtk(selRasPointsArr))

            # transforming coordinates from RAS to XY
            sliceLogic = self.sliceWidget.sliceLogic()
            sliceNode = sliceLogic.GetSliceNode()
            rasToXy = vtk.vtkTransform()
            rasToXy.SetMatrix(sliceNode.GetXYToRAS())
            rasToXy.Inverse()

            selXyPoints = vtk.vtkPoints()
            rasToXy.TransformPoints(selRasPoints, selXyPoints)

            # creating poly data
            selPolyData = vtk.vtkPolyData()
            selPolyData.SetPoints(selXyPoints)

            import vtkSegmentationCorePython as vtkSegmentationCore

            self.scriptedEffect.appendPolyMask(modifierLabelmap, selPolyData, self.sliceWidget, segmentationNode)

        self.resetPolyData()
        if anySelection:
            self.scriptedEffect.modifySelectedSegmentByLabelmap(
                modifierLabelmap, slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeAdd
            )

    def resetPolyData(self):
        # Return the polyline to initial state with no points
        lines = self.polyData.GetLines()
        lines.Initialize()
        self.xyPoints.Reset()
        self.rasPoints.Reset()
        self.activeSliceOffset = None
