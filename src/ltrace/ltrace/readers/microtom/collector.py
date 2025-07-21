from collections import defaultdict
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
import re
import slicer
import traceback

from ltrace.slicer import helpers, data_utils as du

from .utils import read_file, revert_z_axis


def create_volume_from(sim_data, ref_node=None, name="", environment=None, direction="z"):
    volume_node = helpers.createTemporaryVolumeNode(
        slicer.vtkMRMLScalarVolumeNode,
        name,
        environment=environment,
        content=ref_node,  # copy reference
    )

    volume_node.SetAndObserveImageData(None)

    if sim_data.dtype == np.float64:
        sim_data = sim_data.astype(np.float32)

    sim_ndarray = sim_data.values if isinstance(sim_data, xr.DataArray) else sim_data

    if sim_ndarray.ndim == 4:
        sim_ndarray = sim_ndarray[0, :, :, :]

    slicer.util.updateVolumeFromArray(volume_node, revert_z_axis(direction, sim_ndarray) if direction else sim_ndarray)
    volume_node.Modified()
    return volume_node


def get_dataset(filepath: Path) -> xr.Dataset:
    if not Path(filepath).exists():
        raise FileNotFoundError("Missing file")

    data: xr.Dataset = read_file(filepath)

    return data


class BaseResultCompiler:
    def __init__(self) -> None:
        self.missing_results = []

    def __call__(self, results):
        nodes, ref_node, project_name = self.compile(results)  # TODO better way to inform the parent node?

        helpers.addNodesToScene(nodes)
        helpers.setNodesHierarchy(nodes, ref_node, projectDirName=project_name)

        if len(self.missing_results) > 0:
            helpers.showMissingResults(self.missing_results)

        return nodes, ref_node, project_name

    def compile(self, simulation, simulator, name, ref_node, tag, direction, prefix):
        raise NotImplementedError


class PorosimetryCompiler(BaseResultCompiler):
    def __init__(self) -> None:
        super().__init__()

        self.vfrac = None

    def compile(self, results):
        simulator = results.get("simulator", "")
        prefix = results.get("output_prefix", "microtom")
        direction = results.get("direction", "z")
        # tag = results.get("geoslicer_tag", "") TODO this should be removed
        ref_node_id = results.get("reference_volume_node_id", None)
        ouputs = results.get("results", [])

        self.vfrac = results.get("vfrac", None)

        ref_node = helpers.tryGetNode(ref_node_id)

        project_name = f"{prefix}_{simulator}"

        name = [v.upper() for v in (prefix, simulator, direction) if v]

        sim_output_filepath = ouputs[0]

        nodes = []

        try:

            simulation = get_dataset(sim_output_filepath)

            nodes.append(
                create_volume_from(simulation[simulator], ref_node, name="_".join(name) + "_Volume", direction=None)
            )
            nodes.append(self.create_table_from(simulation, simulator, name="_".join(name) + "_Data"))

        except TypeError:
            self.missing_results.append((sim_output_filepath, "Invalid file format"))
            import traceback

            traceback.print_exc()
        except FileNotFoundError as e:
            self.missing_results.append((sim_output_filepath, "File not found"))
        except Exception as e:
            self.missing_results.append((sim_output_filepath, repr(e)))
            logging.error(repr(e))
            import traceback

            traceback.print_exc()

        return nodes, ref_node, project_name

    def create_table_from(self, simulation, simulator, name="", environment=None):
        radii = np.array(simulation[f"radii_{simulator}"])
        snw = np.array(simulation[f"snw_{simulator}"])

        sw = 1.0 - snw
        table = {
            "radii (voxel)": radii,
            "1/radii": 1.0 / radii,
            "log(1/radii)": np.log(1.0 / radii),
            "Snw (frac)": snw,
            "Sw (frac)": sw,
        }

        if self.vfrac:
            table["Sws (frac)"] = sw
            sw_corrected = self.vfrac + sw * (1.0 - self.vfrac)
            table["Sw (frac)"] = sw_corrected
            table["Snw (frac)"] = 1 - sw_corrected

        table_node = helpers.createTemporaryNode(slicer.vtkMRMLTableNode, name, environment=environment)

        df = pd.DataFrame(table).round(decimals=5)
        du.dataFrameToTableNode(df, table_node)
        table_node.Modified()

        return table_node


