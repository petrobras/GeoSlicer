"""The NFS share is reached through a different prefix per platform. Getting
this wrong is silent: a Windows literal on Linux becomes a *relative* path, and
the handler that used it just fails to write its input file."""

import platform

import sys
import pytest

from pathlib import Path
from commons.remote.paths import ClusterStorage, storage_for, to_local, to_remote

WINDOWS_SHARE = r"\\dfs.petrobras.biz\cientifico\cenpes\res"

# The cluster paths each handler works in.
MICROTOM = "/nethome/drp/microtom/geoslicer/remote/jobs"
GEOSLICER_JOBS = "/nethome/drp/servicos/LTRACE/GEOSLICER/jobs"
KREL_DATASET = "/nethome/drp/servicos/LTRACE/ROMULO/Giovanni/krel/filtrados"


@pytest.fixture
def on(monkeypatch):
    """Pretend to be a given platform, optionally inside the cluster."""

    def _on(system, geoslicer_mode=None):
        monkeypatch.setattr(platform, "system", lambda: system)
        monkeypatch.delenv("GEOSLICER_MODE", raising=False)
        if geoslicer_mode is not None:
            monkeypatch.setenv("GEOSLICER_MODE", geoslicer_mode)

    return _on


class TestLinuxWorkstation:
    """The case that was broken: every handler built a Windows literal."""

    @pytest.mark.parametrize("remote", [MICROTOM, GEOSLICER_JOBS, KREL_DATASET])
    def test_cluster_paths_are_used_as_is(self, on, remote):
        on("Linux")
        assert to_local(remote) == Path(remote)

    @pytest.mark.skipif(sys.platform == "win32", reason="Not supported on Windows")
    def test_result_is_absolute(self, on):
        # The old literal produced a relative path on Linux, so os.mkdir failed
        # on the missing parents and the job was never submitted.
        on("Linux")
        assert to_local(MICROTOM).is_absolute()


class TestWindowsWorkstation:
    """Must keep producing exactly what the hardcoded literals produced."""

    @pytest.mark.parametrize(
        "remote, expected",
        [
            (MICROTOM, WINDOWS_SHARE + r"\drp\microtom\geoslicer\remote\jobs"),
            (GEOSLICER_JOBS, WINDOWS_SHARE + r"\drp\servicos\LTRACE\GEOSLICER\jobs"),
            (KREL_DATASET, WINDOWS_SHARE + r"\drp\servicos\LTRACE\ROMULO\Giovanni\krel\filtrados"),
        ],
    )
    def test_share_prefix_is_substituted(self, on, remote, expected):
        on("Windows")
        assert str(to_local(remote)) == expected


class TestInsideCluster:
    """GEOSLICER_MODE=Remote means this instance runs on a cluster VM, so the
    cluster's filesystem is the local one and nothing is translated."""

    def test_no_translation(self, on):
        on("Linux", geoslicer_mode="Remote")
        assert to_local(MICROTOM) == Path(MICROTOM)

    def test_beats_the_platform_check(self, on):
        on("Windows", geoslicer_mode="Remote")
        assert to_local(MICROTOM) == Path(MICROTOM)

    def test_other_values_are_not_special(self, on):
        on("Windows", geoslicer_mode="Local")
        assert str(to_local(MICROTOM)).startswith(WINDOWS_SHARE)


class TestOutsideTheShare:
    def test_unrelated_paths_are_untouched(self, on):
        # /atena is a different export with no Windows mapping; rewriting it
        # would be worse than leaving the caller to fail on it.
        on("Windows")
        assert to_local("/atena/users/dibi/containers/geoslicer") == Path("/atena/users/dibi/containers/geoslicer")

    def test_the_root_itself(self, on):
        on("Windows")
        assert to_local("/nethome") == Path(WINDOWS_SHARE)


class TestToRemote:
    """MonaiLabel takes a folder typed by the user and has to send the cluster
    path over SSH."""

    @pytest.mark.parametrize(
        "typed",
        [
            "//dfs.petrobras.biz/cientifico/cenpes/res/drp/smart-segmenter/x",
            r"\\dfs.petrobras.biz\cientifico\cenpes\res\drp\smart-segmenter\x",
            "//DFS.PETROBRAS.BIZ/cientifico/cenpes/res/drp/smart-segmenter/x",
        ],
        ids=["forward-slashes", "backslashes", "uppercase-host"],
    )
    def test_share_prefix_is_stripped(self, typed):
        assert str(to_remote(typed)) == "/nethome/drp/smart-segmenter/x"

    def test_cluster_path_passes_through(self):
        assert str(to_remote("/nethome/drp/smart-segmenter/x")) == "/nethome/drp/smart-segmenter/x"

    def test_round_trip(self, on):
        on("Windows")
        assert str(to_remote(to_local(GEOSLICER_JOBS))) == GEOSLICER_JOBS


class TestPerHostConfiguration:
    """The layout is shipped per deployment in the account template, so a host
    must be able to override any part of it and inherit the rest."""

    def test_defaults_apply_when_a_host_configures_nothing(self, on):
        on("Windows")
        storage = ClusterStorage()
        assert str(storage.local_dir("geoslicer_jobs")) == WINDOWS_SHARE + r"\drp\servicos\LTRACE\GEOSLICER\jobs"

    def test_a_different_company_root(self, on):
        on("Windows")
        storage = ClusterStorage(storage={"cluster_root": "/shared", "local_root": {"windows": r"\\nas\team"}})
        assert str(storage.remote_dir("geoslicer_jobs")) == "/shared/drp/servicos/LTRACE/GEOSLICER/jobs"
        assert str(storage.local_dir("geoslicer_jobs")) == r"\\nas\team\drp\servicos\LTRACE\GEOSLICER\jobs"

    def test_overriding_one_directory_leaves_the_others(self, on):
        on("Linux")
        storage = ClusterStorage(storage={"dirs": {"geoslicer_jobs": "acme/jobs"}})
        assert str(storage.remote_dir("geoslicer_jobs")) == "/nethome/acme/jobs"
        assert str(storage.remote_dir("microtom_jobs")) == "/nethome/drp/microtom/geoslicer/remote/jobs"

    def test_remote_paths_are_never_translated(self, on):
        # They live outside the exported root and have no local counterpart.
        on("Windows")
        storage = ClusterStorage()
        assert str(storage.remote_path("geoslicer_containers")) == "/atena/users/dibi/containers/geoslicer"

    def test_remote_paths_are_overridable(self, on):
        on("Linux")
        storage = ClusterStorage(remote_paths={"geoslicer_containers": "/opt/acme/containers"})
        assert str(storage.remote_path("geoslicer_containers")) == "/opt/acme/containers"
        assert str(storage.remote_path("workflow_files")) == "/atena/tcr/ia-drp/banco_de_dados"

    def test_an_unknown_platform_falls_back_to_the_cluster_path(self, on):
        # Better a path that visibly is not there than a Windows string on a
        # machine that cannot use one.
        on("FreeBSD")
        assert ClusterStorage().local_root == Path("/nethome")

    def test_unknown_names_say_what_exists(self):
        with pytest.raises(KeyError, match="geoslicer_jobs"):
            ClusterStorage().remote_dir("nope")

    def test_storage_for_tolerates_no_host(self):
        # Handlers are built before they are told which account they serve.
        assert str(storage_for(None).cluster_root) == "/nethome"
