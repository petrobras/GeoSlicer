import os
import vtk


# Function to convert a binary VTK file to ASCII
def convert_vtk_to_ascii(input_file, output_file):
    # Read the binary VTK file
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(input_file)
    reader.ReadAllScalarsOn()
    reader.Update()

    # Get the polydata from the reader
    polyData = reader.GetOutput()

    # Write the polydata to an ASCII VTK file
    writer = vtk.vtkPolyDataWriter()
    writer.SetFileVersion(42)
    writer.SetFileName(output_file)
    writer.SetInputData(polyData)
    writer.SetFileTypeToASCII()
    writer.Write()


# Folder containing the binary VTK files
folder_path = "./"

# List all files in the folder
files = os.listdir(folder_path)

# Process each file in the folder
for file in files:
    if file.endswith(".vtk"):
        input_file = os.path.join(folder_path, file)
        output_file = os.path.join(folder_path, f"{os.path.splitext(file)[0]}_ascii.vtk")
        convert_vtk_to_ascii(input_file, output_file)
        print(f"Converted {input_file} to {output_file}")
        # os.rename(input_file, f"{input_file}.old")
        # os.rename(output_file, input_file)
        # print(f"Replacing {output_file}")
