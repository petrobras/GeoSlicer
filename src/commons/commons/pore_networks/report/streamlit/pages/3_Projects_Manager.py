import streamlit as st
import pandas as pd
from utils import read_json, PROJECTS_FOLDER, convert_vtk_to_ascii, convert_vtk_to_xml
from pathlib import Path
import os
import shutil
import json
import re
import nrrd
import numpy as np
import zipfile
import io
from datetime import datetime


def load_projects(zip_file, overwrite):
    target_dir = Path(PROJECTS_FOLDER) / "temporary"

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir)

    try:
        progress_index = 1
        progress_text = "Operation in progress. Please wait."
        progress_bar = st.progress(progress_index, text=progress_text)

        with zipfile.ZipFile(zip_file, "r") as zip_ref:
            zip_ref.extractall(target_dir)

        load_path = Path(target_dir / "static")
        if not os.path.exists(load_path / "projects.json"):
            st.error('File "static/projects.json" not found in uploaded zip.')
            return

        json_dict = read_json(load_path / "projects.json")
        if os.path.exists(f"{PROJECTS_FOLDER}/projects.json"):
            dest_json_dict = read_json(f"{PROJECTS_FOLDER}/projects.json")
        else:
            dest_json_dict = {}

        df = pd.read_csv(load_path / "folder_report.csv", index_col=0)
        if os.path.exists(f"{PROJECTS_FOLDER}/folder_report.csv"):
            dest_df = pd.read_csv(f"{PROJECTS_FOLDER}/folder_report.csv", index_col=0)
            dest_df = pd.concat([df, dest_df], ignore_index=True)
        else:
            dest_df = df
        dest_df.to_csv(f"{PROJECTS_FOLDER}/folder_report.csv", index=True, mode="w")

        not_overwritten_files = False
        for key in json_dict.keys():
            progress_bar.progress(min(progress_index / len(json_dict), 1), text=progress_text)
            progress_index += 1

            source_dir = load_path / key
            dest_dir = Path(PROJECTS_FOLDER) / key
            if os.path.exists(dest_dir):
                if not overwrite:
                    not_overwritten_files = True
                    continue
                else:
                    shutil.rmtree(dest_dir)

            shutil.copytree(source_dir, dest_dir)
            convert_necessary(json_dict, key, dest_dir)
            dest_json_dict.update({key: json_dict[key]})

        if not_overwritten_files:
            st.info(
                'Some projects in your `.zip` file were not copied because they already exist in the current report. To replace the existing projects with the ones from the `.zip` file, please ensure that the "Overwrite local data" option is selected before proceeding.'
            )
        else:
            st.success("Projects have been successfully extracted and added to the report.")
    except Exception as e:
        st.error(
            f"""
            Failed to load projects from `{zip_file}` due to the error:
            {e}
            """
        )
    finally:
        if dest_json_dict and os.path.exists(PROJECTS_FOLDER):
            with open(f"{PROJECTS_FOLDER}/projects.json", "w") as file:
                json.dump(dest_json_dict, file)

        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        progress_bar.empty()


def convert_necessary(json_dict, key, dest_dir):
    if json_dict[key]["multiangle_model"].endswith(".vtk"):
        filename = json_dict[key]["multiangle_model"]
        newname = re.sub(".vtk", ".vtp", filename)
        input_file = os.path.join(PROJECTS_FOLDER, key, filename)
        output_file = os.path.join(PROJECTS_FOLDER, key, newname)
        convert_vtk_to_xml(input_file, output_file)
        json_dict[key]["multiangle_model"] = newname

    for filekey, filename in json_dict[key].items():
        if filename.endswith(".nrrd"):
            input_file = os.path.join(PROJECTS_FOLDER, key, filename)
            if os.path.getsize(input_file) > 200000000:
                data, header = nrrd.read(input_file)
                original_dimensions = np.array(data.shape)
                target_dimensions = np.array([200, 200, 200])
                stride = original_dimensions // target_dimensions
                downscaled_data = data[:: stride[0], :: stride[1], :: stride[2]]
                nrrd.write(input_file, downscaled_data)

        if filename.endswith(".vtk"):
            with open(dest_dir / filename, "br") as file:
                lines = file.readlines()
                if len(lines) >= 3 and lines[2].strip() == b"BINARY":
                    newname = re.sub(".vtk", "_ascii.vtk", filename)
                    input_file = os.path.join(PROJECTS_FOLDER, key, filename)
                    output_file = os.path.join(PROJECTS_FOLDER, key, newname)
                    convert_vtk_to_ascii(input_file, output_file)
                    json_dict[key][filekey] = newname


