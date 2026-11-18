import shutil
import tempfile
import unittest

from commons.remote.hosts.base import Host
from commons.remote.hosts.ssh.ssh import SshHost
from commons.remote.hosts.utils import (
    get_host_subclasses_from_module,
    get_module_from_path,
    get_modules,
    get_host_subclasses,
    protocol_to_host,
    rglob,
)
from pathlib import Path
from unittest.mock import patch, MagicMock


class MockHost1(Host):
    protocol = "mock1"


class MockHost2(Host):
    protocol = "mock2"


class MockHost3(Host):
    protocol = "mock3"


class RemoteHostsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp())
        # Create a structure that satisfies HOSTS_DIRS[0].parents[3]
        # HOSTS_DIRS[0] is src/commons/remote/hosts
        # parents[3] is the root.
        host_dir = self.temp_root / "src" / "commons" / "remote" / "hosts"
        host_dir.mkdir(parents=True)
        self.hosts_test_dir = [host_dir]

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root)

    def test_rglob(self):
        # Create a few files and a symlink
        file1 = self.hosts_test_dir[0] / "file1.py"
        file1.touch()
        subdir = self.hosts_test_dir[0] / "sub"
        subdir.mkdir()
        file2 = subdir / "file2.py"
        file2.touch()
        other = self.hosts_test_dir[0] / "other.txt"
        other.touch()

        # Test finding .py files
        results = rglob(self.hosts_test_dir[0], "*.py")
        assert len(results) == 2
        assert file1 in results
        assert file2 in results
        assert other not in results

    def test_get_host_subclasses_from_module(self):
        module = MagicMock()
        module.MockHost1 = MockHost1
        module.MockHost2 = MockHost2

        subclasses = get_host_subclasses_from_module(module)
        assert isinstance(subclasses, list)
        assert len(subclasses) == 2
        assert MockHost1 in subclasses
        assert MockHost2 in subclasses

    def test_get_module_from_path(self):
        with patch("commons.remote.hosts.utils.HOSTS_DIRS", self.hosts_test_dir):
            test_module_path = self.hosts_test_dir[0] / "test_module.py"
            with test_module_path.open("w") as f:
                f.write(
                    "from commons.remote.hosts.base import Host\n"
                    "class TestHost(Host):\n"
                    "    protocol = 'test_protocol'\n"
                )

            test_module = get_module_from_path(test_module_path, self.hosts_test_dir[0])
            assert test_module is not None
            assert hasattr(test_module, "TestHost")
            assert issubclass(test_module.TestHost, Host)
            assert test_module.__name__.startswith("remote.src.commons.remote.hosts")

    def test_get_module_from_path_file_not_found(self):
        with patch("commons.remote.hosts.utils.HOSTS_DIRS", self.hosts_test_dir):
            test_module_path = self.hosts_test_dir[0] / "test_module.py"
            test_module = get_module_from_path(test_module_path, self.hosts_test_dir[0])
            assert not test_module_path.exists()
            assert test_module is None

    @patch("importlib.util.spec_from_file_location")
    def test_get_module_from_path_any_exception(self, mock_spec):
        mock_spec.side_effect = Exception("TestException")
        with patch("commons.remote.hosts.utils.HOSTS_DIRS", self.hosts_test_dir):
            test_module_path = self.hosts_test_dir[0] / "test_module.py"
            test_module = get_module_from_path(test_module_path, self.hosts_test_dir[0])
            assert test_module is None

    @patch("commons.remote.hosts.utils.rglob")
    @patch("commons.remote.hosts.utils.get_module_from_path")
    def test_get_modules(self, mock_get_module_from_path: MagicMock, mock_rglob: MagicMock):
        mock_rglob.return_value = [Path("path1.py"), Path("path2.py"), Path("__init__.py")]

        mocked_modules = [MagicMock(), MagicMock()]
        mocked_modules[0].__name__ = "mocked_module_1"
        mocked_modules[1].__name__ = "mocked_module_2"

        mock_get_module_from_path.side_effect = mocked_modules

        modules = get_modules()
        assert isinstance(modules, list)
        assert len(modules) == 2
        assert modules == mocked_modules

    def test_get_host_subclasses(self):
        mock_module_1 = MagicMock()
        mock_module_1.TestHost1 = MockHost1

        mock_module_2 = MagicMock()
        mock_module_2.TestHost2 = MockHost2
        mock_module_2.TestHost3 = MockHost3

        mock_module_3 = MagicMock()

        with patch("commons.remote.hosts.utils.get_modules") as mock_get_modules:
            mock_get_modules.return_value = [mock_module_1, mock_module_2, mock_module_3]

            subclasses = get_host_subclasses()
            assert isinstance(subclasses, list)
            assert len(subclasses) == 3
            assert MockHost1 in subclasses
            assert MockHost2 in subclasses
            assert MockHost3 in subclasses

    def test_protocol_to_host_mocked(self):
        mock_subclasses = [MockHost1, MockHost2]

        with patch("commons.remote.hosts.utils.get_host_subclasses") as mock_get_host_subclasses:
            mock_get_host_subclasses.return_value = mock_subclasses

            protocols = protocol_to_host()
            assert isinstance(protocols, dict)
            assert len(protocols) == 2
            assert protocols["mock1"] == MockHost1
            assert protocols["mock2"] == MockHost2

    def test_protocol_to_host(self):
        protocols = protocol_to_host()
        assert isinstance(protocols, dict)
        assert protocols["ssh"].__name__ == SshHost.__name__
