import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from commons.interactive import features, features_3d, forest, resources, volume_3d
from commons.interactive.ipc import FeatureIndex, InterprocessPaths


def _volume(shape, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.random(shape) * 1000).astype(np.int16)


# Shapes chosen so np.argmax picks a different slab axis in each case, and so the
# last one is small enough that thickness hits the halo+1 floor for every feature.
@pytest.mark.parametrize("shape", [(12, 40, 40), (40, 12, 40), (20, 20, 20), (6, 6, 6)])
@pytest.mark.parametrize("feature", list(FeatureIndex))
def test_filter_into_plane_matches_whole_volume(shape, feature, monkeypatch):
    """The slabbed out-of-core filter is bit-for-bit the whole-volume filter."""
    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "1")  # clamped up to the halo+1 floor

    scale = features.FeatureScale.from_multiplier(1)
    volume = _volume(shape)
    calc_func = scale.definitions[feature]

    out = np.zeros(shape, dtype=np.float32)
    features_3d.filter_into_plane(volume, calc_func, scale.halo(feature), out)

    np.testing.assert_array_equal(out, np.asarray(calc_func(volume), dtype=np.float32))


def _fake_affinity(monkeypatch, allowed, physical):
    monkeypatch.setattr(resources.psutil, "cpu_count", lambda logical=True: physical)
    monkeypatch.setattr(resources.psutil.Process, "cpu_affinity", lambda self: allowed)


def test_available_cores_follows_a_restricted_affinity(monkeypatch):
    _fake_affinity(monkeypatch, allowed=list(range(4)), physical=26)
    assert resources.available_cores() == 4


def test_available_cores_ignores_hyperthreads(monkeypatch):
    _fake_affinity(monkeypatch, allowed=list(range(24)), physical=12)
    assert resources.available_cores() == 12


def test_available_cores_falls_back_to_physical(monkeypatch):
    monkeypatch.setattr(resources.psutil, "cpu_count", lambda logical=True: 8)

    def raise_not_implemented(self):
        raise NotImplementedError

    monkeypatch.setattr(resources.psutil.Process, "cpu_affinity", raise_not_implemented)
    assert resources.available_cores() == 8


# "wrap" is deliberately absent: it makes a voxel near one face depend on the
# opposite face, which no slabbing scheme can reproduce. Every mode the features
# actually use is local.
@pytest.mark.parametrize("mode", ["nearest", "mirror", "constant"])
def test_filter_into_plane_matches_whole_volume_for_any_local_filter_edge_mode(mode, monkeypatch):
    """Slab borders follow the FILTER's edge handling, not one dask happens to share."""
    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "1")
    volume = _volume((40, 12, 12))

    def calc_func(array):
        return gaussian_filter(array, sigma=2, mode=mode)

    out = np.zeros(volume.shape, dtype=np.float32)
    features_3d.filter_into_plane(volume, calc_func, int(4 * 2 + 0.5), out)

    np.testing.assert_array_equal(out, np.asarray(calc_func(volume), dtype=np.float32))


def test_slab_thickness_gives_every_core_a_slab(monkeypatch):
    """Thickness is the thickest slab that still keeps every worker busy."""
    monkeypatch.setattr(features_3d, "max_worker_threads", lambda: 11)
    monkeypatch.setattr(features_3d, "feature_mem_budget", lambda: 64 * 1024**3)
    scale = features.FeatureScale.from_multiplier(1)
    volume = _volume((512, 512, 512))

    sizes = []
    monkeypatch.setattr(features_3d.da, "store", lambda arr, out, **kwargs: sizes.append(arr.chunks[0]))
    features_3d.filter_into_plane(volume, lambda arr: arr, scale.halo(FeatureIndex.GAUSSIAN_D), np.zeros(1))

    assert sizes[0] == (47,) * 10 + (42,)


def test_slab_thickness_falls_back_to_the_halo_floor_under_a_tight_budget(monkeypatch):
    monkeypatch.setattr(features_3d, "max_worker_threads", lambda: 11)
    monkeypatch.setattr(features_3d, "feature_mem_budget", lambda: 1024**3)
    scale = features.FeatureScale.from_multiplier(1)
    volume = _volume((512, 512, 512))

    sizes = []
    monkeypatch.setattr(features_3d.da, "store", lambda arr, out, **kwargs: sizes.append(arr.chunks[0]))
    features_3d.filter_into_plane(volume, lambda arr: arr, scale.halo(FeatureIndex.GAUSSIAN_D), np.zeros(1))

    assert sizes[0][0] == scale.halo(FeatureIndex.GAUSSIAN_D) + 1


