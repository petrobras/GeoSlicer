import hashlib

import numpy as np
from scipy import ndimage

from slicer import util


class undoManager:
    """
    Manager for Undo and Redo operations
    Can be used with only the instance created at import
    TODO: Contains placeholder function for unimplemented uses

    Changes to volumeNodes must be made through undoManager functions

    Undo stages only save a bounding box view of the differecnce between arrays

    Usage example:
    from scipy import ndimage
    import numpy as np

    from ltrace.slicer.undo import manager
    import slicer

    # must be called only once, before any undoable changes are performed
    manager.start_managing(volumeNode) #must be called only once, before any undoable changes are performed

    # for each modification step, create an array with the new values and pass it along the
    # volumeNode reference and the bbox for the view of the changed array region to the
    # modify_and_save function
    array = slicer.util.arrayFromVolume(volumeNode)
    modified_array = np.where(array == value, new_value, array)
    bbox = ndimage.find_objects(array == new_value)[0]
    manager.modify_and_save(volumeNode, modified_array[bbox], bbox_slices=bbox)

    # to undo and redo saved states
    manager.undo(volumeNode)
    manager.redo(volumeNode)
    """

    MAX_UNDO = 5

    def __init__(self):
        self.managed_nodes = {}

    def start_managing(self, volumeNode, verify=False):
        """
        Initialize volume state management. Verify checks hashes of states,
        but can take too much time when used with large data.
        """
        node_id = volumeNode.GetID()
        if node_id in self.managed_nodes.keys():
            raise ValueError(f"Volume node '{node_id}' is already managed")
        self.managed_nodes[node_id] = {"saved states": [], "current stage": 0, "verify": verify}

    def undo(self, volumeNode):
        node_id = volumeNode.GetID()
        saved_states = self.managed_nodes[node_id]["saved states"]
        current_stage = self.managed_nodes[node_id]["current stage"]
        verify = self.managed_nodes[node_id]["verify"]

        if self.managed_nodes[node_id]["current stage"] > (len(saved_states) - 1):
            print(
                f"Cannot undo with node {node_id}, "
                f"undoing stage {self.managed_nodes[node_id]['current stage']} "
                f"with {len(saved_states)} saved states"
            )
            return 1

        origin_array = util.arrayFromVolume(volumeNode)

        if verify:
            saved_hash = saved_states[current_stage]["current_hash"]
            current_hash = hashlib.sha256(origin_array).hexdigest()
            if current_hash != saved_hash:
                print("Cannot undo, array has unsaved changes")
                saved_states[:] = []
                self.managed_nodes[node_id]["current stage"] = 0
                return 1

        bbox = saved_states[current_stage]["bbox_slices"]
        delta_array = saved_states[current_stage]["delta_array"]
        origin_array[bbox] = np.add(origin_array[bbox], delta_array, casting="unsafe")
        util.arrayFromVolumeModified(volumeNode)
        self.managed_nodes[node_id]["current stage"] += 1
        return 0

    def redo(self, volumeNode):
        node_id = volumeNode.GetID()
        saved_states = self.managed_nodes[node_id]["saved states"]
        current_stage = self.managed_nodes[node_id]["current stage"]
        verify = self.managed_nodes[node_id]["verify"]

        if self.managed_nodes[node_id]["current stage"] == 0:
            print(f"Cannot redo with node {node_id}, no undone stage")
            return 1

        origin_array = util.arrayFromVolume(volumeNode)

        if verify:
            current_hash = hashlib.sha256(origin_array).hexdigest()
            try:
                saved_hash = saved_states[current_stage]["current_hash"]
                if current_hash != saved_hash:
                    print(f"Hashes: {current_hash}, {saved_hash}")
                    print("Cannot undo, array has unsaved changes")
                    saved_states[:] = []
                    self.managed_nodes[node_id]["current stage"] = 0
                    return 1
            except IndexError:
                pass  # BUG/TODO Hash is not checked for redo from last saved state, since the array hash is not stored

        bbox = saved_states[current_stage - 1]["bbox_slices"]
        delta_array = saved_states[current_stage - 1]["delta_array"]
        origin_array[bbox] = np.subtract(origin_array[bbox], delta_array, casting="unsafe")
        util.arrayFromVolumeModified(volumeNode)
        self.managed_nodes[node_id]["current stage"] -= 1
        return 0

    def modify_and_save(self, volumeNode, new_array, bbox_slices=None):
        node_id = volumeNode.GetID()
        save_hash = self.managed_nodes[node_id]["verify"]

        origin_array = util.arrayFromVolume(volumeNode)
        if not bbox_slices:
            raise Exception("Not implemented yet")
            current_array = ndimage.find_objects(image >= 1)[value - 1]
        else:
            delta_array = origin_array[bbox_slices] - new_array

        origin_array[bbox_slices] = new_array
        util.arrayFromVolumeModified(volumeNode)

        if save_hash:
            current_hash = hashlib.sha256(origin_array).hexdigest()
        else:
            current_hash = None

        new_state = {
            "bbox_slices": bbox_slices,
            "delta_array": delta_array,
            "current_hash": current_hash,
        }
        self._add_state(volumeNode, new_state)
        return 0

    def modify_and_cache(self, volumeNode, new_array, bbox=None):
        raise Exception("Not implemented yet")

    def save_cached(self, volumeNode):
        raise Exception("Not implemented yet")

    def _add_state(self, volumeNode, new_state):
        node_id = volumeNode.GetID()
        saved_states = self.managed_nodes[node_id]["saved states"]

        if node_id not in self.managed_nodes:
            raise ValueError(f"Volume node '{node_id}' is not managed")

        if self.managed_nodes[node_id]["current stage"] > 0:
            current_stage = self.managed_nodes[node_id]["current stage"]
            saved_states[:] = saved_states[current_stage:]
            self.managed_nodes[node_id]["current stage"] = 0

        saved_states.insert(0, new_state)
        saved_states[:] = saved_states[: undoManager.MAX_UNDO]

        return 0

    @staticmethod
    def _bbox_tuple_to_slices(bbox_tuple):
        """
        Bounding box (min_row, min_col, max_row, max_col).
        Pixels belonging to the bounding box are in the half-open
        interval [min_row; max_row) and [min_col; max_col).
        """
        min_row, min_col, max_row, max_col = bbox_tuple
        return (slice(0, 1, None), slice(min_col, max_col, None), slice(min_row, max_row, None))


"""        
class nodeSavedState():

    def __init__(self, original_state, new_state, bbox=None):
        self.bbox_slices = None
        self.delta_array = None
        self.current_hash = None
"""

manager = undoManager()
