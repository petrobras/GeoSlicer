import math
import numpy as np
import qt
import slicer
import vtk

from ltrace.slicer.helpers import createTemporaryNode


class Markup(qt.QObject):
    FIDUCIAL_MARKUP_TYPE = 0
    LINE_MARKUP_TYPE = 1

    def __init__(
        self,
        type,
        finish_callback,
        finish_criterion=None,
        pick_criterion=None,
        update_instruction=None,
        start_callback=None,
        cancel_callback=None,
        after_finish_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.TYPE_TO_SLICER_TYPE = {
            self.FIDUCIAL_MARKUP_TYPE: slicer.vtkMRMLMarkupsFiducialNode,
            self.LINE_MARKUP_TYPE: slicer.vtkMRMLMarkupsLineNode,
        }

        self.type = type
        self.finish_callback = finish_callback
        self.pick_criterion = pick_criterion or (lambda *args, **kwargs: True)
        self.finish_criterion = finish_criterion or (lambda *args, **kwargs: True)
        self.update_instruction = update_instruction
        self.start_callback = start_callback
        self.cancel_callback = cancel_callback or (lambda *args, **kwargs: None)
        self.after_finish_callback = after_finish_callback or (lambda *args, **kwargs: None)
        self.markups_observer_tags = None
        self.interaction_observer_tags = None
        self.pick_criterion_passed = None
        self.last_slice_view_name = None

        self.markups_node = createTemporaryNode(cls=self.TYPE_TO_SLICER_TYPE[self.type], name="markups_node")
        slicer.modules.AppContextInstance.mainWindow.installEventFilter(self)

    def __del__(self):
        self.stop_picking()
        self.__reset_markups_node()
        selection_node = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")
        selection_node.SetReferenceActivePlaceNodeID(None)
        slicer.mrmlScene.RemoveNode(self.markups_node)
        del self.markups_node

    def eventFilter(self, object, event):
        if event.type() == qt.QEvent.HoverMove:
            self.last_slice_view_name = (
                self.markups_node.GetAttribute("Markups.MovingInSliceView") or self.last_slice_view_name
            )
            return False
        if event.type() == qt.QEvent.KeyPress and event.key() == qt.Qt.Key_Escape:
            self.cancel_picking()
            return True
        return False

    def start_picking(self):
        @vtk.calldata_type(vtk.VTK_INT)
        def set_pick_criterion_passed(markups_node=None, event=None, index=None):
            self.pick_criterion_passed = self.pick_criterion(self, index)

        def next_pick_or_finish(interaction_node=None, event=None):
            point_index = self.markups_node.GetNumberOfControlPoints() - 1
            if not self.pick_criterion_passed:
                if point_index > -1:
                    self.markups_node.RemoveNthControlPoint(point_index)
            if self.finish_criterion(self, point_index):
                self.stop_picking()
                self.finish_callback(self, point_index)
                self.__reset_markups_node()
                self.after_finish_callback()
            else:  # pick another point
                if self.update_instruction:
                    self.update_instruction(self, point_index)
                if interaction_node.GetCurrentInteractionMode() != 1:
                    self.stop_picking()
                    self.__reset_markups_node()

        self.__reset_markups_node()
        self.__removeInteractionObserverTags()
        self.__removeMarkupsObserverTags()

        self.markups_observer_tags = [
            self.markups_node.AddObserver(
                slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, set_pick_criterion_passed
            ),
        ]

        selection_node = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")
        selection_node.SetReferenceActivePlaceNodeID(self.markups_node.GetID())

        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        interactionNode.SetPlaceModePersistence(0)
        self.interaction_observer_tags = [
            interactionNode.AddObserver(slicer.vtkMRMLInteractionNode.EndPlacementEvent, next_pick_or_finish)
        ]
        interactionNode.SetCurrentInteractionMode(1)

        # allow picks from interaction node
        interactionNode.SetCurrentInteractionMode(1)
        if self.update_instruction is not None:
            self.update_instruction(self)
        if self.start_callback is not None:
            self.start_callback()

    def stop_picking(self):
        self.__removeInteractionObserverTags()
        self.__removeMarkupsObserverTags()
        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        interactionNode.SetPlaceModePersistence(0)
        interactionNode.SetCurrentInteractionMode(2)
        interactionNode.SwitchToViewTransformMode()
        slicer.modules.AppContextInstance.mainWindow.removeEventFilter(self)

    def cancel_picking(self):
        if self.markups_node is not None:
            self.markups_node.EndModify(True)
        self.stop_picking()
        if self.markups_node is not None:
            self.markups_node.StartModify()
            self.markups_node.EndModify(False)
        self.__reset_markups_node()
        self.cancel_callback()

    def format_markups(self, format="P%d", glyph="Cross2D", glyph_scale=5.0, disable_text=None):
        self.markups_node.SetMarkupLabelFormat(format)
        display_node = self.markups_node.GetDisplayNode()
        if display_node is not None:
            display_node.SetGlyphTypeFromString(glyph)
            display_node.SetGlyphScale(glyph_scale)
            if disable_text is not None and disable_text:
                display_node.SetTextScale(0.0)
            else:
                display_node.SetTextScale(3.0)

    def get_selected_ras_points(self):
        return slicer.util.arrayFromMarkupsControlPoints(self.markups_node)

    def get_selected_ijk_points(self, volume_node=None, as_int=True):
        rasPoints = self.get_selected_ras_points()
        return self.__ras_to_ijk(rasPoints, volume_node, as_int=as_int)

    def get_number_of_selected_points(self):
        return self.markups_node.GetNumberOfControlPoints()

    def get_ras_point_position(self, point_index):
        ras_point = np.empty(3)
        self.markups_node.GetNthControlPointPosition(point_index, ras_point)
        return ras_point

    def get_ijk_point_position(self, point_index, volume=None):
        return self.__ras_to_ijk(self.get_ras_point_position(point_index)[None, :], volume)[0]

    def __reset_markups_node(self):
        if self.markups_node is not None:
            self.markups_node.RemoveAllControlPoints()

    def __removeInteractionObserverTags(self):
        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        if interactionNode is not None:
            if self.interaction_observer_tags is not None:
                for tag in self.interaction_observer_tags:
                    interactionNode.RemoveObserver(tag)
        return False

    def __removeMarkupsObserverTags(self):
        if self.markups_node is not None:
            if self.markups_observer_tags is not None:
                for tag in self.markups_observer_tags:
                    self.markups_node.RemoveObserver(tag)
        return False

    def __ras_to_ijk(self, ras, volume_node=None, as_int=True):
        if volume_node is None:
            volume_node = slicer.mrmlScene.GetNodeByID(self.markups_node.GetNthControlPointAssociatedNodeID(0))
        if volume_node is None:
            self.__reset_markups_node()
            return
        ras1Arr = np.c_[ras, np.ones((ras.shape[0], 1))]
        ras_to_ijk = vtk.vtkMatrix4x4()
        volume_node.GetRASToIJKMatrix(ras_to_ijk)
        ras_to_ijkArr = slicer.util.arrayFromVTKMatrix(ras_to_ijk)
        ijk1 = (ras_to_ijkArr @ ras1Arr.T).T
        ijk = ijk1[:, :3]
        if as_int:
            ijk = np.round(ijk).astype(int)
        return ijk

    def _get_markup_ijk_indices(self, volume_node=None, as_int=True):
        rasPoints = slicer.util.arrayFromMarkupsControlPoints(self.markups_node)
        return self.__ras_to_ijk(rasPoints, volume_node, as_int=as_int)


class MarkupLine(Markup):
    def __init__(
        self,
        finish_callback,
        finish_criterion=None,
        pick_criterion=None,
        update_instruction=None,
        start_callback=None,
        cancel_callback=None,
        after_finish_callback=None,
        parent=None,
    ):
        super().__init__(
            Markup.LINE_MARKUP_TYPE,
            finish_callback,
            finish_criterion,
            pick_criterion,
            update_instruction,
            start_callback,
            cancel_callback,
            after_finish_callback,
            parent,
        )

    def get_line_length_in_pixels(self, volume=None):
        line_points = self.get_selected_ijk_points(volume)
        i_distance = line_points[0, 0] - line_points[1, 0]
        j_distance = line_points[0, 1] - line_points[1, 1]
        line_length = math.sqrt(i_distance**2 + j_distance**2)
        return line_length


class MarkupFiducial(Markup):
    def __init__(
        self,
        finish_callback,
        finish_criterion=None,
        pick_criterion=None,
        update_instruction=None,
        start_callback=None,
        cancel_callback=None,
        after_finish_callback=None,
        parent=None,
    ):
        super().__init__(
            Markup.FIDUCIAL_MARKUP_TYPE,
            finish_callback,
            finish_criterion,
            pick_criterion,
            update_instruction,
            start_callback,
            cancel_callback,
            after_finish_callback,
            parent,
        )
