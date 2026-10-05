"""Where a cluster's files live, from the cluster's side and from this machine's.

A cluster exports part of its filesystem over NFS, and the workstation reaches
it through a different prefix depending on the operating system:

    on the cluster            /nethome/...
    Linux workstation         /nethome/...   (mounted at the same path)
    Windows workstation       \\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\...

Handlers speak the cluster's POSIX paths, because that is what they send over
SSH. This module turns those into local paths, and holds the layout that used
to be hardcoded in every handler -- which is how one Windows literal ended up
copied into five files and broke every Linux workstation.

The layout is per-cluster, so it belongs to the host: ``storage_for(host)``
returns the storage for a given account, falling back to the defaults below
when the host's configuration says nothing. Deployments override it through
their account template.
"""

import os
import platform

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Optional


# Layout of the exported filesystem. A host's "storage" block overrides any of
# these keys; whatever it omits falls back here, so existing accounts and older
# templates keep working.
DEFAULT_STORAGE = {
    # The root as the cluster itself sees it.
    "cluster_root": "/nethome",
    # The same root as each kind of workstation sees it, keyed by
    # platform.system() lowercased.
    "local_root": {
        "windows": r"\\dfs.petrobras.biz\cientifico\cenpes\res",
        "linux": "/nethome",
        "darwin": "/nethome",
    },
    # Directories under the root, relative to it. Configured through templates
    # only: they are effectively frozen per deployment and not worth exposing.
    "dirs": {
        # The deployment prefix under cluster_root. Handlers that receive a
        # relative bin/script path resolve it against this.
        "root": "drp",
        "geoslicer_jobs": "drp/servicos/LTRACE/GEOSLICER/jobs",
        "microtom_jobs": "drp/microtom/geoslicer/remote/jobs",
        "monailabel": "drp/smart-segmenter/laminas",
        "krel_dataset": "drp/servicos/LTRACE/ROMULO/Giovanni/krel/filtrados",
    },
}

# Absolute paths that exist only on the cluster. They are outside the exported
# root, so there is no local counterpart and nothing here ever tries to make
# one -- keeping them separate from "storage" is what stops someone from
# "fixing" a local path that should not exist.
DEFAULT_REMOTE_PATHS = {
    "geoslicer_containers": "/atena/users/dibi/containers/geoslicer",
    "workflow_files": "/atena/tcr/ia-drp/banco_de_dados",
}


def running_on_cluster() -> bool:
    """Whether this GeoSlicer runs inside the cluster rather than on a workstation.

    GEOSLICER_MODE=Remote marks an instance running on a cluster VM. There the
    cluster's own filesystem *is* the local filesystem, so nothing is
    translated even on a platform that would otherwise use the share.
    """
    return os.getenv("GEOSLICER_MODE") == "Remote"


def current_platform() -> str:
    """The key into ``local_root`` for the machine we are on."""
    return platform.system().lower()


def _merged(defaults: Dict, override: Optional[Dict]) -> Dict:
    """One level of nesting deep, which is all this schema has."""
    result = dict(defaults)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            merged = dict(result[key])
            merged.update(value)
            result[key] = merged
        else:
            result[key] = value
    return result


