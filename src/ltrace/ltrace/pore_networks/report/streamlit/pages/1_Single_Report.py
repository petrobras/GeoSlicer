import streamlit as st
import pandas as pd
import numpy as np
import os
import warnings
import re

import plotly.express as px
import plotly.graph_objects as go
import plotly.colors as pc

from matplotlib.pyplot import get_cmap
import matplotlib.pyplot as plt

from utils import (
    read_tsv,
    read_json,
    read_volume,
    read_vtk,
    hex_to_rgb,
    PROJECTS_FOLDER,
)


def water_color_gradient(normalized_value):
    r = 0  # 0
    g = int(100 + 140 * normalized_value)  # 100 --> 240
    b = int(200 * (1 - normalized_value))  # 200 --> 0
    return (r, g, b)


def oil_color_gradient(normalized_value):
    r = int(200 + 55 * normalized_value)  # 200 --> 255
    g = int(0 + 110 * normalized_value)  # 0 --> 110
    b = int(10 + 190 * (1 - normalized_value))  # 200 --> 10
    return (r, g, b)


import vtk
import json
from stitkvtkviewer import stitkvtkviewer
from pathlib import Path

st.set_page_config(
    page_title="PNM Report",
    # page_icon="📊",
    # layout="wide",
)

st.write("# 📈 Single Report")

if os.path.exists(f"{PROJECTS_FOLDER}/projects.json"):
    st.markdown(
        """
        Please select a tab to see results from the report selected in the sidebar.
        """
    )

    json_dict = read_json(f"{PROJECTS_FOLDER}/projects.json")

    st.sidebar.selectbox(
        "Select a project folder:",
        json_dict.keys(),
        key="project_selectbox",
    )

    name = st.session_state.project_selectbox
else:
    json_dict = None
    name = None
    st.write(
        "JSON file not found. Please generate it using the Geoslicer tool or import an existing one via the Projects Manager."
    )
    st.stop()


static_folder = Path(__file__).parent.parent / "static"

is_multiscale = "pore_polydata_1" in json_dict[name]

tabs = st.tabs(["Volume", "Network", "Kabs", "Krel", "Production", "MICP"])

with tabs[0]:
    st.write("## 3D Volume")

    volume = json_dict[name]["volume"]

    path = f"{name}/{volume}"
    if not os.path.exists(static_folder / path):
        st.text(f"3D volume not found in {static_folder / path}.")
    elif os.stat(static_folder / path).st_size > 200 * 1024 * 1024:
        st.text("File size of volume exceed maximum server capability (200 Mb).")
    else:
        stitkvtkviewer(path, key="volume")


