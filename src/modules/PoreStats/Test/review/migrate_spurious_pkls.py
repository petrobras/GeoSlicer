"""One-time migration of the spurious_*.pkl files from sklearn 1.0.2 -> 1.8.0.

These pickles were saved under sklearn 1.0.2 and fail to load under 1.8.0 with

    ValueError: node array from the pickle has an incompatible dtype:
      expected: …missing_go_to_left: u1 …
      got     : …7-field tuple (no missing_go_to_left)

plus, once the dtype is patched, `RandomForestClassifier` raises
`AttributeError: 'RandomForestClassifier' object has no attribute 'estimator'`
(the attribute was called `base_estimator` in 1.0.x), and each
`DecisionTreeClassifier` is missing `monotonic_cst` (added in sklearn 1.4).

This script:

  1. Upgrades the `Tree.nodes` ndarray dtype to the 8-field layout sklearn 1.8
     expects. `missing_go_to_left` defaults to 0 — only consulted when the
     training/inference data contains NaN feature values, which these pipelines
     don't produce.
  2. Aliases `model.estimator = model.base_estimator` on the forest so
     `BaseForest._get_estimator` finds what it wants.
  3. Adds `monotonic_cst = None` on each `DecisionTreeClassifier`.
  4. Re-pickles the dict ({"scaler", "model"}) under the current sklearn so
     subsequent loads need no workaround.

Run this script once inside GeoSlicer's Python (via the gs-exec skill or
`PythonSlicer.exe`) to migrate the files in-place. It is checked in for
audit / re-run if we bump sklearn again and the pickle format shifts further.
Nothing at CLI run time depends on it.
"""

import pickle
import warnings
from pathlib import Path

import numpy as np
from sklearn.tree._tree import Tree


OLD_NODE_DTYPE = np.dtype(
    [
        ("left_child", "<i8"),
        ("right_child", "<i8"),
        ("feature", "<i8"),
        ("threshold", "<f8"),
        ("impurity", "<f8"),
        ("n_node_samples", "<i8"),
        ("weighted_n_node_samples", "<f8"),
    ]
)

NEW_NODE_DTYPE = np.dtype(
    {
        "names": [
            "left_child",
            "right_child",
            "feature",
            "threshold",
            "impurity",
            "n_node_samples",
            "weighted_n_node_samples",
            "missing_go_to_left",
        ],
        "formats": ["<i8", "<i8", "<i8", "<f8", "<f8", "<i8", "<f8", "u1"],
        "offsets": [0, 8, 16, 24, 32, 40, 48, 56],
        "itemsize": 64,
    }
)


def _upgrade_state(state):
    if not isinstance(state, dict):
        return state
    nodes = state.get("nodes")
    if isinstance(nodes, np.ndarray) and nodes.dtype == OLD_NODE_DTYPE:
        new_nodes = np.zeros(nodes.shape, dtype=NEW_NODE_DTYPE)
        for name in OLD_NODE_DTYPE.names:
            new_nodes[name] = nodes[name]
        state["nodes"] = new_nodes
    return state


class _TreeStateUpgradingUnpickler(pickle._Unpickler):
    """Intercepts BUILD so we can upgrade tree state dicts on the fly."""

    def load_build(self):
        state = self.stack[-1]
        inst = self.stack[-2]
        if isinstance(inst, Tree):
            self.stack[-1] = _upgrade_state(state)
        super().load_build()

    dispatch = pickle._Unpickler.dispatch.copy()
    dispatch[pickle.BUILD[0]] = load_build


PKL_DIR = Path(__file__).resolve().parents[1] / "PoreStatsCLI" / "Libs" / "pore_stats" / "models" / "spurious_removal"


def main():
    for pkl_path in sorted(PKL_DIR.glob("spurious_*.pkl")):
        print(f"\n=== {pkl_path.name} ===")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with open(pkl_path, "rb") as f:
                obj = _TreeStateUpgradingUnpickler(f).load()

        model = obj["model"]
        if hasattr(model, "base_estimator") and not hasattr(model, "estimator"):
            model.estimator = model.base_estimator
        for est in model.estimators_:
            if not hasattr(est, "monotonic_cst"):
                est.monotonic_cst = None

        # Smoke-test predict on an all-zeros row of the right dimensionality.
        X = np.zeros((1, model.n_features_in_), dtype=np.float64)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pred = model.predict(X)
        print(f"  smoke predict: {pred}")

        with open(pkl_path, "wb") as f:
            pickle.dump(obj, f)
        print("  saved")


if __name__ == "__main__":
    main()