def _tiny_model(n_columns, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.random((200, n_columns)).astype(np.float32)
    model = forest.make_model(1)
    model.fit(X, (X[:, 0] > 0.5).astype(np.uint8))
    return model


def _saved(paths, key="result"):
    with np.load(paths.result) as saved:
        return saved[key].copy()


def test_slabbed_extent_predict_matches_the_whole_extent(tmp_path, monkeypatch):
    paths = InterprocessPaths(tmp_path)
    rng = np.random.default_rng(1)
    features = rng.random((1, len(FeatureIndex), 6, 5, 4)).astype(np.float32)
    feature_indices = [0, 2, 5]
    model = _tiny_model(len(feature_indices))
    extents = [0, 4, 0, 5, 0, 6]

    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "1")
    volume_3d.predict_and_save(model, features, extents, feature_indices, paths)
    slabbed = _saved(paths)
    assert paths.full_result_mmap.exists()  # the slab loop really ran

    monkeypatch.delenv(resources.SLAB_THICKNESS_ENV)
    monkeypatch.setattr(volume_3d, "feature_mem_budget", lambda: 1 << 40)
    volume_3d.predict_and_save(model, features, extents, feature_indices, paths)

    assert slabbed.shape == (6, 5, 4)
    np.testing.assert_array_equal(slabbed, _saved(paths))


def test_preview_extent_predict_keeps_the_uncertainty_map(tmp_path, monkeypatch):
    paths = InterprocessPaths(tmp_path)
    rng = np.random.default_rng(2)
    features = rng.random((1, len(FeatureIndex), 6, 5, 4)).astype(np.float32)
    model = _tiny_model(3)

    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "1")  # ignored: the preview never slabs
    volume_3d.predict_and_save(model, features, [0, 4, 0, 5, 0, 6], [0, 2, 5], paths, compute_uncertainty=True)

    uncertainty = _saved(paths, "uncertainty")
    assert uncertainty.shape == (6, 5, 4)
    assert set(np.unique(uncertainty)) <= {0, 1}


def _whole_volume_columns(source, feature_indices, scale):
    """The two-phase reference: filter each feature over the whole volume, then flatten."""
    n_channels = source.shape[3] if source.ndim == 4 else 1
    columns = []
    for channel in range(n_channels):
        block = source[..., channel] if source.ndim == 4 else source
        for index in feature_indices:
            columns.append(np.asarray(scale.definitions[FeatureIndex(index)](block), dtype=np.float32))
    return np.stack(columns).reshape(len(columns), -1).T


def test_fused_apply_matches_whole_volume_features(tmp_path, monkeypatch):
    paths = InterprocessPaths(tmp_path)
    scale = features.FeatureScale.from_multiplier(1)
    source = _volume((24, 18, 16), seed=5)
    feature_indices = [0, 1, 5]

    X = _whole_volume_columns(source, feature_indices, scale)
    model = forest.make_model(1)
    # Label from the gaussian column, so a slab margin that is too small shows up
    # as a wrong label rather than being masked by the raw-value column.
    model.fit(X, (X[:, 1] > 500).astype(np.uint8))
    expected = model.predict(X).reshape(source.shape)
    assert len(np.unique(expected)) > 1

    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "5")
    volume_3d.predict_full_3d(model, source, feature_indices, scale, paths)

    np.testing.assert_array_equal(_saved(paths), expected)


def test_fused_apply_matches_the_feature_memmap_path_on_two_channels(tmp_path, monkeypatch):
    """Pins the (channel outer, feature inner) column order the two paths must share."""
    paths = InterprocessPaths(tmp_path)
    scale = features.FeatureScale.from_multiplier(1)
    shape = (10, 12, 14)
    rng = np.random.default_rng(11)
    source = (rng.random(shape + (2,)) * 1000).astype(np.int16)
    feature_indices = [0, 2, 5]

    feature_mmap, n_channels = features_3d.allocate_feature_mmap(source, tmp_path / "features.mmap")
    features_3d.compute_feature_planes(source, feature_mmap, n_channels, list(FeatureIndex), scale)

    # Annotate every voxel, so the forest is trained on exactly the rows both paths
    # predict, and label from BOTH channels so a swapped column order really shows.
    k, j, i = np.meshgrid(*(np.arange(n) for n in shape), indexing="ij")
    labels = ((source[..., 0] > 500) ^ (source[..., 1] > 500)).astype(np.uint8)
    np.save(paths.annotation, np.stack([labels.ravel(), i.ravel(), j.ravel(), k.ravel()]))
    model = volume_3d.train_model(feature_mmap, paths, feature_indices)

    volume_3d.predict_and_save(model, feature_mmap, [0, shape[2], 0, shape[1], 0, shape[0]], feature_indices, paths)
    from_memmap = _saved(paths)
    assert len(np.unique(from_memmap)) > 1

    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "3")
    volume_3d.predict_full_3d(model, source, feature_indices, scale, paths)

    np.testing.assert_array_equal(_saved(paths), from_memmap)


