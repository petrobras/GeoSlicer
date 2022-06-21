import numpy as np
from os.path import isfile

import h5py as h5
from numpy.random.mtrand import RandomState

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import log_loss, accuracy_score

import multiprocessing

CPU_COUNT = multiprocessing.cpu_count()


class ClassifierPlugin:
    def __init__(self, nEstimators=8, maxDepth=6, seed=12345, n_jobs=None):
        rng = RandomState(seed)

        self.model = RandomForestClassifier(
            n_estimators=nEstimators, max_depth=maxDepth, n_jobs=n_jobs, random_state=rng
        )

    def _coerseToObsAndTarget(self, gen):
        observations = []
        targets = []

        for x, y in gen:
            observations.append(x.ravel())
            targets.append(y.flat[0])

        observations = np.array(observations)
        targets = np.array(targets)

        return observations, targets

    def fit_generator(self, dataGenerator):
        r = self.fit(*self._coerseToObsAndTarget(dataGenerator))
        return r

    def fit(self, observations, targets, validation=None):

        if validation:
            val_obs, val_targets = validation

        if observations.ndim > 2:
            features = observations.shape[1] * observations.shape[2] * observations.shape[3]
            observations = observations.reshape((observations.shape[0], features))
        if targets.ndim > 1:
            targets = targets.reshape(targets.shape[0])

        self.model.fit(observations, targets)

        return None

    def predict(self, X):
        return self.model.predict(X)