class ClusterStorage:
    """The filesystem layout of one cluster account."""

    def __init__(self, storage: Optional[Dict] = None, remote_paths: Optional[Dict] = None) -> None:
        self._storage = _merged(DEFAULT_STORAGE, storage)
        self._remote_paths = _merged(DEFAULT_REMOTE_PATHS, remote_paths)

    # -- roots ------------------------------------------------------------

    @property
    def cluster_root(self) -> PurePosixPath:
        return PurePosixPath(self._storage["cluster_root"])

    @property
    def local_root(self) -> Path:
        """Where this machine reaches the cluster root.

        Inside the cluster there is nothing to translate. On a platform with no
        entry of its own, the cluster's own path is the best guess: that is
        right for any Linux-like client mounting the share in place, and it
        fails visibly rather than silently producing a Windows string.
        """
        if running_on_cluster():
            return Path(self.cluster_root)

        roots = self._storage.get("local_root") or {}
        configured = roots.get(current_platform())
        if not configured:
            return Path(self.cluster_root)

        return Path(configured)

    @property
    def local_roots(self) -> Dict:
        """Every configured local root, keyed by platform."""
        return dict(self._storage.get("local_root") or {})

    @property
    def dirs(self) -> Dict:
        """The configured directories, relative to the roots."""
        return dict(self._storage.get("dirs") or {})

    @property
    def translates(self) -> bool:
        """Whether local and cluster paths actually differ here."""
        return str(self.local_root) != str(self.cluster_root)

    # -- translation ------------------------------------------------------

    def to_local(self, remote_path) -> Path:
        """Where a cluster path can be opened from this process.

        Paths outside the exported root come back unchanged: there is no
        mapping for them, and rewriting one silently would be worse than
        letting the caller fail on it.
        """
        remote = PurePosixPath(remote_path)

        if not self.translates:
            return Path(remote)

        try:
            relative = remote.relative_to(self.cluster_root)
        except ValueError:
            return Path(remote)

        return self._join_local(relative)

    def to_remote(self, local_path) -> PurePosixPath:
        """The cluster path for something under any of the local roots.

        Every configured root is tried, not just this platform's: a value can
        arrive from a template written for another operating system, or be
        pasted by a colleague, and it still names the same folder. Accepts
        either separator style, since a UNC share is as often written
        "//host/share/..." as "\\\\host\\share\\...". A path that is already
        cluster-side passes through untouched.
        """
        text = str(local_path).replace("\\", "/")

        candidates = [str(self.local_root)] + list(self.local_roots.values())
        # Longest first, so a root nested inside another still matches the
        # more specific one.
        for root in sorted(candidates, key=len, reverse=True):
            root = str(root).replace("\\", "/").rstrip("/")
            if root and text.lower().startswith(root.lower()):
                return self.cluster_root / text[len(root) :].lstrip("/")

        return PurePosixPath(text)

    def _join_local(self, relative: PurePosixPath) -> Path:
        root = str(self.local_root)
        if root.startswith("\\\\") or root.startswith("//"):
            # A UNC share: build it with Windows semantics so the separators
            # come out right even when this runs on another platform.
            return Path(str(PureWindowsPath(root).joinpath(*relative.parts)))
        return Path(root).joinpath(*relative.parts)

    # -- named locations --------------------------------------------------

    def remote_dir(self, name: str) -> PurePosixPath:
        """A configured directory, as the cluster sees it."""
        try:
            return self.cluster_root / self._storage["dirs"][name]
        except KeyError:
            raise KeyError(f"No storage directory named '{name}'. Known: {sorted(self._storage['dirs'])}") from None

    def local_dir(self, name: str) -> Path:
        """A configured directory, as this machine sees it."""
        return self.to_local(self.remote_dir(name))

    def remote_path(self, name: str) -> PurePosixPath:
        """A cluster-only path, which has no local counterpart."""
        try:
            return PurePosixPath(self._remote_paths[name])
        except KeyError:
            raise KeyError(f"No remote path named '{name}'. Known: {sorted(self._remote_paths)}") from None

    def to_dict(self) -> Dict:
        return {"storage": dict(self._storage), "remote_paths": dict(self._remote_paths)}


def storage_for(host=None) -> ClusterStorage:
    """The storage layout for a host, or the defaults when there is no host.

    Handlers reloaded from disk build themselves before they are told which
    host they belong to, so a host of None has to be usable.
    """
    if host is None:
        return ClusterStorage()

    return ClusterStorage(
        storage=getattr(host, "storage", None),
        remote_paths=getattr(host, "remote_paths", None),
    )


# Convenience wrappers for callers that have no host in hand.
def to_local(remote_path) -> Path:
    return ClusterStorage().to_local(remote_path)


def to_remote(local_path) -> PurePosixPath:
    return ClusterStorage().to_remote(local_path)
