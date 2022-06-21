from slicer import vtkMRMLTextNode
from vtk import VTK_ENCODING_NONE


def createBinaryNode(content: bytes = b"") -> vtkMRMLTextNode:
    node = vtkMRMLTextNode()

    # Prevent the GUI from showing the contents.
    node.SetEncoding(VTK_ENCODING_NONE)

    # Small texts get stored in the .mrml. We can't do this since .mrml is a text file
    # and cannot store binary.
    node.SetForceCreateStorageNode(True)

    node.SetText(content)
    return node


def getBinary(binaryNode: vtkMRMLTextNode) -> bytes:
    isNodeValid = binaryNode and binaryNode.IsA("vtkMRMLTextNode")
    binary = binaryNode.GetText() if isNodeValid else ""

    # The C++ binding returns `str` if the std::string is valid UTF-8, otherwise it
    # returns `bytes`.
    # We want to store binary, so we convert to `bytes` in case we get a `str`.
    if isinstance(binary, str):
        binary = binary.encode()

    return binary