def test_fused_apply_reports_progress_and_finishes_below_a_hundred(tmp_path, monkeypatch):
    paths = InterprocessPaths(tmp_path)
    scale = features.FeatureScale.from_multiplier(1)
    source = _volume((12, 8, 8), seed=6)
    feature_indices = [0]

    reported = []
    monkeypatch.setattr(volume_3d, "update_progress", lambda path, progress, message: reported.append(progress))
    monkeypatch.setenv(resources.SLAB_THICKNESS_ENV, "3")
    volume_3d.predict_full_3d(
        model=_tiny_model(1), source=source, feature_indices=feature_indices, scale=scale, paths=paths
    )

    assert reported == [0, 25, 50, 75, 99]


class _RecordingModel:
    """Stands in for the cached interactive forest, recording the n_jobs it predicts with."""

    n_classes_ = 2
    n_outputs_ = 2  # not 1, so predict_in_batches falls back to the predict() recorded below

    def __init__(self, n_jobs=1):
        self.n_jobs = n_jobs
        self.jobs_at_predict = []

    def predict(self, X):
        self.jobs_at_predict.append(self.n_jobs)
        return np.zeros(X.shape[0], dtype=np.uint8)


def test_full_apply_predicts_on_every_core_and_restores_n_jobs(tmp_path, monkeypatch):
    paths = InterprocessPaths(tmp_path)
    np.save(paths.inference_source, _volume((6, 5, 4)))
    monkeypatch.setattr(volume_3d, "available_cores", lambda: 7)
    model = _RecordingModel()

    returned = volume_3d.handle_task(
        {"action": "predict", "is_full_inference": True, "features": [0], "extents": [0, 4, 0, 5, 0, 6]},
        paths,
        model,
        features=None,
        original_shape=(6, 5, 4),
        scale=features.FeatureScale.from_multiplier(1),
    )

    assert model.jobs_at_predict == [7]
    assert model.n_jobs == 1  # previews go back to single-threaded
    assert returned is model
    assert not paths.inference_source.exists()


def test_fused_slab_plan_trades_workers_for_thickness_when_memory_is_tight():
    """At 2000^3 with 8 features: a roomy budget fills the cores, a tight one backs off."""
    at_2000 = dict(K=2000, plane_bytes=2000 * 2000 * 4, margin=33, n_columns=8, n_channels=1, cores=12)

    thickness, workers = volume_3d.fused_slab_plan(budget=32 * 1024**3, **at_2000)
    assert (thickness, workers) == (31, 8)

    tight_thickness, tight_workers = volume_3d.fused_slab_plan(budget=8 * 1024**3, **at_2000)
    assert tight_workers < workers
    assert (1 + 2 * 33 / tight_thickness) / tight_workers < (1 + 2 * 33 / 1) / 8  # beats filling the cores


def test_predict_batches_agree_with_a_single_call(monkeypatch):
    """Batching is invisible in the result, and each batch fills one accumulator."""
    rng = np.random.default_rng(13)
    X = rng.random((5000, 3)).astype(np.float32)
    model = _tiny_model(3)
    whole = model.predict(X)

    monkeypatch.setattr(forest, "PREDICT_ACCUMULATOR_BYTES", 0)  # so the row floor sets the batch
    monkeypatch.setattr(forest, "PREDICT_MIN_BATCH_ROWS", 700)
    accumulate = forest._accumulate_leaf_probabilities
    accumulator_rows = []
    monkeypatch.setattr(
        forest,
        "_accumulate_leaf_probabilities",
        lambda leaves, table, proba: (accumulator_rows.append(len(proba)), accumulate(leaves, table, proba))[1],
    )

    np.testing.assert_array_equal(forest.predict_in_batches(model, X), whole)
    # Every tree accumulates into the batch before the next batch starts.
    assert accumulator_rows[:: len(model.estimators_)] == [700] * 7 + [100]
