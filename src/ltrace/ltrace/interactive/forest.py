"""The random forest: building one, labelling rows with it, and reading its confidence."""

import numpy as np
from concurrent.futures import ThreadPoolExecutor
from numba import njit
from sklearn.ensemble import RandomForestClassifier


PREDICT_N_JOBS = 4
UNCERTAINTY_MARGIN = 0.5
# Sized so one batch's accumulator fits a core's L2 cache.
PREDICT_ACCUMULATOR_BYTES = 1024 * 1024
PREDICT_MIN_BATCH_ROWS = 16_000


def uncertainty_mask_from_proba(proba):
    """Mask (1 = uncertain) of samples whose top two class probabilities are within
    UNCERTAINTY_MARGIN -- the pixels most worth annotating next."""
    if proba.shape[1] < 2:
        return np.zeros(proba.shape[0], dtype=np.uint8)
    top2 = np.partition(proba, -2, axis=1)[:, -2:]
    margin = top2[:, 1] - top2[:, 0]
    return (margin < UNCERTAINTY_MARGIN).astype(np.uint8)


def make_model(n_jobs):
    return RandomForestClassifier(
        n_estimators=64,
        n_jobs=n_jobs,
        warm_start=False,
        random_state=42,
        bootstrap=True,
        oob_score=True,
        min_impurity_decrease=0.001,
        class_weight="balanced",
    )


def _leaf_probability_tables(model):
    """Per-tree leaf -> class-probability lookup, float32 and explicitly normalized so the
    per-tree vote weight does not depend on the sklearn version."""
    tables = []
    for estimator in model.estimators_:
        table = np.array(estimator.tree_.value[:, 0, :], dtype=np.float64)
        totals = table.sum(axis=1, keepdims=True)
        totals[totals == 0] = 1.0  # an unreachable leaf; the row is never gathered
        tables.append(np.ascontiguousarray(table / totals, dtype=np.float32))
    return tables


@njit(nogil=True, cache=True)
def _accumulate_leaf_probabilities(leaves, table, proba):
    """Add one tree's leaf probabilities into the running per-row sum, gathering and
    adding in one pass under no GIL."""
    for row in range(leaves.shape[0]):
        leaf = leaves[row]
        for klass in range(proba.shape[1]):
            proba[row, klass] += table[leaf, klass]


def predict_in_batches(model, X):
    """Label every row of `X` by summing the trees' leaf probabilities."""
    if model.n_outputs_ != 1 or X.ndim != 2 or X.dtype != np.float32:
        return model.predict(X)
    if X.shape[0] == 0:
        return np.empty(0, dtype=model.classes_.dtype)

    n_classes = int(np.max(model.n_classes_))
    tables = _leaf_probability_tables(model)
    classes = model.classes_
    batch = max(PREDICT_MIN_BATCH_ROWS, PREDICT_ACCUMULATOR_BYTES // (n_classes * 4))

    def predict_batch(start):
        block = X[start : start + batch]
        proba = np.zeros((block.shape[0], n_classes), dtype=np.float32)
        for estimator, table in zip(model.estimators_, tables):
            # check_input=False: the dtype and shape sklearn would re-check per tree
            # are guaranteed above.
            _accumulate_leaf_probabilities(estimator.apply(block, check_input=False), table, proba)
        return classes.take(np.argmax(proba, axis=1))

    starts = range(0, X.shape[0], batch)
    threads = max(1, model.n_jobs or 1)
    if threads == 1:
        return np.concatenate([predict_batch(start) for start in starts])
    with ThreadPoolExecutor(max_workers=threads) as pool:
        return np.concatenate(list(pool.map(predict_batch, starts)))
