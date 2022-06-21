import numpy as np
from scipy.ndimage import label, binary_closing, binary_opening
from sklearn.cluster import KMeans


def create_distance_mask(array, circle):
    x, y, r = circle
    xx, yy = np.meshgrid(np.arange(array.shape[2]), np.arange(array.shape[1]))
    dist = (xx - x) ** 2 + (yy - y) ** 2
    return dist < r**2


def normalize_intensity(array, target_slice_index):
    mean = array.mean(axis=(1, 2))
    std = array.std(axis=(1, 2))
    target_mean = array[target_slice_index].mean()
    target_std = array[target_slice_index].std()
    normalized = (array - mean[:, np.newaxis, np.newaxis]) / std[:, np.newaxis, np.newaxis]
    normalized = normalized * target_std + target_mean
    return normalized


def perform_kmeans_clustering(interval_data, initial_centroids):
    kmeans = KMeans(n_clusters=3, init=initial_centroids[:, np.newaxis], n_init=1, max_iter=100)
    result = kmeans.fit(interval_data[:, np.newaxis])
    return np.sort(result.cluster_centers_, axis=0)


def extract_largest_component(segment):
    labels, num_labels = label(segment)
    if num_labels > 0:
        largest_label = np.argmax(np.bincount(labels.flat)[1:]) + 1
        return labels == largest_label
    return segment


def apply_morphological_operations(segmented_array, n_segments, callback=lambda progress, message: None):
    kernel_a = np.ones((5, 1, 1), np.uint8)
    kernel_b = np.zeros((1, 3, 3), np.uint8)
    kernel_b[:, 1], kernel_b[:, :, 1] = 1, 1
    filtered = np.zeros_like(segmented_array)
    for i in range(1, n_segments + 1):
        callback((i - 1) / n_segments * 100, "Post-processing segmentation")
        mask = segmented_array == i
        mask = binary_closing(mask, kernel_a, iterations=2)
        mask = binary_opening(mask, kernel_b)
        filtered[mask] = i
    return filtered


def segment_cups(array, circle, initial_centroids, callback=lambda progress, message: None):
    callback(0, "Preparing image for cups segmentation")

    initial_centroids = np.array(initial_centroids)
    mean = array.mean()
    std = array.std()
    new_mean = 5500
    new_std = 3000

    array = (array - mean) / std * new_std + new_mean
    initial_centroids = (initial_centroids - mean) / std * new_std + new_mean

    original_shape = array.shape
    downsample_ratio = 2
    array = array[::downsample_ratio, ::downsample_ratio, ::downsample_ratio].astype(np.float32)
    circle = tuple(coord / downsample_ratio for coord in circle)
    mask = create_distance_mask(array, circle)
    mask = np.repeat(mask[np.newaxis, :, :], array.shape[0], axis=0)
    array[mask] = -1000

    array = normalize_intensity(array, array.shape[0] // 2)
    array[mask] = -1000

    range_ = initial_centroids[2] - initial_centroids[0]
    min_ = initial_centroids[0] - range_ / 2
    max_ = initial_centroids[2] + range_ / 2
    mask |= (array < min_) | (array > max_)
    array[mask] = -1000
    array = normalize_intensity(array, array.shape[0] // 2)
    array[mask] = -1000

    segmented = np.zeros_like(array)
    z_depth = array.shape[0]

    for i in range(0, z_depth, 10):
        callback(10 + i / z_depth * 50, "Segmenting cups")

        upper_bound = min(i + 10, z_depth)
        original_data = array[i:upper_bound, :]
        interval_data = original_data[original_data > -1000]

        if interval_data.size == 0:
            continue

        interval_data = interval_data[::3]
        interval_data = np.float32(interval_data)
        centers_sorted = perform_kmeans_clustering(interval_data, initial_centroids)

        thresholds = [[0]] + list((centers_sorted[:-1] + centers_sorted[1:]) / 2) + [[np.inf]]

        for j, (lower, upper) in enumerate(zip(thresholds[:-1], thresholds[1:]), 1):
            segment = (original_data > lower) & (original_data < upper)
            largest_component = extract_largest_component(segment)
            segmented[i:upper_bound][largest_component] = j

    sub_callback = lambda progress, message: callback(60 + progress * 0.4, message)
    filtered = apply_morphological_operations(segmented, 3, callback=sub_callback)

    upscaled_labelmap_array = np.repeat(np.repeat(np.repeat(filtered, 2, axis=0), 2, axis=1), 2, axis=2)
    upscaled_labelmap_array = upscaled_labelmap_array[: original_shape[0], : original_shape[1], : original_shape[2]]

    return upscaled_labelmap_array.astype(np.uint8)