st.set_page_config(
    page_title="PNM Report",
    page_icon="📊",
    # layout="wide",
)

st.write("# 💾 Projects Manager")

tab = st.tabs(["Import Projects", "Export Report"])

with tab[0]:
    zip_files = st.file_uploader(
        "Select the `.zip` files with PNM Report projects:",
        type="zip",
        accept_multiple_files=False,
        key="import",
    )
    checkbox = st.checkbox("Overwrite local data")
    load_button = st.button("Load")

    if load_button:
        load_projects(zip_files, checkbox)

with tab[1]:
    if st.button("Generate zip file for download", use_container_width=True):
        buf = io.BytesIO()
        report_path = Path(PROJECTS_FOLDER).resolve().parent
        progress_index = 1
        progress_text = "Operation in progress. Please wait."
        progress_bar = st.progress(progress_index, text=progress_text)
        with zipfile.ZipFile(buf, "x", zipfile.ZIP_DEFLATED) as zip_file:
            report_list = list(report_path.rglob("*"))
            for entry in report_list:
                zip_file.write(entry, entry.relative_to(report_path))
                progress_bar.progress(progress_index / len(report_list), text=progress_text)
                progress_index += 1

        st.download_button(
            label="Download zip",
            data=buf.getvalue(),
            file_name="PNM_Report.zip",
            mime="application/zip",
            use_container_width=True,
        )

if os.path.exists(f"{PROJECTS_FOLDER}/projects.json"):
    json_dict = read_json(f"{PROJECTS_FOLDER}/projects.json")
    df = pd.DataFrame(json_dict).T

    ctime = []
    for proj in json_dict.keys():
        dir_stat = os.stat(Path(PROJECTS_FOLDER) / proj)
        creation_time = datetime.fromtimestamp(dir_stat.st_ctime).strftime("%d-%m-%Y %H:%M:%S")
        ctime.append(creation_time)

    df_nulls = df.notnull()
    if len(ctime) < len(df_nulls):
        ctime += [""] * (len(df_nulls) - len(ctime))
    elif len(ctime) > len(df_nulls):
        ctime = ctime[: len(df_nulls)]
    index_to_use = df_nulls.index
    false = pd.Series([False] * len(df_nulls), index=index_to_use)
    ctime = pd.Series(ctime, index=index_to_use)
    dict_final = {
        "Volume": df_nulls.get("volume", false),
        "Network": df_nulls.get("pore_table", false)
        & df_nulls.get("throat_table", false)
        & df_nulls.get("pore_polydata_0", false)
        & df_nulls.get("throat_polydata_0", false),
        "Network (Flow Properties)": df_nulls.get("flow_props_pore_network", false)
        & df_nulls.get("flow_props_throat_network", false),
        "Kabs": df_nulls.get("flow_rate", false)
        & df_nulls.get("perm_node", false)
        & df_nulls.get("multiangle_model", false)
        & df_nulls.get("multiangle_arrow_model", false)
        & df_nulls.get("multiangle_plane_model", false)
        & df_nulls.get("multiangle_sphere_model", false)
        & df_nulls.get("multiangle_statistics", false),
        "Krel": df_nulls.get("sensibility", false),
        "Production": df_nulls.get("production", false),
        "MICP": df_nulls.get("micp", false),
        "Creation date": ctime,
    }

    st.dataframe(pd.DataFrame(dict_final))
