from dask.callbacks import Callback
from ltrace.slicer.cli_utils import progressUpdate


class DaskCLICallback(Callback):
    def _pretask(self, key, dask, state):
        if not state:
            progressUpdate(0)
            return
        n_done = len(state["finished"])
        n_total = sum(len(state[k]) for k in ("ready", "waiting", "running")) + n_done
        progressUpdate(n_done / n_total if n_total else 0)