with tabs[1]:
    st.write("## 3D Representation of the network")

    sample_dict = json_dict[name]

    polydata_list = []
    polydata_colors = []

    pores_dict = [key for key in sample_dict.keys() if key.startswith("pore_polydata")]
    throats_dict = [key for key in sample_dict.keys() if key.startswith("throat_polydata")]

    pores_color = {"0": (0.1, 0.1, 0.9), "1": (0.9, 0.1, 0.9)}
    throats_color = {"0": (0.1, 0.9, 0.1), "1": (0.9, 0.8, 0.1), "2": (0.9, 0.1, 0.1)}

    for key in pores_dict:
        polydata_name = sample_dict[key]
        path = f"{name}/{polydata_name}"
        if os.path.exists(static_folder / path):
            polydata_list.append(path)
            polydata_colors.append(pores_color[key[-1]])

    for key in throats_dict:
        polydata_name = sample_dict[key]
        path = f"{name}/{polydata_name}"
        if os.path.exists(static_folder / path):
            polydata_list.append(path)
            polydata_colors.append(throats_color[key[-1]])

    if polydata_list:
        stitkvtkviewer(polydata_list, geometries_colors=polydata_colors, key="network")
    else:
        st.text("3D Network not found.")

    st.write("## Pores table statistics")
    col1, col2 = st.columns(2, gap="small")

    if "flow_props_pore_network" in json_dict[name]:
        pore_table_name = json_dict[name]["flow_props_pore_network"]
    else:
        pore_table_name = json_dict[name]["pore_table"]
    path = f"{PROJECTS_FOLDER}/{name}/{pore_table_name}"
    if os.path.exists(path):
        pore_table = read_tsv(path)
        pore_table_description = pore_table.describe()
        for key in ["pore.manual_valvatne_conductivity", "pore.sub_conductivity"]:
            if key in pore_table_description:
                pore_table_description[key] = pore_table_description[key].apply(lambda x: f"{x:e}")
        col1.dataframe(pore_table_description.T)

        column = col2.selectbox("Select a column entry from the table:", pore_table.columns)
        if is_multiscale:
            color = "pore.phase_name"
            pore_table.loc[pore_table["pore.phase"] == 1, color] = "resolv"
            pore_table.loc[pore_table["pore.phase"] == 2, color] = "subres"
        else:
            color = None
        fig = px.histogram(
            pore_table,
            x=column,
            color=color,
        )
        fig.update_layout(margin=dict(l=20, r=20, t=0, b=0), height=300)
        col2.plotly_chart(fig, theme="streamlit", use_container_width=True)
    else:
        st.text("Pores table not found.")

    st.write("## Throats table statistics")
    col1, col2 = st.columns(2, gap="small")

    if "flow_props_throat_network" in json_dict[name]:
        throat_table_name = json_dict[name]["flow_props_throat_network"]
    else:
        throat_table_name = json_dict[name]["throat_table"]
    path = f"{PROJECTS_FOLDER}/{name}/{throat_table_name}"
    if os.path.exists(path):
        throat_table = read_tsv(path)
        throat_table_description = throat_table.describe()
        for key in [
            "throat.cross_sectional_area",
            "throat.volume",
            "throat.manual_valvatne_conductivity",
            "throat.manual_valvatne_conductance",
            "throat.manual_valvatne_conductance_former",
            "throat.sub_conductivity",
        ]:
            if key in throat_table_description:
                throat_table_description[key] = throat_table_description[key].apply(lambda x: f"{x:e}")
        col1.dataframe(throat_table_description.T)

        column = col2.selectbox("Select a column entry from the table:", throat_table.columns)
        if is_multiscale:
            color = "throat.phases"
            throat_table[color] = throat_table["throat.phases_0"] + throat_table["throat.phases_1"]
            throat_table.loc[throat_table["throat.phases"] == 2, color] = "resolv/resolv"
            throat_table.loc[throat_table["throat.phases"] == 3, color] = "resolv/subres"
            throat_table.loc[throat_table["throat.phases"] == 4, color] = "subres/subres"
        else:
            color = None
        fig = px.histogram(throat_table, x=column, color=color)
        fig.update_layout(margin=dict(l=20, r=20, t=0, b=0), height=300)
        col2.plotly_chart(fig, theme="streamlit", use_container_width=True)
    else:
        st.text("Throats table not found.")

    if is_multiscale:
        st.write("## Subscale model")

        dict_name = json_dict[name].get("subres_model")
        path = f"{PROJECTS_FOLDER}/{name}/{dict_name}" if dict_name else None
        if path and os.path.exists(path):
            subres = read_json(path, filtering=False)
            subres_name = list(subres)[0]
            subres_params = subres[subres_name]
            st.write(f"Model used: '{subres_name}'")
            if subres_name == "Pressure Curve":
                subres_params.pop("throat radii")

                subres_params_df = pd.DataFrame(subres_params)
                subres_params_df.rename(
                    columns={
                        "capillary pressure": "Pressure (Pa)",
                        "dsn": "Volume Fraction",
                    },
                    inplace=True,
                )

                col1, col2 = st.columns(2, gap="small")

                col1.dataframe(subres_params_df)

                fig = px.line(subres_params_df, x="Pressure (Pa)", y="Volume Fraction", height=400, markers=True)
                fig.update_traces(marker_size=10)
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
                col2.plotly_chart(fig, theme="streamlit", use_container_width=True)
            elif subres_name == "Throat Radius Curve":
                subres_params.pop("capillary pressure")

                subres_params_df = pd.DataFrame(subres_params)
                subres_params_df.rename(
                    columns={
                        "throat radii": "Radii (mm)",
                        "dsn": "Volume Fraction",
                    },
                    inplace=True,
                )

                col1, col2 = st.columns(2, gap="small")

                col1.dataframe(subres_params_df)

                fig = px.line(subres_params_df, x="Radii (mm)", y="Volume Fraction", height=400, markers=True)
                fig.update_traces(marker_size=10)
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
                col2.plotly_chart(fig, theme="streamlit", use_container_width=True)
            else:
                st.write(subres_params)
        else:
            st.write("Subresolution model not found.")

