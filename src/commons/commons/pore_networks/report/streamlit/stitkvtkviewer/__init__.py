from typing import Optional
from pathlib import Path
import streamlit.components.v1 as components

frontend_dir = Path(__file__).parent.absolute()
_component_func = components.declare_component("stitkvtkviewer", path=str(frontend_dir))


def stitkvtkviewer(
    filenames: list,
    geometries_colors: Optional[list] = None,
    bg_color: Optional[list] = [0.58, 0.58, 0.8],
    ui_collapsed: Optional[bool] = True,
    rotate: Optional[bool] = False,
    key: Optional[str] = None,
):
    component_value = _component_func(
        filenames=filenames,
        geometries_colors=geometries_colors,
        bg_color=bg_color,
        ui_collapsed=ui_collapsed,
        rotate=rotate,
        key=key,
        default=0,
    )
    return component_value
