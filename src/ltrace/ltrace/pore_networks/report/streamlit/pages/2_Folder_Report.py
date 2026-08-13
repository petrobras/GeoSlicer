import streamlit as st
import pandas as pd
import os

import plotly.express as px
import plotly.graph_objects as go
import plotly.colors as pc

from utils import read_tsv, read_csv, read_json, read_volume, PROJECTS_FOLDER

st.set_page_config(
    page_title="PNM Report",
    # page_icon="📊",
    # layout="wide",
)

st.write("# 📊 Folder Report")

path = f"{PROJECTS_FOLDER}/folder_report.csv"
if os.path.exists(path):
    df = read_csv(path)

    df = df.rename(
        columns={
            "index": "Index",
            "permeability": "Permeability [mD]",
            "porosity": "Porosity",
            "realistic_production": "Production",
            "residual_So": "Residual Oil Saturation",
            "well": "Well",
        },
    )

    x_column = st.selectbox("X Column", df.columns, index=2)
    y_column = st.selectbox("Y Column", df.columns, index=3)
    color_column = st.selectbox("Color Column", df.columns, index=4)

    log_x = st.checkbox("Log scale on X-axis", value=False)
    log_y = st.checkbox("Log scale on Y-axis", value=False)

    fig = px.scatter(
        df,
        x=x_column,
        y=y_column,
        color=color_column,
        color_continuous_scale="viridis",
        title="",
        log_x=log_x,
        log_y=log_y,
    )
    fig.update_traces(marker={"size": 20})

    st.plotly_chart(fig, theme="streamlit", use_container_width=True)
else:
    st.text("Folder report not found.")