with tabs[2]:
    st.write("## Single angle")

    col1, col2 = st.columns(2, gap="small")

    col1.write("### Flow rate")
    flow_rate_name = json_dict[name]["flow_rate"]
    path = f"{PROJECTS_FOLDER}/{name}/{flow_rate_name}"
    if os.path.exists(path):
        flow_rate_df = read_tsv(path)
        # flow_rate_df.index = list(flow_rate_df.columns)
        col1.dataframe(flow_rate_df)
    else:
        st.text("Flow rate table not found.")

    col2.write("### Permeability")
    permeability_name = json_dict[name]["perm_node"]
    path = f"{PROJECTS_FOLDER}/{name}/{permeability_name}"
    if os.path.exists(path):
        permeability_df = read_tsv(path)
        # permeability_df.index = list(permeability_df.columns)
        col2.dataframe(permeability_df)
    else:
        st.text("Permeability table not found.")

    st.write("## Multi angle")

    multiangle_polydata = []
    multiangle_colors = []
    multiangle_model_name = json_dict[name]["multiangle_model"]
    path = f"{name}/{multiangle_model_name}"
    if os.path.exists(static_folder / path):
        path = re.sub(".vtk", ".vtp", path)
        multiangle_polydata.append(path)
        multiangle_colors.append("color_range")

        multiangle_model_name = json_dict[name]["multiangle_arrow_model"]
        path = f"{name}/{multiangle_model_name}"
        multiangle_polydata.append(path)
        multiangle_colors.append([0.0, 0.0, 1.0])

        multiangle_model_name = json_dict[name]["multiangle_plane_model"]
        path = f"{name}/{multiangle_model_name}"
        multiangle_polydata.append(path)
        multiangle_colors.append([0.5, 0.5, 0.5, 0.5])

        multiangle_model_name = json_dict[name]["multiangle_sphere_model"]
        path = f"{name}/{multiangle_model_name}"
        multiangle_polydata.append(path)
        multiangle_colors.append([0.5, 0.5, 0.5])

        stitkvtkviewer(multiangle_polydata, geometries_colors=multiangle_colors, key="multiangle")
    else:
        st.text("Multiangle models not found.")

    st.write("### Statistics")
    statistics_name = json_dict[name]["multiangle_statistics"]
    path = f"{PROJECTS_FOLDER}/{name}/{statistics_name}"
    if os.path.exists(path):
        statistics_df = read_tsv(path).T
        statistics_df.columns = [""]
        st.dataframe(statistics_df)
    else:
        st.text("Statistics for multiangle model not found.")


