import numpy as np
import pandas as pd
import slicer
from pathlib import Path
from vtk.util.numpy_support import vtk_to_numpy
import tempfile

from commons.slicer.data_utils import dataFrameToTableNode
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import save_project, close_project, load_project

COMMA_CSV_CONTENT = (
    "Pressão capilar(psia),Saturação de Hg (%),raio de poro (um)\n0.2,0.0,537.5\n0.49,0.0,219.4\n0.57,0.0,188.6\n"
)
SEMICOLON_CSV_CONTENT = (
    "Pressão capilar(psia);Saturação de Hg (%);raio de poro (um)\n0.2;0.0;537.5\n0.49;0.0;219.4\n0.57;0.0;188.6\n"
)


class CustomizedTablesTest(LTracePluginTest):
    def tearDown(self):
        super().tearDown()
        # Clean up the temporary directory after each test
        if hasattr(self, "_tmp_dir") and self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

    def pre_setup(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = Path(self._tmp_dir.name) / "CustomizedTablesTest" / "CustomizedTablesTest.mrml"
        slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "A")
        slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "B")

    def post_setup(self) -> None:
        tableNodeSelector = self.find_widget(name="TableNodeSelector")
        tableNodeSelector.setCurrentNode(slicer.util.getNode("B"))

    def _write_temp_csv(self, filename, content, encoding="utf-8"):
        csv_path = Path(self._tmp_dir.name) / filename
        csv_path.write_text(content, encoding=encoding)
        return csv_path

    def test_save_and_load_project(self):
        save_project(self.project_path)
        close_project()
        status, message = load_project(self.project_path)
        self.assertTrue(status, msg=message)

    def test_load_csv_with_comma_delimiter(self):
        csv_path = self._write_temp_csv("test_comma.csv", COMMA_CSV_CONTENT)

        self._module_widget.csvPathEdit.setCurrentPath(str(csv_path))
        self._module_widget.csvDelimiterCombo.setCurrentText("Comma (,)")
        self._module_widget.onLoadCSVClicked()

        table_node = slicer.util.getNode("test_comma")
        self.assertIsNotNone(table_node, "Table node 'test_comma' was not created")
        self.assertEqual(table_node.GetNumberOfColumns(), 3, "Expected 3 columns")
        self.assertEqual(table_node.GetNumberOfRows(), 3, "Expected 3 rows")

    def test_load_csv_with_semicolon_delimiter(self):
        csv_path = self._write_temp_csv("test_semicolon.csv", SEMICOLON_CSV_CONTENT)

        self._module_widget.csvPathEdit.setCurrentPath(str(csv_path))
        self._module_widget.csvDelimiterCombo.setCurrentText("Semicolon (;)")
        self._module_widget.onLoadCSVClicked()

        table_node = slicer.util.getNode("test_semicolon")
        self.assertIsNotNone(table_node, "Table node 'test_semicolon' was not created")
        self.assertEqual(table_node.GetNumberOfColumns(), 3, "Expected 3 columns")
        self.assertEqual(table_node.GetNumberOfRows(), 3, "Expected 3 rows")

    def test_load_csv_autodetect_comma(self):
        csv_path = self._write_temp_csv("test_autodetect_comma.csv", COMMA_CSV_CONTENT)

        self._module_widget.csvPathEdit.setCurrentPath(str(csv_path))
        self._module_widget.csvDelimiterCombo.setCurrentText("Auto-detect")
        self._module_widget.onLoadCSVClicked()

        table_node = slicer.util.getNode("test_autodetect_comma")
        self.assertIsNotNone(table_node, "Table node was not created for auto-detected comma CSV")
        self.assertEqual(table_node.GetNumberOfColumns(), 3, "Expected 3 columns")
        self.assertEqual(table_node.GetNumberOfRows(), 3, "Expected 3 rows")

    def test_load_csv_autodetect_semicolon(self):
        csv_path = self._write_temp_csv("test_autodetect_semicolon.csv", SEMICOLON_CSV_CONTENT)

        self._module_widget.csvPathEdit.setCurrentPath(str(csv_path))
        self._module_widget.csvDelimiterCombo.setCurrentText("Auto-detect")
        self._module_widget.onLoadCSVClicked()

        table_node = slicer.util.getNode("test_autodetect_semicolon")
        self.assertIsNotNone(table_node, "Table node was not created for auto-detected semicolon CSV")
        self.assertEqual(table_node.GetNumberOfColumns(), 3, "Expected 3 columns")
        self.assertEqual(table_node.GetNumberOfRows(), 3, "Expected 3 rows")

    def test_load_csv_utf8_encoding(self):
        csv_path = self._write_temp_csv("test_utf8.csv", COMMA_CSV_CONTENT, encoding="utf-8")

        self._module_widget.csvPathEdit.setCurrentPath(str(csv_path))
        self._module_widget.csvDelimiterCombo.setCurrentText("Comma (,)")
        self._module_widget.onLoadCSVClicked()

        table_node = slicer.util.getNode("test_utf8")
        self.assertIsNotNone(table_node, "Table node was not created from UTF-8 encoded CSV")
        self.assertEqual(table_node.GetNumberOfColumns(), 3, "Expected 3 columns from UTF-8 CSV")
        self.assertEqual(table_node.GetNumberOfRows(), 3, "Expected 3 rows from UTF-8 CSV")
        self.assertEqual(
            table_node.GetColumnName(0),
            "Pressão capilar(psia)",
            "Column header not decoded correctly from UTF-8 CSV",
        )

    def test_load_csv_iso8859_encoding(self):
        csv_path = self._write_temp_csv("test_iso8859.csv", COMMA_CSV_CONTENT, encoding="iso-8859-1")

        self._module_widget.csvPathEdit.setCurrentPath(str(csv_path))
        self._module_widget.csvDelimiterCombo.setCurrentText("Comma (,)")
        self._module_widget.onLoadCSVClicked()

        table_node = slicer.util.getNode("test_iso8859")
        self.assertIsNotNone(table_node, "Table node was not created from ISO-8859-1 encoded CSV")
        self.assertEqual(table_node.GetNumberOfColumns(), 3, "Expected 3 columns from ISO-8859-1 CSV")
        self.assertEqual(table_node.GetNumberOfRows(), 3, "Expected 3 rows from ISO-8859-1 CSV")
        self.assertEqual(
            table_node.GetColumnName(0),
            "Pressão capilar(psia)",
            "Column header not decoded correctly from ISO-8859-1 CSV",
        )

    def test_load_csv_no_path_does_not_create_table(self):
        from unittest.mock import patch

        initial_count = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLTableNode")

        self._module_widget.csvPathEdit.setCurrentPath("")
        with patch.object(slicer.util, "warningDisplay"):
            self._module_widget.onLoadCSVClicked()

        final_count = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLTableNode")
        self.assertEqual(initial_count, final_count, "No table node should be created when path is empty")

    def _make_calculator_table(self, first=(1.0, 2.0, 3.0), second=(10.0, 20.0, 30.0)):
        """Table whose columns A, B and C hold `first`, `second` and zeros."""
        df = pd.DataFrame({"A": list(first), "B": list(second), "C": [0.0] * len(first)})
        return dataFrameToTableNode(df)

    def _result_column(self, table_node, column_index=2):
        """A column read straight from the node, so assertions do not go through the logic.

        Reads the VTK array rather than GetCellText, which would round to six significant
        digits and hide any precision the calculator loses.
        """
        return list(vtk_to_numpy(table_node.GetTable().GetColumn(column_index)))

    def test_calculate_simple_formula(self):
        table_node = self._make_calculator_table()

        self._module_widget.logic.calculate(table_node, "A + B", "C")

        np.testing.assert_allclose(self._result_column(table_node), [11.0, 22.0, 33.0])

    def test_calculate_preserves_full_double_precision(self):
        # Regression test: columns used to be read through GetCellText, which formats doubles at
        # six significant digits, so even copying a column onto another altered every value by
        # about 1e-6 relative (1234567.89 came back as 1234570.0).
        values = (1234567.89, 0.1234567890123)
        table_node = self._make_calculator_table(first=values, second=(0.0, 0.0))

        self._module_widget.logic.calculate(table_node, "A", "C")

        self.assertEqual(self._result_column(table_node), list(values))

    def test_calculate_into_non_numeric_column(self):
        # The output column is converted to double before results are written, so a text column
        # is a valid target even though it could not be read as numbers.
        table_node = dataFrameToTableNode(pd.DataFrame({"A": [1.5, 2.5], "B": [10.0, 20.0], "C": ["x", "y"]}))

        self._module_widget.logic.calculate(table_node, "A + B", "C")

        self.assertEqual(self._result_column(table_node), [11.5, 22.5])

    def test_calculate_does_not_break_on_repeated_calls(self):
        # Regression test: the old code injected columns with exec(...locals()) and let numexpr
        # find them by reading the caller's frame. Since numexpr 2.8.5 evaluate() reads that frame
        # twice (validate, then re_evaluate) and the first read clears it, so every call raised
        # KeyError - the first one included, not just repeated ones. Repeats the same formula
        # string against different data, which also covers numexpr's compiled expression cache.
        logic = self._module_widget.logic

        table_node_1 = self._make_calculator_table(first=(1.0, 2.0), second=(10.0, 20.0))
        logic.calculate(table_node_1, "A + B", "C")
        np.testing.assert_allclose(self._result_column(table_node_1), [11.0, 22.0])

        table_node_2 = self._make_calculator_table(first=(3.0, 4.0), second=(30.0, 40.0))
        logic.calculate(table_node_2, "A + B", "C")
        np.testing.assert_allclose(self._result_column(table_node_2), [33.0, 44.0])

    def test_calculate_with_double_letter_columns(self):
        # Regression test: columns beyond Z must be addressable as AA, AB, ...
        # and must not be confused with single-letter columns (e.g. "A" matching
        # inside "AA") when parsing the formula.
        num_columns = 30  # last two columns become AA (index 26) and AB (index 27)
        column_names = [chr(ord("A") + i) if i < 26 else "A" + chr(ord("A") + i - 26) for i in range(num_columns)]
        df = pd.DataFrame({name: [float(i)] for i, name in enumerate(column_names)})
        table_node = dataFrameToTableNode(df)

        self.assertEqual(table_node.GetColumnName(26), "AA")
        self.assertEqual(table_node.GetColumnName(27), "AB")

        self._module_widget.logic.calculate(table_node, "AA + AB", "A")

        self.assertEqual(self._result_column(table_node, column_index=0), [26.0 + 27.0])

    def test_calculate_with_function_and_constant(self):
        table_node = self._make_calculator_table()

        self._module_widget.logic.calculate(table_node, "sqrt(B) + 1", "C")

        expected = [10.0**0.5 + 1, 20.0**0.5 + 1, 30.0**0.5 + 1]
        np.testing.assert_allclose(self._result_column(table_node), expected)

    def test_calculate_scalar_formula_fills_column(self):
        table_node = self._make_calculator_table()

        self._module_widget.logic.calculate(table_node, "2", "C")

        np.testing.assert_allclose(self._result_column(table_node), [2.0, 2.0, 2.0])

    def test_calculate_rejects_invalid_formula(self):
        from CustomizedTables import CustomizedTableError

        table_node = self._make_calculator_table()

        with self.assertRaises(CustomizedTableError):
            self._module_widget.logic.calculate(table_node, "A +", "C")

    def test_calculate_rejects_column_missing_from_table(self):
        from CustomizedTables import CustomizedTableError

        table_node = self._make_calculator_table()

        # Referenced by the formula
        with self.assertRaises(CustomizedTableError):
            self._module_widget.logic.calculate(table_node, "A + D", "C")

        # Named as the output, both single and multi letter
        for outputColumn in ("Z", "ZZZ"):
            with self.assertRaises(CustomizedTableError):
                self._module_widget.logic.calculate(table_node, "A + B", outputColumn)

    def test_calculate_rejects_non_numeric_cell(self):
        from CustomizedTables import CustomizedTableError

        # A string column, since text does not survive being written into a double column
        table_node = dataFrameToTableNode(
            pd.DataFrame({"A": ["1", "not a number", "3"], "B": ["10", "20", "30"], "C": ["0", "0", "0"]})
        )

        with self.assertRaises(CustomizedTableError):
            self._module_widget.logic.calculate(table_node, "A + B", "C")
