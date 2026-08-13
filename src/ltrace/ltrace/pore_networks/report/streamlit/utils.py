import os
import streamlit as st
import pandas as pd
import numpy as np
import nrrd
import json
import vtk
from pathlib import Path

PROJECTS_FOLDER = f"{Path(__file__).parent.absolute()}/static"


def hex_to_rgb(value):
    value = value.lstrip("#")
    lv = len(value)
    return tuple(int(value[i : i + lv // 3], 16) / 255.0 for i in range(0, lv, lv // 3))


# @st.cache_data
def read_json(filename, filtering=True):
    with open(filename, "r") as f:
        d = json.load(f)

    if filtering:
        d_filtered = {}
        for key in d.keys():
            if os.path.exists(os.path.join(os.path.dirname(filename), key)):
                d_filtered.update({key: d[key]})

        return d_filtered
    else:
        return d


@st.cache_data
def read_tsv(filename):
    df = pd.read_csv(filename, sep="\t")
    return df


@st.cache_data
def read_csv(filename):
    df = pd.read_csv(filename, sep=",", decimal=".")
    return df


@st.cache_data
def read_volume(volume_file):
    volume, header = nrrd.read(volume_file)
    return volume


def read_vtk(filename):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(filename)
    reader.Update()

    target_polydata = vtk.vtkPolyData()
    target_polydata.SetPoints(reader.GetOutput().GetPoints())
    target_polydata.SetPolys(reader.GetOutput().GetPolys())
    target_polydata.SetLines(reader.GetOutput().GetLines())
    target_polydata.SetStrips(reader.GetOutput().GetStrips())

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(target_polydata)

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    return actor


def convert_vtk_to_ascii(input_file, output_file):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(input_file)
    reader.ReadAllScalarsOn()
    reader.Update()
    polyData = reader.GetOutput()
    writer = vtk.vtkPolyDataWriter()
    writer.SetFileVersion(42)
    writer.SetFileName(output_file)
    writer.SetInputData(polyData)
    writer.SetFileTypeToASCII()
    writer.Write()


def convert_vtk_to_xml(input_file, output_file):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(input_file)
    reader.ReadAllScalarsOn()
    reader.Update()
    polyData = reader.GetOutput()
    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_file)
    writer.SetInputData(polyData)
    writer.Write()