with tabs[3]:
    st.write("## Krel Results")

    if "sensibility" in json_dict[name]:
        sensibility_name = json_dict[name]["sensibility"]
        path = f"{PROJECTS_FOLDER}/{name}/{sensibility_name}"

        if path and os.path.exists(path):
            sensibility = read_tsv(path)

            st.write("### Sensibility analysis")

            analysis_type = st.selectbox("Select the type of analysis:", ["Curves plot", "Self-correlation"])

            if analysis_type == "Curves plot":
                st.write("#### Curves plot")

                angle_columns = [column for column in sensibility if ("_min" in column) or ("_max" in column)]
                variable_keys = [
                    key
                    for key, value in sensibility.items()
                    if value.nunique() > 1 and key.startswith("input") and key not in angle_columns
                ]
                color_scale = st.selectbox("Curves color scale", ["None"] + variable_keys)

                col1, col2, col3 = st.columns(3, gap="small")
                Ko = []
                Kw = []
                Ko.append(col1.checkbox("Drainage Ko"))
                Kw.append(col1.checkbox("Drainage Kw"))
                Ko.append(col2.checkbox("Imbibition Ko", value=True))
                Kw.append(col2.checkbox("Imbibition Kw", value=True))
                Ko.append(col3.checkbox("Second Drainage Ko"))
                Kw.append(col3.checkbox("Second Drainage Kw"))

                kmax = 0
                kmin = 180

                figs = []
                kro_curves_data = []
                krw_curves_data = []
                for c in range(0, 3):
                    sensibility_cycle_name = json_dict[name][f"sensibility_cycle{c}"]
                    sensibility_cycle = read_tsv(f"{PROJECTS_FOLDER}/{name}/{sensibility_cycle_name}")

                    curves = []
                    colors = []
                    if Ko[c]:
                        curves.extend([f"Kro_{i}" for i in range(len(sensibility))])
                        if color_scale == "None":
                            colors.extend(["rgb(178, 53, 53)" for i in range(len(sensibility))])
                        else:
                            maxi = max(sensibility[color_scale])
                            mini = min(sensibility[color_scale])
                            if maxi != mini:
                                curves_colors = [
                                    (sensibility[color_scale][i] - mini) / (maxi - mini) / 2
                                    for i in range(len(sensibility))
                                ]
                                colors.extend(
                                    ["rgb({},{},{})".format(*oil_color_gradient(val)) for val in curves_colors]
                                )
                            else:
                                colors.extend(
                                    [
                                        "rgb({},{},{})".format(*oil_color_gradient(0.5))
                                        for val in range(len(sensibility[color_scale]))
                                    ]
                                )
                            if maxi > kmax:
                                kmax = maxi
                            if mini < kmin:
                                kmin = mini
                    if Kw[c]:
                        curves.extend([f"Krw_{i}" for i in range(len(sensibility))])
                        if color_scale == "None":
                            colors.extend(["rgb(69, 54, 178)" for i in range(len(sensibility))])
                        else:
                            maxi = max(sensibility[color_scale])
                            mini = min(sensibility[color_scale])
                            if maxi != mini:
                                curves_colors = [
                                    (sensibility[color_scale][i] - mini) / (maxi - mini) / 2
                                    for i in range(len(sensibility))
                                ]
                                colors.extend(
                                    ["rgb({},{},{})".format(*water_color_gradient(val)) for val in curves_colors]
                                )
                            else:
                                colors.extend(
                                    [
                                        "rgb({},{},{})".format(*water_color_gradient(0.5))
                                        for val in range(len(sensibility[color_scale]))
                                    ]
                                )
                            if maxi > kmax:
                                kmax = maxi
                            if mini < kmin:
                                kmin = mini

                    trace_objs = []
                    for curve, color in zip(curves, colors):
                        if curve in sensibility_cycle:
                            trace_objs.append(
                                go.Scatter(
                                    x=sensibility_cycle["Sw"],
                                    y=sensibility_cycle[curve],
                                    mode="lines",
                                    name=curve,
                                    opacity=0.4,
                                    line=dict(color=color),
                                    showlegend=False,
                                )
                            )
                            if curve.startswith("Kro_"):
                                kro_curves_data.append(sensibility_cycle[curve])
                            elif curve.startswith("Krw_"):
                                krw_curves_data.append(sensibility_cycle[curve])

                    fig = go.Figure(data=trace_objs)
                    figs.append(fig)

                data = figs[0].data + figs[1].data + figs[2].data

                if kro_curves_data:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        mean_curve = np.nanmean(kro_curves_data, axis=0)
                    mean_trace = go.Scatter(
                        x=sensibility_cycle["Sw"],
                        y=mean_curve,
                        mode="lines",
                        name="Kro Mean Curve",
                        line=dict(color="rgb(255,0,0)"),
                    )
                    kro_mean_fig = go.Figure(data=mean_trace)
                    data += kro_mean_fig.data

                if krw_curves_data:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        mean_curve = np.nanmean(krw_curves_data, axis=0)
                    mean_trace = go.Scatter(
                        x=sensibility_cycle["Sw"],
                        y=mean_curve,
                        mode="lines",
                        name="Krw Mean Curve",
                        line=dict(color="rgb(0,0,255)"),
                    )
                    krw_mean_fig = go.Figure(data=mean_trace)
                    data += krw_mean_fig.data

                if color_scale != "None":
                    colorbar_kw = go.Scatter(
                        x=[None],
                        y=[None],
                        mode="markers",
                        showlegend=False,
                        marker=dict(
                            colorscale=[
                                [0.0, "rgb({},{},{})".format(*water_color_gradient(0))],
                                [1.0, "rgb({},{},{})".format(*water_color_gradient(0.5))],
                            ],
                            cmin=0,
                            cmax=1,
                            colorbar=dict(
                                tickvals=[],
                                ticktext=[],
                                orientation="h",
                                y=-0.35,
                                xanchor="center",
                                len=1.0,
                            ),
                        ),
                    )

                    colorbar_ko = go.Scatter(
                        x=[None],
                        y=[None],
                        mode="markers",
                        showlegend=False,
                        marker=dict(
                            colorscale=[
                                [0.0, "rgb({},{},{})".format(*oil_color_gradient(0))],
                                [1.0, "rgb({},{},{})".format(*oil_color_gradient(0.5))],
                            ],
                            cmin=0,
                            cmax=1,
                            colorbar=dict(
                                tickvals=[0.0, 0.25, 0.5, 0.75, 1.0],
                                ticktext=[
                                    kmin,
                                    (kmin + kmax) / 4.0,
                                    (kmin + kmax) / 2.0,
                                    3 * (kmin + kmax) / 4.0,
                                    kmax,
                                ],
                                orientation="h",
                                y=-0.5,
                                xanchor="center",
                                len=1.0,
                            ),
                        ),
                    )

                    data += (
                        colorbar_ko,
                        colorbar_kw,
                    )

                fig = go.Figure(data=data)

                fig.update_traces(marker_size=10)
                fig.update_layout(
                    margin=dict(l=20, r=20, t=0, b=0),
                    height=300 if color_scale == "None" else 500,
                    xaxis_title="Sw",
                    yaxis_title="Krel",
                )
                st.plotly_chart(fig, theme="streamlit", use_container_width=True)

            elif analysis_type == "Self-correlation":
                st.write("#### Self-correlation of the results")

                filter_col = [
                    col
                    for col in sensibility
                    if col.startswith("result-") and col != "result-no" and col != "result-nw"
                ]
                matrix = sensibility[filter_col].corr(method="pearson")

                fig = px.imshow(matrix, text_auto=True)
                fig.update_layout(margin=dict(l=20, r=20, t=0, b=0))
                st.plotly_chart(fig, theme="streamlit", use_container_width=True)
        else:
            st.text("Sensibility results not found.")
    else:
        st.text("Sensibility results not found.")

    st.write("### Sensibility parameters")

    if "sensibility_parameters" in json_dict[name]:
        parameters_name = json_dict[name]["sensibility_parameters"]
        path = f"{PROJECTS_FOLDER}/{name}/{parameters_name}"
        if path and os.path.exists(path):
            parameters = read_tsv(path)
            st.write(parameters)
        else:
            st.write("Parameters node not found")
    else:
        st.write("Parameters node not found")

