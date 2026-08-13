import logging
import random
import numpy as np
import slicer
import vtk
import vtk.util.numpy_support
import vtkSegmentationCorePython as vtkSegmentationCore

from ltrace.slicer.helpers import getSourceVolume


def _numpy_from_vtk_image(image_data):
    """Extracts numpy array (Z, Y, X) from a vtkImageData-like object."""
    if not image_data:
        return None

    point_data = image_data.GetPointData()
    if not point_data:
        return None

    sc = point_data.GetScalars()
    if sc is None:
        return None

    arr = vtk.util.numpy_support.vtk_to_numpy(sc)
    dims = image_data.GetDimensions()
    return arr.reshape(dims[2], dims[1], dims[0])


def _iter_array_chunks(arr, num_chunks=None):
    """
    Generator that processes an array in random chunks.
    Yields (progress_percent, accumulator).
    """
    arr_flat = arr.ravel()
    size = arr_flat.size

    # Heuristic: approx 64MB per chunk if float64, otherwise dynamic
    if num_chunks is None:
        num_chunks = max(1, size // 2**26)

    accumulator = np.zeros(0, dtype=np.int64)
    indices = list(range(num_chunks))
    random.shuffle(indices)

    total_steps = len(indices)

    for step, k in enumerate(indices):
        start = (k * size) // num_chunks
        end = ((k + 1) * size) // num_chunks

        chunk = arr_flat[start:end]
        counts = np.bincount(chunk)

        # Resize accumulator if we encounter a larger label ID
        if counts.size > accumulator.size:
            new_acc = np.zeros(counts.size, dtype=np.int64)
            new_acc[: accumulator.size] = accumulator
            accumulator = new_acc

        accumulator[: counts.size] += counts
        progress_pct = int(((step + 1) / total_steps) * 100)
        yield progress_pct, accumulator


def _resample_roi_to_reference(roi_node, reference_geometry):
    """
    Resamples the ROI node binary mask to match the geometry of the reference.
    Returns the numpy boolean mask.
    """
    if not roi_node:
        return None

    # Get ROI Labelmap representation
    roi_segmentation = roi_node.GetSegmentation()
    if roi_segmentation.GetNumberOfSegments() == 0:
        return None

    roi_segment_id = roi_segmentation.GetNthSegmentID(0)
    roi_labelmap = slicer.vtkOrientedImageData()

    # Ensure representation exists
    if not roi_node.GetBinaryLabelmapRepresentation(roi_segment_id, roi_labelmap):
        roi_node.GetSegmentation().CreateRepresentation(
            slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName()
        )
        roi_node.GetBinaryLabelmapRepresentation(roi_segment_id, roi_labelmap)

    # Resample
    roi_resampled = slicer.vtkOrientedImageData()
    vtkSegmentationCore.vtkOrientedImageDataResample.ResampleOrientedImageToReferenceOrientedImage(
        roi_labelmap, reference_geometry, roi_resampled, False, False
    )

    return _numpy_from_vtk_image(roi_resampled)


def _get_node_geometry(node):
    """Extracts vtkOrientedImageData geometry from a node."""
    geometry = slicer.vtkOrientedImageData()

    # FIX: Check for generic vtkMRMLVolumeNode to handle both LabelMaps AND ScalarVolumes
    # (Source volumes are usually ScalarVolumeNodes, not LabelMapVolumeNodes)
    if node.IsA("vtkMRMLVolumeNode"):
        image_data = node.GetImageData()
        if image_data:
            ijk_to_ras = vtk.vtkMatrix4x4()
            node.GetIJKToRASMatrix(ijk_to_ras)

            # Apply parent transform if exists
            parent_transform = node.GetParentTransformNode()
            if parent_transform:
                world_transform = vtk.vtkMatrix4x4()
                parent_transform.GetMatrixTransformToWorld(world_transform)
                combined = vtk.vtkMatrix4x4()
                vtk.vtkMatrix4x4.Multiply4x4(world_transform, ijk_to_ras, combined)
                ijk_to_ras = combined

            geometry.SetGeometryFromImageToWorldMatrix(ijk_to_ras)
            dims = image_data.GetDimensions()
            geometry.SetDimensions(dims)
            geometry.SetExtent(0, dims[0] - 1, 0, dims[1] - 1, 0, dims[2] - 1)

    elif node.IsA("vtkMRMLSegmentationNode"):
        source_vol = getSourceVolume(node)
        if source_vol:
            return _get_node_geometry(source_vol)

        # Fallback to first valid segment geometry
        segmentation = node.GetSegmentation()
        for i in range(segmentation.GetNumberOfSegments()):
            seg_id = segmentation.GetNthSegmentID(i)
            rep = node.GetBinaryLabelmapInternalRepresentation(seg_id)
            if rep:
                geometry.DeepCopy(rep)
                break

    return geometry


def _get_denominator_voxels(target_node, roi_mask_array):
    """Calculates the total number of valid voxels (denominator) for proportions."""
    if roi_mask_array is not None:
        return np.count_nonzero(roi_mask_array)

    if target_node.IsA("vtkMRMLVolumeNode"):
        img = target_node.GetImageData()
        if img:
            dims = img.GetDimensions()
            return dims[0] * dims[1] * dims[2]

    elif target_node.IsA("vtkMRMLSegmentationNode"):
        source_vol = getSourceVolume(target_node)
        if source_vol and source_vol.GetImageData():
            dims = source_vol.GetImageData().GetDimensions()
            return dims[0] * dims[1] * dims[2]

        # Fallback
        segmentation = target_node.GetSegmentation()
        for i in range(segmentation.GetNumberOfSegments()):
            seg_id = segmentation.GetNthSegmentID(i)
            arr = slicer.util.arrayFromSegmentInternalBinaryLabelmap(target_node, seg_id)
            if arr is not None:
                return arr.size

    return 0


def process_labelmap_volume(node, roi_node):
    if roi_node:
        if roi_node.GetSegmentation().GetNumberOfSegments() == 0:
            raise ValueError("SOI has no segments")

    arr_ref = slicer.util.arrayFromVolume(node)
    if arr_ref is None:
        return

    # Work on copy to allow masking
    arr = arr_ref.copy()

    geometry = _get_node_geometry(node)

    roi_mask = None
    if roi_node:
        roi_mask = _resample_roi_to_reference(roi_node, geometry)
        if roi_mask is not None and roi_mask.max() == 0:
            raise ValueError("SOI's first segment is empty")

    total_voxels = _get_denominator_voxels(node, roi_mask)
    if total_voxels == 0:
        yield 100, {}, True
        return

    if roi_mask is not None:
        if roi_mask.shape == arr.shape:
            arr[roi_mask == 0] = 0
        else:
            # Fallback for shape mismatch (should be rare with correct geometry)
            logging.error(f"PropListWidget Error: ROI Shape {roi_mask.shape} != Volume {arr.shape}")
            yield 100, {}, True
            return

    for progress, counts in _iter_array_chunks(arr):
        is_final = progress == 100
        processed_denom = total_voxels * (progress / 100.0)

        props = {}
        if processed_denom > 0:
            for label_val, count in enumerate(counts):
                if label_val == 0 or count == 0:
                    continue
                props[label_val] = count / processed_denom

        yield progress, props, is_final


def process_segmentation_node(node, roi_node):
    segmentation = node.GetSegmentation()
    if segmentation.GetNumberOfSegments() == 0:
        raise ValueError("Segmentation has no segments")

    if roi_node:
        if roi_node.GetSegmentation().GetNumberOfSegments() == 0:
            raise ValueError("SOI has no segments")

        if getSourceVolume(node) != getSourceVolume(roi_node):
            raise ValueError("Segmentation and SOI do not have the same source")

    layer_groups = {}

    n_segments = segmentation.GetNumberOfSegments()
    for i in range(n_segments):
        seg_id = segmentation.GetNthSegmentID(i)
        layer_obj = node.GetBinaryLabelmapInternalRepresentation(seg_id)
        if not layer_obj:
            continue

        layer_addr = layer_obj.GetAddressAsString("")
        if layer_addr not in layer_groups:
            # Use copy
            arr = slicer.util.arrayFromSegmentInternalBinaryLabelmap(node, seg_id).copy()
            layer_groups[layer_addr] = {"array": arr, "map": {}, "geometry": layer_obj}

        segment = segmentation.GetSegment(seg_id)
        label_val = int(segment.GetLabelValue())
        layer_groups[layer_addr]["map"][label_val] = seg_id

    if not layer_groups:
        yield 100, {}, True
        return

    ref_geometry = _get_node_geometry(node)

    roi_mask_ref = None
    if roi_node:
        roi_mask_ref = _resample_roi_to_reference(roi_node, ref_geometry)
        if roi_mask_ref is not None and roi_mask_ref.max() == 0:
            raise ValueError("SOI's first segment is empty")

    total_voxels = _get_denominator_voxels(node, roi_mask_ref)

    if total_voxels == 0:
        yield 100, {}, True
        return

    current_props = {}
    processed_layers = 0
    total_layers = len(layer_groups)

    for layer_data in layer_groups.values():
        arr = layer_data["array"]
        seg_map = layer_data["map"]
        layer_geo = layer_data["geometry"]

        # Mask this specific layer
        if roi_node:
            layer_roi_mask = _resample_roi_to_reference(roi_node, layer_geo)
            if layer_roi_mask is not None and layer_roi_mask.shape == arr.shape:
                arr[layer_roi_mask == 0] = 0

        for progress, partial_counts in _iter_array_chunks(arr):
            global_progress = int(((processed_layers + (progress / 100)) / total_layers) * 100)

            for label_val, seg_id in seg_map.items():
                if label_val < partial_counts.size:
                    count = partial_counts[label_val]
                    if count > 0:
                        current_props[seg_id] = count / total_voxels

            yield global_progress, current_props, False

        processed_layers += 1

    yield 100, current_props, True
