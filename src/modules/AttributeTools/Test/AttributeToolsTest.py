import slicer
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from pathlib import Path
from commons.slicer import metadata

RESOURCES = Path(__file__).parent / "Resources"
VALID_PCR = RESOURCES / "valid.pcr"
INVALID_PCR = RESOURCES / "invalid.pcr"
NO_MIN_MAX_PCR = RESOURCES / "no_min_max.pcr"
NONEXISTENT_PCR = RESOURCES / "nonexistent.pcr"


class AttributeToolsTest(LTracePluginTest):
    def pre_setup(self):
        self.volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TestVolume")

    def post_setup(self):
        self.inputSelector = self.widgets["inputSelector"]
        self.pcrPathLineEdit = self.widgets["pcrPathLineEdit"]
        self.pcrInfoLabel = self.widgets["pcrInfoLabel"]
        self.applyButton = self.widgets["applyButton"]
        self.statusLabel = self.widgets["statusLabel"]

    def tear_down(self):
        self.inputSelector.setCurrentNode(None)
        self.pcrPathLineEdit.setCurrentPath("")
        process_events()

    def test_empty_file(self):
        self.pcrPathLineEdit.setCurrentPath("")
        process_events()
        self.assertFalse(self.applyButton.enabled)
        self.assertEqual(self.pcrInfoLabel.text, "")
        self.assertEqual(self.statusLabel.text, "")
        self.assertIsNone(self.inputSelector.currentNode())
        self.assertEqual(self.pcrPathLineEdit.currentPath, "")

    def test_no_input_node_selected(self):
        self.pcrPathLineEdit.setCurrentPath(str(VALID_PCR))
        process_events()
        self.assertFalse(self.applyButton.enabled)

    def test_select_nonexistent_file(self):
        self.inputSelector.setCurrentNode(self.volume)
        process_events()
        self.pcrPathLineEdit.setCurrentPath(str(NONEXISTENT_PCR))
        process_events()
        self.assertEqual(self.pcrInfoLabel.text, "File does not exist.")
        self.assertFalse(self.applyButton.enabled)

    def test_select_invalid_file(self):
        self.inputSelector.setCurrentNode(self.volume)
        process_events()
        self.pcrPathLineEdit.setCurrentPath(str(INVALID_PCR))
        process_events()
        self.assertTrue(self.pcrInfoLabel.text.startswith("Could not parse file content:"))
        self.assertFalse(self.applyButton.enabled)

    def test_select_file_without_min_max(self):
        self.inputSelector.setCurrentNode(self.volume)
        process_events()
        self.pcrPathLineEdit.setCurrentPath(str(NO_MIN_MAX_PCR))
        process_events()
        self.assertTrue(self.pcrInfoLabel.text.startswith(f"File {NO_MIN_MAX_PCR} is missing the [VolumeData] section"))
        self.assertFalse(self.applyButton.enabled)

    def test_import_pcr(self):
        self.inputSelector.setCurrentNode(self.volume)
        process_events()

        self.pcrPathLineEdit.setCurrentPath(str(VALID_PCR))
        process_events()

        self.assertEqual(self.pcrInfoLabel.text, "Valid PCR file. Min: 0.0; Max: 1.0")
        self.assertTrue(self.applyButton.enabled)

        self.applyButton.click()
        process_events()

        self.assertEqual(self.statusLabel.text, "PCR imported successfully.")

        pcr_content = VALID_PCR.read_text()
        node_metadata = metadata.get_node_metadata(self.volume)
        self.assertIn("pcr", node_metadata)
        self.assertEqual(node_metadata["pcr"], pcr_content)