with tabs[4]:
    st.write("## Production Results")

    if "production" in json_dict[name]:
        production_name = json_dict[name]["production"]
        path = f"{PROJECTS_FOLDER}/{name}/{production_name}"
        if path and os.path.exists(path):
            production = read_tsv(path)

        color_dict = {
            "pessimistic_NpD": "rgb(255, 0, 0)",
            "realistic_NpD": "rgb(255, 255, 0)",
            "optimistic_NpD": "rgb(0, 255, 0)",
        }

        trace_objs = []
        for curve in production.keys()[1:]:
            color = color_dict.get(curve, "rgb(127, 127, 127)")
            in_color_dict = curve in color_dict
            trace_objs.append(
                go.Scatter(
                    x=production["tD"],
                    y=production[curve],
                    mode="lines",
                    name=curve,
                    opacity=0.7 if in_color_dict else 0.4,
                    line=dict(color=color),
                    showlegend=in_color_dict,
                )
            )

        fig = go.Figure(data=trace_objs)
        fig.update_layout(margin=dict(l=20, r=20, t=0, b=0), xaxis_title="tD", yaxis_title="NpD")
        st.plotly_chart(fig, theme="streamlit", use_container_width=True)
    else:
        st.text("Production results not found.")

with tabs[5]:
    st.write("## MICP Results")

    micp_name = json_dict[name]["micp"]
    path = f"{PROJECTS_FOLDER}/{name}/{micp_name}"
    if os.path.exists(path):
        micp = read_tsv(path)
        micp = micp.rename(
            columns={
                "snwp": "Saturation",
                "pc": "Pressure (Pa)",
                "dsn": "Volume Fraction",
                "radii": "Radii (mm)",
            },
        )

        fig = px.line(micp, x="Saturation", y="Pressure (Pa)", height=300, markers=True)
        fig.update_traces(marker_size=10)
        fig.update_layout(xaxis_range=[1, 0], margin=dict(l=20, r=20, t=0, b=0))
        st.plotly_chart(fig, theme="streamlit", use_container_width=True)

        fig = px.line(micp, x="Pressure (Pa)", y="Volume Fraction", height=300, markers=True)
        fig.update_traces(marker_size=10)
        fig.update_layout(margin=dict(l=20, r=20, t=0, b=0))
        st.plotly_chart(fig, theme="streamlit", use_container_width=True)

        fig = px.line(micp, x="Radii (mm)", y="Volume Fraction", height=300, markers=True)
        fig.update_traces(marker_size=10)
        fig.update_layout(margin=dict(l=20, r=20, t=0, b=0))
        st.plotly_chart(fig, theme="streamlit", use_container_width=True)

        # st.write("## MICP Table")
        # st.write(micp, use_container_width=True)
    else:
        st.text("micp results not found.")