class StokesKabsCompiler(BaseResultCompiler):
    def __init__(self) -> None:
        super().__init__()

    def compile(self, results):
        simulator = results.get("simulator", "")
        prefix = results.get("output_prefix", "microtom")
        direction = results.get("direction", "z")
        # tag = results.get("geoslicer_tag", "")
        ref_node_id = results.get("reference_volume_node_id", None)
        outputs = results.get("results", [])
        load_volumes = results.get("load_volumes", False)

        ref_node = helpers.tryGetNode(ref_node_id)

        project_name = f"{prefix}_{simulator}"

        attributes = []
        nodes = []

        for sim_output_filepath in outputs:
            try:
                simulation = get_dataset(sim_output_filepath)

                if load_volumes:
                    """Extract volumes for every type of kAbs"""
                    for rtype in ("bin", "velocity", "pressure"):
                        try:
                            name = "_".join([v.upper() for v in (prefix, simulator, direction, rtype) if v])
                            node = create_volume_from(
                                simulation[rtype],
                                ref_node,
                                name=name,
                                direction=None if "darcy" in simulator else direction,
                            )
                            nodes.append(node)
                        except KeyError:
                            continue

                attributes.append(simulation.attrs)

            except TypeError:
                self.missing_results.append((sim_output_filepath, "Invalid file format"))
                continue
            except FileNotFoundError as e:
                self.missing_results.append((sim_output_filepath, "File not found"))
                continue
            except Exception as e:
                logging.error(f"{e}.\n{traceback.format_exc()}")
                continue

        name = "_".join([v.upper() for v in (prefix, simulator, direction) if v]) + "_Variables"
        table_node = self.compile_table(attributes, simulator, name)
        nodes.append(table_node)

        return nodes, ref_node, project_name

    def compile_table(self, datasets_attributes, simulator, name):
        # Extract attributes
        attributes = defaultdict(list)
        try:
            for attrs in datasets_attributes:
                attributes["Total Porosity (frac)"].append(float(attrs.get("total_porosity", "nan")))
                attributes["Resolved Porosity (frac)"].append(float(attrs.get("resolved_porosity", "nan")))
                attributes["Permeability (mD)"].append(float(attrs.get("permeability", "nan")))

                if "stokes_kabs_rev" in simulator:
                    count = int(attrs["dimx"]) * int(attrs["dimy"]) * int(attrs["dimz"])
                    attributes["Subvolume Voxel Count"].append(count)

                    cut_info = attrs["cut_info"]
                    attributes["Subvolume Cut Info"].append(str(cut_info))

        except Exception as e:
            logging.error(f"{e}.\n{traceback.format_exc()}")

        table_node = helpers.createTemporaryNode(slicer.vtkMRMLTableNode, name)

        df = pd.DataFrame(attributes).round(decimals=5)
        du.dataFrameToTableNode(df, table_node)
        table_node.Modified()
        return table_node


class KrelCompiler(BaseResultCompiler):
    def __init__(self) -> None:
        super().__init__()

        self.sim_pattern = re.compile(r"\\sim(\d+)\\")

    def compile(self, results):
        simulator = results.get("simulator", "")
        prefix = results.get("output_prefix", "microtom")
        direction = results.get("direction", "z")
        # tag = results.get("geoslicer_tag", "")
        ref_node_id = results.get("reference_volume_node_id", None)
        outputs = results.get("results", [])

        diameters = results.get("diameters", [])

        ref_node = helpers.tryGetNode(ref_node_id)

        project_name = f"{prefix}_{simulator}"

        nodes = []

        for sim_output_filepath in outputs:
            try:
                ith_file = str(sim_output_filepath)

                index = int(self.sim_pattern.search(ith_file).group(1)) - 1

                if not Path(sim_output_filepath).exists():
                    raise FileNotFoundError("Missing file")

                if ith_file.endswith(".csv"):
                    name = f"Results [diameter={diameters[index]}]"
                    node = self.compile_table(name, sim_output_filepath)
                    node.SetAttribute("diameter", str(diameters[index]))
                elif "blue_" in ith_file and ith_file.endswith(".vtk"):
                    name = f"Blue volume [diameter={diameters[index]}]"
                    simulation = read_file(sim_output_filepath).to_array()
                    node = create_volume_from(simulation, ref_node, name=name, direction=direction)
                    node.SetAttribute("diameter", str(diameters[index]))
                elif "red_" in ith_file and ith_file.endswith(".vtk"):
                    name = f"Red volume [diameter={diameters[index]}]"
                    simulation = read_file(sim_output_filepath).to_array()
                    node = create_volume_from(simulation, ref_node, name=name, direction=direction)
                    node.SetAttribute("diameter", str(diameters[index]))

                nodes.append(node)

            except TypeError:
                self.missing_results.append((sim_output_filepath, "Invalid file format"))
                import traceback

                traceback.print_exc()
            except FileNotFoundError as e:
                self.missing_results.append((sim_output_filepath, "File not found"))
            except Exception as e:
                self.missing_results.append((sim_output_filepath, repr(e)))
                print("--------------------------------------------------------------------------------------------")
                import traceback

                traceback.print_exc()

        return nodes, ref_node, project_name

    def compile_table(self, name, file, tag=None):
        table_node = helpers.createTemporaryNode(slicer.vtkMRMLTableNode, name, environment=tag)
        df = pd.read_csv(file, header=0, index_col=False, delimiter="\t", dtype=np.float32).round(decimals=5)
        du.dataFrameToTableNode(df, table_node)
        table_node.Modified()
        return table_node
