from dask_image.imread import imread
from PIL import Image
import xarray as xr
import numpy as np
import os, sys, re, tempfile, tarfile, shutil
from .utils import build_filename


def extract_tar_file(filename, extract_dir=None):
    """
    Extract files from microtomography tarfile.

    Parameters:
        filename : str
            Microtomography tar filename.
        extract_dir : str, optional
            Directory where to save the extracted files (if None a temporary directory will be created).

    Returns:
        outputdir : str
            Directory where the extracted files were saved.
    """

    with tarfile.open(filename, "r") as t:
        t.extractall(extract_dir)

    return extract_dir


def read_netcdf_file(filename):
    """
    Read netcdf4 file.

    Parameters:
        filename : str
            Microtomography tar filename.

    Returns:
        ds : xr.Dataset
            microtom xarray Dataset
    """
    with xr.open_dataset(filename) as temp_ds:
        ds = temp_ds
    return ds


def read_tif_files(foldername, out_of_memory=False, save_nc_to=None):
    """
    Read microtomography tif files in a folder.

    Parameters:
        foldername : str
            Folder containing microtomography files.
        out_of_memory : bool, optional
            Read images lazily, without loading into memory.
            Defaults to False.
        save_nc_to : string, optional
            Path to a directory where a nc file will be stored.
            The default is None.

    Returns:
        ds : xr.Dataset
            Xarray Dataset with the information given by the file.
    """
    basename = os.path.basename(os.path.normpath(foldername))
    attrs = re.search(
        r"(?P<well>\w+)_(?P<sample_name>\w+)_(?P<condition>\w+)_(?P<sample_type>\w+)_(?P<resolution>\d+)nm", basename
    ).groupdict()
    attrs["resolution"] = float(attrs["resolution"]) / 1e6  # mm

    img = imread(os.path.join(foldername, "*.tif*"))

    dimz, dimy, dimx = img.shape

    attrs["dimx"] = dimx
    attrs["dimy"] = dimy
    attrs["dimz"] = dimz

    x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
    y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
    z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

    if not out_of_memory:
        img = img.compute()

    ds = xr.Dataset({"microtom": (("z", "y", "x"), img)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)
    ds.x.attrs["units"] = "mm"
    ds.y.attrs["units"] = "mm"
    ds.z.attrs["units"] = "mm"

    if save_nc_to is not None:
        ds.to_netcdf(os.path.join(save_nc_to, build_filename(ds) + ".nc"), "w")

    return ds


def read_tar_file(filename, extract_dir=None, out_of_memory=False, save_nc_to=None):
    """
    Read microtomography tar file. It assumes the filename follows the format:

    WELL_SAMPLE_CONDITION_TYPE_RESOLUTIONnm.tar (example 'LL36A_V011830H_LIMPA_P_41220nm.tar')

    Parameters:
        filename : str
            Microtomography tar filename.
        extract_dir : str, optional
            Directory where to save the extracted files (if None a temporary directory will be used).
            Defaults to None.
        out_of_memory : bool, optional
            Read images lazily, without loading into memory.
            Defaults to False.
        save_nc_to : string, optional
            Path to a directory where a nc file will be stored.
            The default is None.

    Returns:
        ds: xr.Dataset:
            microtom xarray Dataset
    """
    basename = os.path.splitext(os.path.basename(filename))[0]
    attrs = re.search(
        r"(?P<well>\w+)_(?P<sample_name>\w+)_(?P<condition>\w+)_(?P<sample_type>\w+)_(?P<resolution>\d+)nm", basename
    ).groupdict()
    attrs["resolution"] = float(attrs["resolution"]) / 1e6  # mm

    if extract_dir is None:
        tmp = True
        extract_dir = tempfile.mkdtemp()
    else:
        tmp = False

    with tarfile.open(filename, "r") as t:
        t.extractall(extract_dir)

    img = imread(os.path.join(extract_dir, basename, "*.tif*"))

    dimz, dimy, dimx = img.shape

    attrs["dimx"] = dimx
    attrs["dimy"] = dimy
    attrs["dimz"] = dimz

    x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
    y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
    z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

    if not out_of_memory:
        img = img.compute()

    ds = xr.Dataset({"microtom": (("z", "y", "x"), img)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)
    ds.x.attrs["units"] = "mm"
    ds.y.attrs["units"] = "mm"
    ds.z.attrs["units"] = "mm"

    if tmp and (not out_of_memory):
        shutil.rmtree(extract_dir)

    if save_nc_to is not None:
        ds.to_netcdf(os.path.join(save_nc_to, build_filename(ds) + ".nc"), "w")

    return ds


def read_raw_file(
    filename, nx=None, ny=None, nz=None, dtype=np.uint16, resolution=None, data_array="field", save_nc_to=None
):
    """
    Read microtomography raw file. It assumes the filename follows the format:
    WELL_SAMPLE_STATE_TYPE_TYPEOFIMAGE_NX_NY_NZ_RESOLUTION.raw (example 'LL36A_V011830H_LIMPA_B1_BIN_0256_0256_0256_04000nm.raw').
    If this format is not detected, the attributes well, sample, state, type, typeofimage are set to None, the dimensions nx, ny and nz and the dtype are mandatory.

    Parameters:
        filename : str
            .raw filename, see https://git.ep.petrobras.com.br/DRP/General/wikis/estrutura for more information.
            In the case the file format follows the above mentioned pattern, there is no need for any other information to open the file.
        nx : int, optional
            Dimension in voxels in the x direction.
            The default is None, and the dimension is given by the file name.
        ny : int, optional
            Dimension in voxels in the y direction.
            The default is None, and the dimension is given by the file name.
        nz : int, optional
            Dimension in voxels in the z direction.
            The default is None, and the dimension is given by the file name.
        dtype : type, optional
            Type which should be read in the raw file.
            The default is np.uint16, but it is ignored if the file has the name as described above.
        resolution : float, optional
            Resolution in mm.
            The default is None, and the resolution is given by the file name.
        data_array : str, optional
            Name of the data array which will be refered in the xarray Dataset.
            The default is field.
        save_nc_to : string, optional
            Path to a directory where a nc file will be stored.
            The default is None.

    Returns:
        ds : xr.Dataset
            Xarray Dataset with the information given by the file.
    """
    basename = os.path.splitext(os.path.basename(filename))[0]
    basename_list = basename.split("_")
    if len(basename_list) == 9:
        attrs = {}
        attrs["well"] = basename_list[0]
        attrs["sample_name"] = basename_list[1]
        attrs["condition"] = basename_list[2]
        attrs["sample_type"] = basename_list[3]
        image_type = basename_list[4]
        attrs["dimx"] = int(basename_list[5])
        attrs["dimy"] = int(basename_list[6])
        attrs["dimz"] = int(basename_list[7])
        attrs["resolution"] = float(int(basename_list[8].split("n")[0])) / 1e6  # mm
    else:
        if isinstance(nx, int) and isinstance(ny, int) and isinstance(nx, int):
            attrs = {}
            image_type = data_array
            attrs["dimx"] = int(nx)
            attrs["dimy"] = int(ny)
            attrs["dimz"] = int(nz)
            attrs["resolution"] = float(resolution)
        else:
            print("The dimensions of the raw file should be provided.")
            return 0

    x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
    y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
    z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

    type_data = dtype
    dict_name = data_array
    if ("BIN" in image_type) or ("BIW" in image_type):
        type_data = np.uint8
        dict_name = "bin"
    elif "MANGO" in image_type:
        type_data = np.uint8
        dict_name = "mango"
    elif "BASINS" in image_type:
        type_data = np.uint8
        dict_name = "basins"
    elif "CT" in image_type:
        type_data = np.uint16
        dict_name = "microtom"
    elif "KABS" in image_type:
        type_data = np.float64
        dict_name = "kabs"

    img = np.fromfile(filename, dtype=type_data, count=-1, sep="")
    img = np.reshape(img, (attrs["dimz"], attrs["dimy"], attrs["dimx"]))
    if "BIW" in image_type:
        img = 1 - img

    ds = xr.Dataset({dict_name: (("z", "y", "x"), img)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)
    ds.x.attrs["units"] = "mm"
    ds.y.attrs["units"] = "mm"
    ds.z.attrs["units"] = "mm"

    if "MANGO" in image_type:
        ds["bin"] = (("z", "y", "x"), (img <= 1).astype(np.uint8))
    elif "BASINS" in image_type:
        ds["bin"] = (("z", "y", "x"), (img == 1).astype(np.uint8))

    if save_nc_to is not None:
        ds.to_netcdf(os.path.join(save_nc_to, build_filename(ds) + ".nc"), "w")

    return ds


def read_vtk_file(
    filename,
    endianness="little",
    well=None,
    sample_name=None,
    condition=None,
    sample_type=None,
    resolution=0.001,
    data_array="field",
    save_nc_to=None,
):
    """
    Read vtk file. Information about the file is read from the header of the vtk.

    Parameters:
        filename : str
            Name of the vtk file.
        endianness : str, optional
            Endianness of the file which will be read.
            The default is little. The other possible choice is big.
        well : str, optional
            Well from where the sample was taken.
            The default is None.
        sample_name : str, optional
            Name of the sample.
            The default is None.
        condition : str, optional
            Condition in which the sample is.
            The default is None.
        sample_type : str, optional
            Type of sample.
            The default is None.
        resolution : float, optional
            Resolution in mm.
            The default is 0.001.
        data_array : str, optional
            Name of the data array which will be refered in the xarray.
            The default is field.
        save_nc_to : string, optional
            Path to a directory where a nc file will be stored.
            The default is None.

    Returns:
        ds : xr.Dataset
            Xarray Dataset with the information given by the file.

    """
    attrs = {}
    attrs["well"] = well
    attrs["sample_name"] = sample_name
    attrs["condition"] = condition
    attrs["sample_type"] = sample_type

    total_len = 0
    with open(filename, "r", encoding="latin-1") as file:
        header_label = ""
        while header_label != "LOOKUP_TABLE":
            line_data = file.readline()
            header_label = line_data.split(" ")[0]
            if header_label == "DIMENSIONS":
                attrs["dimx"] = int(line_data.split(" ")[1])
                attrs["dimy"] = int(line_data.split(" ")[2])
                attrs["dimz"] = int(line_data.split(" ")[3].split("\n")[0])
            elif header_label == "SCALARS":
                if line_data.split(" ")[2] == "float\n":
                    type_data = np.float32
                elif line_data.split(" ")[2] == "int\n":
                    type_data = np.uint16
                elif line_data.split(" ")[2] == "unsigned_char\n":
                    type_data = np.uint8
                else:
                    print("Only unsigned_char and float are accepted in the moment.")
                    sys.exit()
            elif header_label == "ASCII":
                print("Does not read ASCII files.")
                sys.exit()
        total_len = file.tell()

    img = []
    if endianness == "little":
        img = np.reshape(
            np.fromfile(filename, dtype=type_data, count=-1, sep="", offset=total_len),
            (attrs["dimz"], attrs["dimy"], attrs["dimx"]),
        )
    elif endianness == "big":
        img = np.reshape(
            np.fromfile(filename, dtype=type_data, count=-1, sep="", offset=total_len).byteswap(),
            (attrs["dimz"], attrs["dimy"], attrs["dimx"]),
        )

    attrs["resolution"] = resolution
    x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
    y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
    z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

    ds = xr.Dataset({data_array: (("z", "y", "x"), img)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)
    ds.x.attrs["units"] = "mm"
    ds.y.attrs["units"] = "mm"
    ds.z.attrs["units"] = "mm"

    if save_nc_to is not None:
        ds.to_netcdf(os.path.join(save_nc_to, build_filename(ds, data_array=data_array) + ".nc"), "w")

    return ds


def write_raw_file(ds, save_raw_to, data_array="microtom", temp=False):
    """
    Write data_array from a dataset in a raw file.

    Parameters:
        input_data : xarray.Dataset
            xarray Dataset containing the data_array, which will be .
        save_raw_to : string
            Path to a directory where a raw file will be stored, if it is a xarray.Dataset (the name of the file is created from the dataset info).
            Full path (including the file name) where a raw file will be stored.
        data_array : str, optional
            Name of the data array to be converted in a raw file, only for xarray.Dataset.
            The default is microtom.
    """
    if not os.path.exists(save_raw_to):
        os.mkdir(save_raw_to)
    basename = build_filename(ds, data_array=data_array, with_dimensions=True) + ".raw"
    if temp:
        basename = "temp" + basename
    ds[data_array].data.tofile(os.path.join(save_raw_to, basename))
    return basename


def write_tif_files(ds, save_tifs_to, data_array="microtom"):
    """
    Write microtomography tif files in a folder.

    Parameters:
        ds : xarray.Dataset
            xarray Dataset containing the data array.
        save_tifs_to : string
            Path to a directory where a stack of tif files will be saved.
        data_array : str, optional
            Name of the data array to be converted in a stack of tif files.
            The default is microtom.
    """
    foldername = os.path.join(save_tifs_to, build_filename(ds))
    if not os.path.exists(save_tifs_to):
        os.mkdir(save_tifs_to)
    if not os.path.exists(foldername):
        os.mkdir(foldername)

    basename = build_filename(ds, data_array=data_array)

    for i in range(ds[data_array].data.shape[0]):
        filename = basename + "_{:04d}.tif".format(i + 1)
        print(os.path.join(foldername, filename))
        Image.fromarray(np.asarray(ds[data_array].data[i, :, :])).save(
            os.path.join(foldername, filename), format="tiff"
        )


def write_vtk_file(ds, save_vtk_to, data_array="field"):
    """
    Write data_array in a binary vtk file.

    Parameters:
        ds : xarray.Dataset or numpy.array
            xarray Dataset containing the data array or numpy.ndarray with the same information.
            If it is a numpy.ndarray, data_array is not considered.
        save_vtk_to : string, optional
            Full path to a file where a vtk file will be stored.
        data_array : str, optional
            Name of the data array to be converted in a raw file.
            The default is microtom.
    """
    if type(ds) == xr.Dataset:
        if data_array == "microtom":
            image_type = "CT"
            data_type = "int"
        elif data_array == "bin":
            image_type = "BIN"
            data_type = "unsigned_char"
        elif data_array == "mango":
            image_type = "MANGO"
            data_type = "unsigned_char"
        elif data_array == "field":
            image_type = "FIELD"
            data_type = "float"

        npoints = np.int64(ds.attrs["dimx"]) * np.int64(ds.attrs["dimy"]) * np.int64(ds.attrs["dimz"])
        with open(save_vtk_to, "w", encoding="latin-1") as file:
            file.write("# vtk DataFile Version 2.0\n")
            file.write("Geometria\n")
            file.write("BINARY\n")
            file.write("Dataset STRUCTURED_POINTS\n")
            file.write(
                "DIMENSIONS " + str(ds.attrs["dimx"]) + " " + str(ds.attrs["dimy"]) + " " + str(ds.attrs["dimz"]) + "\n"
            )
            file.write("ASPECT_RATIO 1 1 1\n")
            file.write("ORIGIN 0 0 0\n")
            file.write("POINT_DATA " + str(npoints) + "\n")
            file.write("SCALARS geometria " + data_type + "\n")
            file.write("LOOKUP_TABLE default\n")

        with open(save_vtk_to, "ba+") as file:
            ds[data_array].data.tofile(file)

    if type(ds) == np.ndarray:
        npoints = np.int64(ds.shape[0]) * np.int64(ds.shape[1]) * np.int64(ds.shape[2])
        if (ds.dtype) == np.float32:
            data_type = "float"
        if (ds.dtype) == np.int16:
            data_type = "int"
        if (ds.dtype) == np.uint8:
            data_type = "unsigned_char"

        with open(save_vtk_to, "w", encoding="latin-1") as file:
            file.write("# vtk DataFile Version 2.0\n")
            file.write("Geometria\n")
            file.write("BINARY\n")
            file.write("Dataset STRUCTURED_POINTS\n")
            file.write("DIMENSIONS " + str(ds.shape[2]) + " " + str(ds.shape[1]) + " " + str(ds.shape[0]) + "\n")
            file.write("ASPECT_RATIO 1 1 1\n")
            file.write("ORIGIN 0 0 0\n")
            file.write("POINT_DATA " + str(npoints) + "\n")
            file.write("SCALARS geometria " + data_type + "\n")
            file.write("LOOKUP_TABLE default\n")

        with open(save_vtk_to, "ba+") as file:
            ds.tofile(file)


def ds_from_np(
    np_data,
    ds=None,
    data_array="bin",
    well=None,
    sample_name=None,
    condiction=None,
    sample_type=None,
    resolution=None,
    main_direction="z",
):
    if ds is None:
        attrs = {}
        attrs["well"] = well if well is not None else "None"
        attrs["sample_name"] = sample_name if sample_name is not None else "None"
        attrs["condition"] = condiction if condiction is not None else "None"
        attrs["sample_type"] = sample_type if sample_type is not None else "None"
        attrs["resolution"] = resolution if resolution is not None else float(1.0)

        if main_direction == "z":
            attrs["dimx"] = np_data.shape[2]
            attrs["dimy"] = np_data.shape[1]
            attrs["dimz"] = np_data.shape[0]

            x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
            y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
            z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

            ds = xr.Dataset({data_array: (("z", "y", "x"), np_data)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)
        elif main_direction == "y":
            np_data = np_data.transpose((1, 2, 0))
            attrs["dimx"] = np_data.shape[0]
            attrs["dimy"] = np_data.shape[2]
            attrs["dimz"] = np_data.shape[1]

            x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
            y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
            z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

            ds = xr.Dataset({data_array: (("z", "y", "x"), np_data)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)
        elif main_direction == "x":
            np_data = np_data.transpose((2, 0, 1))
            attrs["dimx"] = np_data.shape[1]
            attrs["dimy"] = np_data.shape[0]
            attrs["dimz"] = np_data.shape[2]

            x = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimx"] - 0.5), attrs["dimx"])
            y = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimy"] - 0.5), attrs["dimy"])
            z = np.linspace(attrs["resolution"] * 0.5, attrs["resolution"] * (attrs["dimz"] - 0.5), attrs["dimz"])

            ds = xr.Dataset({data_array: (("z", "y", "x"), np_data)}, coords={"z": z, "y": y, "x": x}, attrs=attrs)

        ds.x.attrs["units"] = "voxels" if resolution is None else "mm"
        ds.y.attrs["units"] = "voxels" if resolution is None else "mm"
        ds.z.attrs["units"] = "voxels" if resolution is None else "mm"
    else:
        if main_direction != "z":
            print("Rotations are not allowed if the aim is to incorporate the numpy into an existing xr.dataset.")
            return
        if (
            (attrs["dimx"] == np.data.shape[2])
            and (attrs["dimy"] == np.data.shape[1])
            and (attrs["dimz"] == np.data.shape[0])
        ):
            ds[data_array] = (("z", "y", "x"), np_data)
    return ds
