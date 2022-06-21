#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# from __future__ import print_function
#
# import logging
# import os, sys
# import traceback
# import itertools
#
# from ltrace.algorithms.common import ArrayProcessor, parseWindowFormat, bbox_3D, bbox_to_slices
#
# import vtk, slicer, slicer.util, mrml
#
# from pathlib import Path
# import numpy as np
# import json
#
# from PIL import Image
#
# from ltrace.algorithms.measurements import masking1d, sharding, textureProperties, labelmapProperties, scalarVolumeProperties
# from ltrace.algorithms.supervised import random_forest
# from ltrace.generators import InputData
# from ltrace import transforms
#
# from numba import typed
#
# DEFAULT_SETTINGS = 'settings.json'
#
#
# def getSpacing(node):
#     return np.array([i for i in node.GetSpacing()])
#
#
# def progressUpdate(value):
#     print(f"<filter-progress>{value}</filter-progress>")
#     sys.stdout.flush()
#
#
# def readExecutionArgs(args: str) -> dict:
#     if len(args) == 0:
#         return {}
#
#     if os.path.isdir(args):
#         args = os.path.join(args, DEFAULT_SETTINGS)
#
#     content = Path(args).read_text() if os.path.isfile(args) else args
#     return json.loads(content)
#
#
# def readFrom(volumeFile, builder):
#     sn = slicer.vtkMRMLNRRDStorageNode()
#     sn.SetFileName(volumeFile)
#     nodeIn = builder()
#     sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
#     return nodeIn
#
#
# def writeDataInto(volumeFile, dataVoxelArray, builder, reference=None, cropping_ras_bounds=None, kij=False):
#     sn_out = slicer.vtkMRMLNRRDStorageNode()
#     sn_out.SetFileName(volumeFile)
#     nodeOut = builder()
#
#     if reference:
#         # copy image information
#         nodeOut.Copy(reference)
#         if cropping_ras_bounds is not None:
#             # volume is cropped, move the origin to the min of the bounds
#             crop_origin = get_origin(dataVoxelArray, reference, cropping_ras_bounds, kij)
#             nodeOut.SetOrigin(crop_origin)
#
#         # reset the attribute dictionary, otherwise it will be transferred over
#         attrs = vtk.vtkStringArray()
#         nodeOut.GetAttributeNames(attrs)
#         for i in range(0, attrs.GetNumberOfValues()):
#             nodeOut.SetAttribute(attrs.GetValue(i), None)
#
#     # reset the data array to force resizing, otherwise we will just keep the old data too
#     nodeOut.SetAndObserveImageData(None)
#     slicer.util.updateVolumeFromArray(nodeOut, dataVoxelArray)
#     nodeOut.Modified()
#
#     sn_out.WriteData(nodeOut)
#
#
# def PorosityEstimationPlugin(args):
#     progressUpdate(value=0.1)
#
#     labelsVolumeNodeID = args.labelVolume
#     if not labelsVolumeNodeID:
#         raise ValueError('Missing label source.' + repr(labelsVolumeNodeID))
#
#     progressUpdate(value=0.2)
#
#     xargs = readExecutionArgs(args.xargs)
#     namedLabels = xargs['labels']
#     countLabels = len(namedLabels)
#
#     # read as slicer node
#     sourceVolumeNode = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)
#     spacing = getSpacing(sourceVolumeNode)
#
#     # access numpy view
#     sourceVolumeVoxelArray = slicer.util.arrayFromVolume(sourceVolumeNode)
#
#     labelVolumeNode = readFrom(labelsVolumeNodeID, mrml.vtkMRMLLabelMapVolumeNode)
#     labelVolumeVoxelArray = np.array(slicer.util.arrayFromVolume(labelVolumeNode), copy=True, dtype=np.uint8)
#
#     solid, macro, micro, total = textureProperties(sourceVolumeVoxelArray, labelVolumeVoxelArray, labels=namedLabels, spacing=spacing,
#                                                    stepCallback=lambda i: progressUpdate(i / countLabels))
#
#     report = {
#         'solid': [solid],
#         'macroporosity': [macro],
#         'microporosity': [micro],
#         'totalPorosity': [macro + micro],
#         'voxelCount': [total]
#     }
#
#     return report
#
#
# def get_ijk_from_ras_bounds(data, node, rasbounds, kij=False):
#     volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
#     node.GetRASToIJKMatrix(volumeRASToIJKMatrix)
#     # reshape bounds for a matrix of 3 collums and 2 rows
#     rasbounds = np.array([
#         [rasbounds[0], rasbounds[2], rasbounds[4]],
#         [rasbounds[1], rasbounds[3], rasbounds[5]]
#     ])
#
#     boundsijk = transforms.transformPoints(volumeRASToIJKMatrix, rasbounds, returnInt=True)
#
#     return boundsijk
#
#
# def crop_to_rasbounds(data, node, rasbounds, kij=False):
#     boundsijk = get_ijk_from_ras_bounds(data, node, rasbounds, kij)
#     boundsijk[:, 2] = [0, data.shape[0]]
#     arr, _ = transforms.crop_to_selection(data, np.fliplr(boundsijk))  # crop without copying
#
#     return arr
#
#
# def get_origin(data, node, rasbounds, kij=False):
#     boundsijk = get_ijk_from_ras_bounds(data, node, rasbounds, kij)
#     min_ijk = np.min(boundsijk, axis=0)
#     origin_ijk = np.repeat(min_ijk[np.newaxis, :], 2, axis=0)
#     volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
#     node.GetIJKToRASMatrix(volumeIJKToRASMatrix)
#     origin_ras = transforms.transformPoints(volumeIJKToRASMatrix, origin_ijk)
#     return origin_ras[0, :]
#
#
# def processVectorVolumes(volumes):
#     from skimage.color import rgb2hsv
#     from skimage.filters import gaussian
#
#     intersect_bounds = np.zeros(6)
#     volumes[0].GetRASBounds(intersect_bounds)
#
#     for volume in volumes[1:]:
#         bounds = np.zeros(6)
#         volume.GetRASBounds(bounds)
#         # intersect bounds by getting max of lower bounds and min of upper
#         intersect_bounds[0::2] = np.maximum(bounds[0::2], intersect_bounds[0::2])  # max of lower bounds
#         intersect_bounds[1::2] = np.minimum(bounds[1::2], intersect_bounds[1::2])  # min of upper bounds
#
#     components = []
#     for volume in volumes:
#         arr_original = slicer.util.arrayFromVolume(volume).astype(np.uint8)
#         arr = crop_to_rasbounds(arr_original, volume, intersect_bounds).transpose((1, 2, 0))
#         imquant_arr = np.array(Image.fromarray(arr, 'RGB').quantize(colors=256, method=2), dtype=np.uint8)
#
#         hsv = rgb2hsv(arr[:, :, :3])
#
#         components.extend([
#             imquant_arr,
#             hsv[:, :, 0] * 360,
#             hsv[:, :, 1] * 255,
#             hsv[:, :, 2] * 255,
#             *[gaussian(imquant_arr, sigma=(sigma, sigma), truncate=3.5, preserve_range=True)
#               for sigma in (1, 2, 4, 8, 16)]
#         ])
#
#     return np.stack(components), intersect_bounds
#
#
# def SegmentationMorphologyReportPlugin(args):
#     progressUpdate(value=0.1)
#
#     labelsVolumeNodeID = args.labelVolume
#     if not labelsVolumeNodeID:
#         raise ValueError('Missing label source.' + repr(labelsVolumeNodeID))
#
#     outputNodeID = args.outputVolume
#     if outputNodeID is None:
#         raise ValueError('Missing output node')
#
#     """ Read the execution parameters """
#     xargs = readExecutionArgs(args.xargs)
#
#     target_ids_values = xargs.get('target_ids', None)
#     segments = xargs.get('labels', None)
#     if target_ids_values is None or segments is None:
#         return {}         # nothing to do here
#
#     target_ids = typed.List(tid for tid in target_ids_values)
#
#     orientation_line = xargs.get('orientation_line', [])
#
#     params = xargs.get('parameters', {})
#     volume_threshold = params.get('volume_threshold', 100)
#     filter_stddev = params.get('filter_stddev', .4)
#     peak_proximity = params.get('peak_proximity', 6)
#     measures = xargs.get('measures', None)
#
#     labelVolumeNode = readFrom(labelsVolumeNodeID, mrml.vtkMRMLLabelMapVolumeNode)
#     labelVolumeVoxelArray = slicer.util.arrayFromVolume(labelVolumeNode)
#
#     # read as slicer node
#     if args.inputVolume:
#         sourceVolumeNode = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)
#     else:
#         sourceVolumeNode = labelVolumeNode
#
#     spacing = getSpacing(sourceVolumeNode)
#     sourceVolumeVoxelArray = slicer.util.arrayFromVolume(sourceVolumeNode)
#
#     progressUpdate(value=0.3)
#
#     labelmap, validLabels = sharding(
#         masking1d(labelVolumeVoxelArray.ravel(), targets=target_ids).reshape(labelVolumeVoxelArray.shape),
#         sigma=filter_stddev,
#         neighborhood=peak_proximity,
#         volume_threshold=volume_threshold
#     )
#
#     progressUpdate(value=0.0)
#
#     if xargs.get('is_preview', False) or measures is None:
#         # TODO check if larger than 255 remove smalls
#         writeDataInto(outputNodeID, labelmap, mrml.vtkMRMLLabelMapVolumeNode, reference=labelVolumeNode)
#         progressUpdate(value=1.0)
#         return {}
#
#     report = {}
#
#     validLabels.sort()
#     bins = np.bincount(labelmap.ravel())
#
#     report["voxelCount"] = [bins[i] for i in range(1, len(bins))]
#     report["name"] = {label: f"Segment_{n}" for n, label in enumerate(validLabels, start=1)}
#
#     reportScalar = scalarVolumeProperties(sourceVolumeVoxelArray, labelmap, validLabels, measures=measures,
#                                           volume_threshold=volume_threshold,
#                                           spacing=spacing,
#                                           stepCallback=lambda i, l: progressUpdate(i / len(validLabels)))
#
#     # Calculating the core center for each slice in RAS coordinates
#     volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
#     sourceVolumeNode.GetIJKToRASMatrix(volumeIJKToRASMatrix)
#
#     reportLabelmap = labelmapProperties(labelmap, validLabels, measures=measures, volume_threshold=volume_threshold,
#                                         spacing=spacing,
#                                         IJKToRASMatrix=volumeIJKToRASMatrix,
#                                         orientationLine=orientation_line,
#                                         stepCallback=lambda i, l: progressUpdate(i / len(validLabels)))
#
#     report.update(reportScalar)
#     report.update(reportLabelmap)
#
#     progressUpdate(value=0.0)
#     writeDataInto(outputNodeID, labelmap, mrml.vtkMRMLLabelMapVolumeNode, reference=labelVolumeNode)
#     progressUpdate(value=1.0)
#
#     return report
#
#
#
# def predict2d(kernel, X, M, out=None, size=1024):
#     if out is None:
#         out = np.zeros((1, M.shape[1], M.shape[2]))
#
#     for ij, batch in walk2d(X, M, batch_size=size):
#         y = kernel(batch)
#         out[0, ij[:, 0], ij[:, 1]] = y
#
#     return out
#
#
# def walk2d(X, M, batch_size=1024):
#     features, rows, cols = X.shape
#     x_batch = np.zeros((batch_size, features), dtype=X.dtype)
#     ij_batch = np.zeros((batch_size, 2), dtype=int)
#     batch_row_ptr = 0
#     for i, j in itertools.product(range(rows), range(cols)):
#         if M[0, i, j] != 0:
#             x_batch[batch_row_ptr, ...] = X[:, i, j]
#             ij_batch[batch_row_ptr] = [i, j]
#             batch_row_ptr += 1
#             if batch_row_ptr >= batch_size:
#                 batch_row_ptr = 0
#                 yield ij_batch, x_batch
#
#     if batch_row_ptr > 0:
#         yield ij_batch[:batch_row_ptr], x_batch[:batch_row_ptr, ...]
#
#
# class Observed:
#     def __init__(self, kernel, total):
#         self.kernel = kernel
#         self.total = total
#         self.acc = 0
#
#     def __call__(self, batch: np.ndarray):
#         self.acc += batch.size
#         progress = self.acc / self.total
#         y = self.kernel(batch)
#         progressUpdate(value=progress)
#         return y
#
#
# def SupervisedEstimatorWrapperPlugin(args):
#     progressUpdate(value=0.1)
#
#     availableModels = {
#         'superpixel': lambda conf: random_forest.ClassifierPlugin(nEstimators=conf['nEstimators'], maxDepth=conf['maxDepth'], n_jobs=conf['n_jobs']),
#         'random_forest': lambda conf: random_forest.ClassifierPlugin(nEstimators=conf['nEstimators'], maxDepth=conf['maxDepth'], n_jobs=conf['n_jobs']),
#         'xgboost': lambda conf: random_forest.ClassifierPlugin(nEstimators=conf['nEstimators'], maxDepth=conf['maxDepth'], n_jobs=conf['n_jobs'])
#     }
#
#     outputNodeID = args.outputVolume
#     if outputNodeID is None:
#         raise ValueError('Missing output node')
#
#     xargs = readExecutionArgs(args.xargs)
#     modelConf = xargs['model']
#     labels = xargs['labels']
#
#     baseModelID = modelConf['method']
#
#     intersect_bounds = None
#     # access numpy view
#     if modelConf.get('isThinPlate', False):
#         volumes = []
#         sourceVolumeNode = readFrom(args.inputVolume, mrml.vtkMRMLLabelMapVolumeNode)
#         volumes.append(sourceVolumeNode)
#         if args.inputVolumeAdd1:
#             add1VolumeNode = readFrom(args.inputVolumeAdd1, mrml.vtkMRMLLabelMapVolumeNode)
#             volumes.append(add1VolumeNode)
#         if args.inputVolumeAdd2:
#             add2VolumeNode = readFrom(args.inputVolumeAdd2, mrml.vtkMRMLLabelMapVolumeNode)
#             volumes.append(add2VolumeNode)
#         sourceVolumeVoxelArray, intersect_bounds = processVectorVolumes(volumes)
#         windowShape, winStep, winType = [(sourceVolumeVoxelArray.shape[0], 1, 1), 1, "full"]
#         modelConf['n_jobs'] = 4
#     else:
#         # read as slicer node
#         sourceVolumeNode = readFrom(args.inputVolume, mrml.vtkMRMLScalarVolumeNode)
#         sourceVolumeVoxelArray = slicer.util.arrayFromVolume(sourceVolumeNode)
#         windowShape, winStep, winType = parseWindowFormat(modelConf['inputWindowFormat'])
#
#     modelBuilder = availableModels.get(baseModelID, None)
#     if modelBuilder is None:
#         logging.warning('Model not available. Fallbacking to Random Forest.')
#         model = availableModels['random_forest'](modelConf)
#     else:
#         model = modelBuilder(modelConf)
#
#     progressUpdate(value=0.2)
#
#     winStep = 1  # TODO winStep ta com um bug, vou trocar pra um outro mecanismo melhor futuramente
#
#     # TODO usar lógica do segment inspector para cropar com o ROI pois está mais eficiente.
#     try:
#         if args.roiVolume:
#             roiVolumeNode = readFrom(args.roiVolume, mrml.vtkMRMLLabelMapVolumeNode)
#             roiVolumeVoxelArray = slicer.util.arrayFromVolume(roiVolumeNode).astype(np.uint8)
#             if intersect_bounds is not None:
#                 roiVolumeVoxelArray = crop_to_rasbounds(roiVolumeVoxelArray, roiVolumeNode, intersect_bounds, kij=True)
#         else:
#             shape = sourceVolumeVoxelArray.shape
#             roiVolumeVoxelArray = np.ones(shape, dtype=np.uint8)
#
#         if args.labelVolume is None:
#             raise ValueError('LabelMap cannot be NoneType')
#
#         labelmapVolumeNode = readFrom(args.labelVolume, mrml.vtkMRMLLabelMapVolumeNode)
#         labelVolumeVoxelArray = slicer.util.arrayFromVolume(labelmapVolumeNode)
#         if intersect_bounds is not None:
#             labelVolumeVoxelArray = crop_to_rasbounds(labelVolumeVoxelArray, labelmapVolumeNode, intersect_bounds, kij=True)
#
#         X, y = InputData.training(
#             sourceVolumeVoxelArray,
#             labelVolumeVoxelArray,
#             shapeX=windowShape,
#             shapeY=(1, 1, 1),
#             labels=labels,
#             step=winStep,
#             label_sample_size=10000
#         )
#
#         model.fit(X, y)
#
#         if modelConf.get('isThinPlate', False):
#             origShape = sourceVolumeVoxelArray.shape
#             bbox = bbox_3D(roiVolumeVoxelArray)
#             bboxROI_slices = bbox_to_slices(bbox)
#             bboxROI = roiVolumeVoxelArray[bboxROI_slices]
#             X = sourceVolumeVoxelArray[:, bboxROI_slices[1], bboxROI_slices[2]]
#             observableKernel = Observed(model.predict, bboxROI.size)
#             outputArray = np.zeros((1, origShape[1], origShape[2]), dtype=np.uint8)
#             predict2d(observableKernel, X, bboxROI, out=outputArray[bboxROI_slices], size=2**20)
#         else:
#             man = ArrayProcessor()
#             outputArray = man.process(model, sourceVolumeVoxelArray, roiVolumeVoxelArray, windowShape, parallel=True)
#
#         progressUpdate(value=0.1)
#         writeDataInto(outputNodeID, outputArray, mrml.vtkMRMLLabelMapVolumeNode, reference=sourceVolumeNode, cropping_ras_bounds=intersect_bounds, kij=True)
#         progressUpdate(value=1.0)
#     except Exception as e:
#         traceback.print_exc(file=sys.stdout)
#
#     return {}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--master", type=str, dest="inputVolume", default=None, help="Intensity Input Values")
    parser.add_argument("--add1", type=str, dest="inputVolumeAdd1", default=None, help="Variant Intensity Input Values")
    parser.add_argument("--add2", type=str, dest="inputVolumeAdd2", default=None, help="Variant Intensity Input Values")
    parser.add_argument("--labels", type=str, dest="labelVolume", default=None, help="Labels Input (3d) Values")
    parser.add_argument("--roi", type=str, dest="roiVolume", default=None, help="ROI Input (3d) Values")
    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap (3d) Values"
    )
    parser.add_argument("-c", "--command", type=str, default="none", help="Command specification")
    parser.add_argument("-x", "--xargs", type=str, default="", help="Model configuration string")
    parser.add_argument("--returnparameterfile", type=str, help="File destination to store an execution outputs")

    args = parser.parse_args()

    print("Done")
