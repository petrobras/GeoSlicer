from commons.slicer.lazy.protocols.base import BaseProtocol
from commons.slicer.lazy.protocols.local import LocalProtocol
from commons.slicer.lazy.protocols.factory import ProtocolFactory
from pathlib import Path
from unittest.mock import patch, MagicMock

import importlib
import pytest
import shutil
import tempfile


class MockBaseProtocol1(BaseProtocol):
    PROTOCOL = "mock1"

    def load():
        pass


class MockBaseProtocol2(MockBaseProtocol1):
    PROTOCOL = "mock2"


class MockBaseProtocol3(MockBaseProtocol1):
    PROTOCOL = "mock3"


class TestProtocolFactory:
    def setup_method(self, method) -> None:
        self.test_dir = Path(tempfile.mkdtemp())

    def teardown_method(self, method) -> None:
        shutil.rmtree(self.test_dir)

    def test_get_protocol_subclasses_from_module(self):
        module = MagicMock()
        module.MockBaseProtocol1 = MockBaseProtocol1
        module.MockBaseProtocol2 = MockBaseProtocol2

        subclasses = ProtocolFactory._get_protocol_subclasses_from_module(module)
        assert isinstance(subclasses, list)
        assert len(subclasses) == 2
        assert MockBaseProtocol1 in subclasses
        assert MockBaseProtocol2 in subclasses

    def test_get_module_from_path(self):
        with patch("commons.slicer.lazy.protocols.factory.ProtocolFactory.PROTOCOLS_DIR", self.test_dir):
            test_module_path = self.test_dir / "test_module.py"
            with test_module_path.open("w") as f:
                f.write(
                    "from commons.slicer.lazy.protocols.base import BaseProtocol\n"
                    "class TestBaseProtocol(BaseProtocol):\n"
                    "    PROTOCOL = 'test_protocol'\n"
                )

            test_module = ProtocolFactory._get_module_from_path(test_module_path)
            assert test_module is not None
            assert hasattr(test_module, "TestBaseProtocol")
            assert issubclass(test_module.TestBaseProtocol, BaseProtocol)

    def test_get_module_from_path_file_not_found(self):
        with patch("commons.slicer.lazy.protocols.factory.ProtocolFactory.PROTOCOLS_DIR", self.test_dir):
            test_module_path = self.test_dir / "test_module.py"
            test_module = ProtocolFactory._get_module_from_path(test_module_path)
            assert not test_module_path.exists()
            assert test_module is None

    @patch.object(importlib.util, "spec_from_file_location", lambda x: Exception("TestException"))
    def test_get_module_from_path_any_exception(self):
        test_module_path = self.test_dir / "test_module.py"
        test_module = ProtocolFactory._get_module_from_path(test_module_path)
        assert not test_module_path.exists()
        assert test_module is None

    @patch.object(Path, "rglob", lambda x, y: ["path1", "path2"])
    @patch("commons.slicer.lazy.protocols.factory.ProtocolFactory._get_module_from_path")
    def test_get_modules(self, mock_get_module_from_path: MagicMock):
        mocked_modules = [MagicMock(), MagicMock(), None]
        mocked_modules[0].__name__ = "mocked_module_1"
        mocked_modules[1].__name__ = "mocked_module_2"

        mock_get_module_from_path.side_effect = mocked_modules

        modules = ProtocolFactory._get_modules()
        assert isinstance(modules, list)
        assert len(modules) == 2
        assert modules == mocked_modules[:-1]

    def test_get_protocol_subclasses(self):
        mock_module_1 = MagicMock()
        mock_module_1.TestBaseProtocol1 = MockBaseProtocol1

        mock_module_2 = MagicMock()
        mock_module_2.TestBaseProtocol2 = MockBaseProtocol2
        mock_module_2.TestBaseProtocol3 = MockBaseProtocol3

        mock_module_3 = MagicMock()

        with patch("commons.slicer.lazy.protocols.factory.ProtocolFactory._get_modules") as mock_get_modules:
            mock_get_modules.return_value = [mock_module_1, mock_module_2, mock_module_3]

            subclasses = ProtocolFactory._get_protocol_subclasses()
            assert isinstance(subclasses, list)
            assert len(subclasses) == 3
            assert MockBaseProtocol1 in subclasses
            assert MockBaseProtocol2 in subclasses
            assert MockBaseProtocol3 in subclasses

    @pytest.mark.parametrize(
        "input, output",
        [
            pytest.param("file", "file", id="simple"),
            pytest.param(" file ", "file", id="whitespace"),
            pytest.param("file://", "file", id="special_characters"),
        ],
    )
    def test_parse_protocol(self, input, output):
        assert ProtocolFactory._parse_protocol_string(input) == output

    @pytest.mark.parametrize(
        "url, protocolCls, shouldThrowException",
        [
            pytest.param("file", LocalProtocol, True, id="file_no_pattern"),
            pytest.param("file://home/test", LocalProtocol, False, id="file_protocol_simple"),
            pytest.param("file://", LocalProtocol, False, id="file_protocol_no_path"),
            pytest.param("\\#@file://", LocalProtocol, False, id="file_protocol_special_characters"),
            pytest.param("bia", None, True, id="invalid_protocol"),
            pytest.param("", None, True, id="empty_string"),
            pytest.param(" ", None, True, id="whitespace_string"),
        ],
    )
    def test_build(self, url, protocolCls, shouldThrowException):

        if shouldThrowException:
            with pytest.raises(ValueError):
                proto = ProtocolFactory.build(url=url)
                assert proto.__class__.__name__ == protocolCls.__name__, (
                    f"Expected '{protocolCls.__name__}', Current '{proto.__class__.__name__}'"
                )

            return

        proto = ProtocolFactory.build(url=url)
        assert proto.__class__.__name__ == protocolCls.__name__, (
            f"Expected '{protocolCls.__name__}', Current '{proto.__class__.__name__}'"
        )

    @pytest.mark.parametrize(
        "url, protocolCls, shouldThrowException",
        [
            pytest.param("mock1", MockBaseProtocol1, True, id="mock1_protocol_no_protocol"),
            pytest.param("mock1://test.com", MockBaseProtocol1, False, id="mock1_protocol_no_path"),
            pytest.param("mock1://", MockBaseProtocol1, False, id="mock1_protocol_no_path"),
            pytest.param("mock", None, True, id="wrong_protocol"),
        ],
    )
    def test_build_mocked_protocols(self, url, protocolCls, shouldThrowException):
        mock_subclasses = [MockBaseProtocol1, MockBaseProtocol2]

        with patch(
            "commons.slicer.lazy.protocols.factory.ProtocolFactory._get_protocol_subclasses"
        ) as mock_get_protocol_subclasses:
            mock_get_protocol_subclasses.return_value = mock_subclasses
            if shouldThrowException:
                with pytest.raises(ValueError):
                    proto = ProtocolFactory.build(url=url)
                    assert proto.__class__.__name__ == protocolCls.__name__, (
                        f"Expected '{protocolCls.__name__}', Current '{proto.__class__.__name__}'"
                    )

                return

            proto = ProtocolFactory.build(url=url)
            assert proto.__class__.__name__ == protocolCls.__name__, (
                f"Expected '{protocolCls.__name__}', Current '{proto.__class__.__name__}'"
            )
