"""Module to store every node attribute definition with well defined values.

   How to implement:

   - Derive a class from NodeAttributeValue:
       class NewNodeAttribute(NodeAttributeValue):
           Option1 = "option_1"
           Option2 = "option_2"
           
       The class name (retrieved by the method 'name()') is used as the node's attribute key.
       The class attributes are the 'options' available for the node's attribute. The attribute 'key' is used to retrieve the value, which is used as the node's attribute value.

   How to use:

    - Getting an attribute:
      node.GetAttribute(NewNodeAttribute.name())
      # Expecting a node attribute with the string "NewNodeAttribute" as key.
      
     
    - Setting an attribute:
      node.SetAttribute(ATTRIBUTE_EXAMPLE.name(), ATTRIBUTE_EXAMPLE.Option1.value)
      # Expecting to define the node's attribute with the string "NewNodeAttribute" as the key, and a string "option_1" as its value.
     
    - Comparison:
      if node.GetAttribute(ATTRIBUTE_EXAMPLE.name()) == ATTRIBUTE_EXAMPLE.Option1.value:
          ....

"""

import enum
from collections import namedtuple


@enum.unique
class NodeAttributeValue(enum.Enum):
    """
    Node attribute value base class.
    """

    @classmethod
    def name(cls) -> str:
        return cls.__name__


class NodeEnvironment(NodeAttributeValue):
    """
    Environment options for 'environment' node attribute
    """

    EMPTY_ENV = "EmptyEnv"
    IMAGE_LOG = "ImageLogEnv"
    CORE = "CoreEnv"
    MICRO_CT = "MicroCTEnv"
    THIN_SECTION = "ThinSectionEnv"
    CHARTS = "Charts"
    LABEL_MAP_EDITOR = "LabelMapEditor"
    MULTISCALE = "MultiscaleEnv"


class DataOrigin(NodeAttributeValue):
    """
    Define which module/plugin the data was created from
    """

    IMAGE_LOG = "ImageLogEnv"
    CORE = "CoreEnv"
    MICRO_CT = "MicroCTEnv"
    THIN_SECTION = "ThinSectionEnv"
    CHARTS = "Charts"
    LABEL_MAP_EDITOR = "LabelMapEditor"


class NodeTemporarity(NodeAttributeValue):
    """Define if the node is temporary."""

    TRUE = "true"
    FALSE = "false"


class TableDataOrientation(NodeAttributeValue):
    """Define which orientation the data from a table node is."""

    ROW = "TableDataOrientation.ROW"  # Changed to maintain compatibility with older project files
    COLUMN = "TableDataOrientation.COLUMN"  # Changed to maintain compatibility with older project files


class TableType(NodeAttributeValue):
    """Define which table type the data from a table node is."""

    IMAGE_LOG = "image_log"
    HISTOGRAM_IN_DEPTH = "histogram_in_depth"
    BASIC_PETROPHYSICS = "basic_petrophysics"
    PNM_INPUT_PARAMETERS = "pnm_simulation_input_parameters"
    POROSITY_PER_REALIZATION = "porosity_per_realization"
    MEAN_IN_DEPTH = "mean_in_depth"

    @classmethod
    def name(cls) -> str:
        """Define the node's attribute name. Overided from NodeAttributeValue to maintain compatibility with older project files.

        Returns:
            str: the node's attribute name.
        """
        return "table_type"


class TableDataTypeAttribute(NodeAttributeValue):
    """Define which data type the data from a table node is."""

    IMAGE_2D = "image_2D"


class ColorMapSelectable(NodeAttributeValue):
    """Attribute to filter which color map nodes are going to available in the application"""

    TRUE = "ColorMapSelectable.TRUE"  # Changed to maintain compatibility with older project files
    FALSE = "ColorMapSelectable.FALSE"  # Changed to maintain compatibility with older project files


class ImageLogDataSelectable(NodeAttributeValue):
    TRUE = "ImageLogDataSelectable.TRUE"  # Changed to maintain compatibility with older project files
    FALSE = "ImageLogDataSelectable.FALSE"  # Changed to maintain compatibility with older project files


class LosslessAttribute(NodeAttributeValue):
    TRUE = "True"
    FALSE = "False"

    @classmethod
    def name(cls) -> str:
        """Define the node's attribute name. Overided from NodeAttributeValue to maintain compatibility with older project files.

        Returns:
            str: the node's attribute name.
        """
        return "Lossless"


Tag = namedtuple("Tag", ["value"])


class PlotScaleXAxisAttribute(NodeAttributeValue):
    LINEAR_SCALE = "linearscale"
    LOG_SCALE = "logscale"
