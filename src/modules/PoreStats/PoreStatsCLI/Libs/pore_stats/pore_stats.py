import os
import glob
import re
import shutil
import argparse
import pandas as pd
import tempfile

from pathlib import Path
from workflow.ThinSectionLoader import ThinSectionLoader
from workflow.PoreSegmenter import PoreSegmenter
from workflow.ForegroundSegmenter import ForegroundSegmenter
from workflow.PoreCleaner import PoreCleaner
from workflow.InspectorInstanceSegmenter import InspectorInstanceSegmenter
from workflow.commons import delete_tmp_nrrds, get_model_type


def main(args):
    tmp_dir = Path(tempfile.TemporaryDirectory().name)

    try:
        output_dir_path = Path(args.output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        image_filter = None
        no_px_filter = None
        if args.max_frags == "custom":
            image_filter_file = Path(__file__).parent / "filter_images.csv"
            image_filter = pd.read_csv(image_filter_file, delimiter=";")
        if args.use_px == "custom":
            no_px_filter = pd.read_csv(Path(__file__).parent / "not_use_px.csv", header=None)[0]

        pores_output_dir = None
        if args.export_images or args.export_sheets or args.export_las:
            pores_output_dir = output_dir_path / "pores"
            pores_output_dir.mkdir(parents=True, exist_ok=True)

        pore_model_type = get_model_type(args.pore_model)

        thin_section_loader = ThinSectionLoader(
            args.pixel_size, using_bayesian="bayes" in pore_model_type, do_resize=args.resize
        )
        pore_segmenter = PoreSegmenter(args.pore_model, args.seg_cli)
        foreground_segmenter = ForegroundSegmenter(args.foreground_cli)
        pore_cleaner = PoreCleaner(
            pore_model_type,
            args.keep_spurious,
            args.keep_residues,
            args.remove_spurious_cli,
            args.clean_resin_cli,
            save_unclean_resin=args.save_unclean_resin,
        )
        inspector_instance_segmenter = InspectorInstanceSegmenter(
            args.algorithm,
            args.min_size,
            args.sigma,
            args.min_distance,
            args.pixel_size,
            args.inspector_cli,
            args.no_inspector,
        )

        if not args.exclude_ooids:
            from workflow.OoidSegmenter import (
                OoidSegmenter,
            )  # importando só aqui para não requerer as dependências específicas (stardist e csbdeep) desnecessariamente

            ooids_output_dir = output_dir_path / "ooids"
            ooids_output_dir.mkdir(parents=True, exist_ok=True)
            ooid_segmenter = OoidSegmenter(resized_input=args.resize)

            ooids_size_min_scales_log2 = [float("-inf")] + list(range(-8, 3)) + [6, 8, float("inf")]
            ooids_size_classes = [
                "argila",
                "silte muito fino",
                "silte fino",
                "silte médio",
                "silte grosso",
                "areia muito fina",
                "areia fina",
                "areia média",
                "areia grossa",
                "areia muito grossa",
                "grânulo",
                "seixo",
                "calhau",
                "matacão",
            ]
            ooids_rock_type = {
                cls: (
                    "argilito"
                    if "argila" in cls
                    else "siltito"
                    if "silte" in cls
                    else "arenito"
                    if "areia" in cls
                    else "conglomerado_ou_brecha"
                )
                for cls in ooids_size_classes
            }

        if args.netcdf:
            from workflow.NetCDFExporter import NetCDFExporter

            netcdfs_output_dir = output_dir_path / "netCDFs"
            netcdfs_output_dir.mkdir(parents=True, exist_ok=True)
            netcdf_exporter = NetCDFExporter(netcdfs_output_dir, args.pixel_size)

        generate_sheets = args.export_sheets or args.export_las
        if args.export_images:
            from workflow.ImageExporter import ImageExporter

            image_exporter = ImageExporter()
        if generate_sheets:
            from workflow.SheetExporter import SheetExporter

            sheet_exporter = SheetExporter(temporary=not args.export_sheets)
        if args.export_las:
            from workflow.LASExporter import LASExporter

            las_exporter = LASExporter()

        well_names = set()
        image_paths = []
        extension_pattern = "|".join(
            [extension[1:] for extension in ThinSectionLoader.THIN_SECTION_LOADER_FILE_EXTENSIONS]
        )
        image_file_pattern = rf"^.+(_(\d*[.,]?\d+)(-?\d+)?([a-zA-Z]+))(_.+)*_c1\.({extension_pattern})$"  # WELL_8888[.,]88_info*_c1.extension
        for filename in os.listdir(args.input_dir):
            if re.search(image_file_pattern, filename):
                well_names.add(filename.split("_")[0])
                image_paths.append((Path(args.input_dir) / filename).as_posix())

        if len(image_paths) == 0:
            raise FileNotFoundError("No valid images were found in the input directory.")
        if len(well_names) > 1:
            raise ValueError(
                f"The input directory is expected to contain images from a single well. Got wells {well_names}"
            )

        image_paths = sorted(image_paths)
        n_images = len(image_paths)
        image_idx = 0
        checkpoint_path = output_dir_path / "checkpoint.txt"
        if checkpoint_path.exists():
            with open(checkpoint_path, "r") as checkpoint:
                resume_image_path = checkpoint.readline()
                resume_image_path = Path(resume_image_path).as_posix()
            image_idx = image_paths.index(resume_image_path)
            print("\n * Resuming from", resume_image_path, end=" *\n")
        image_paths = image_paths[image_idx:]

        for image_path in image_paths:
            with open(checkpoint_path, "w") as checkpoint:
                checkpoint.write(image_path)

            image_filename = os.path.basename(image_path)
            image_name = os.path.splitext(image_filename)[0]
            print("\n===", image_name, f"({image_idx+1}/{n_images})", "===\n")
            image_idx += 1

            n_largest_islands = None
            if isinstance(args.max_frags, int):
                n_largest_islands = args.max_frags
            elif image_filter is not None:
                n_largest_islands = (
                    int(image_filter[image_filter["file"] == image_filename]["n_useful_islands"])
                    if image_filename in image_filter["file"].values
                    else None
                )
                if n_largest_islands == 0:
                    continue

            load_px_image_path = None
            px_rock_area_path = None
            if not args.keep_residues:
                if args.use_px == "all" or (no_px_filter is not None and not no_px_filter.isin([image_filename]).any()):
                    load_px_image_path = thin_section_loader.run(image_path.replace("_c1", "_c2"), tmp_nrrd_dir=tmp_dir)
                    if args.reg_method == "auto":
                        px_rock_area_path = foreground_segmenter.run(load_px_image_path)

            loaded_image_file_path = thin_section_loader.run(image_path, tmp_nrrd_dir=tmp_dir)
            pore_binary_seg_file_path = pore_segmenter.run(loaded_image_file_path)
            frags_file_path, rock_area_path = foreground_segmenter.run(
                loaded_image_file_path, pore_binary_seg_file_path, n_largest_islands
            )
            pore_binary_seg_file_path = pore_cleaner.run(
                frags_file_path,
                pore_binary_seg_file_path,
                px_image_path=load_px_image_path,
                pp_rock_area_path=rock_area_path,
                px_rock_area_path=px_rock_area_path,
                decide_best_reg=args.reg_method == "auto",
            )
            pore_instance_seg_file_path, pore_report_file_path = inspector_instance_segmenter.run(
                pore_binary_seg_file_path, generate_partitions=True
            )

            if args.export_images:
                image_exporter.run(loaded_image_file_path, pore_instance_seg_file_path, pores_output_dir.as_posix())
            if generate_sheets:
                sheet_exporter.run(loaded_image_file_path, pore_report_file_path, pores_output_dir.as_posix())

            if not args.exclude_ooids:
                ooid_seg_file_path = ooid_segmenter.run(frags_file_path, pore_instance_seg_file_path)
                ooid_seg_file_path, ooid_report_file_path = inspector_instance_segmenter.run(
                    ooid_seg_file_path, generate_partitions=False
                )

                if args.export_images:
                    image_exporter.run(loaded_image_file_path, ooid_seg_file_path, ooids_output_dir.as_posix())
                if generate_sheets:
                    sheet_exporter.run(
                        loaded_image_file_path,
                        ooid_report_file_path,
                        ooids_output_dir.as_posix(),
                        instance_type="ooids",
                        groups={
                            "property": "max_feret (mm)",
                            "scales": {
                                group: (2 ** ooids_size_min_scales_log2[i], 2 ** ooids_size_min_scales_log2[i + 1])
                                for i, group in enumerate(ooids_size_classes)
                            },
                        },
                        supergroups=ooids_rock_type,
                    )

            if args.netcdf:
                instance_seg_files = {"Pores": pore_instance_seg_file_path}
                if not args.exclude_ooids:
                    instance_seg_files.update({"Ooids": ooid_seg_file_path})

                netcdf_exporter.run(loaded_image_file_path, instance_seg_files)

            if not args.keep_temp:
                delete_tmp_nrrds(tmp_dir)
            else:
                os.remove(loaded_image_file_path)  # remover de qualquer jeito para preservar armazenamento

        if args.export_las:
            image_names = []
            if pores_output_dir:
                image_names = [
                    os.path.basename(d)
                    for d in glob.glob(os.path.join(pores_output_dir, "*"))
                    if os.path.basename(d) != "LAS"
                ]

            las_exporter.run(image_names, sheet_exporter.stats_sheet_prefix, pores_output_dir.as_posix())
            if not args.exclude_ooids:
                las_exporter.run(
                    image_names, sheet_exporter.stats_sheet_prefix, ooids_output_dir.as_posix(), instance_type="ooids"
                )

            if sheet_exporter.temporary:
                if args.export_images:
                    sheets_files = glob.glob(
                        os.path.join(args.output_dir, "*", "*", f"{sheet_exporter.stats_sheet_prefix}*.xlsx")
                    )
                    for sheet_file in sheets_files:
                        os.remove(sheet_file)
                else:
                    image_dirs = []
                    for image_name in image_names:
                        image_dirs += glob.glob(os.path.join(args.output_dir, "*", image_name))
                    for image_dir in image_dirs:
                        shutil.rmtree(image_dir)

        checkpoint_path.unlink(missing_ok=True)
    except Exception as e:
        raise e
    finally:
        if not args.keep_temp and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        print("Done.")


if __name__ == "__main__":

    def max_frags_validator(value):
        if value in ["custom", "all"]:
            return value

        try:
            value = int(value)
            if value <= 0:
                raise argparse.ArgumentTypeError(f"--max-frags must be a positive number. Got {value}.")
            return value
        except ValueError:
            try:
                value = float(value)  # apenas para não mostrar float como str na mensagem de erro.
            except ValueError:
                pass
            finally:
                raise argparse.ArgumentTypeError(
                    f"--max-frags must be one of 'custom', 'all' or an integer value. Got {value} ({type(value)})."
                )

    parser = argparse.ArgumentParser(
        description="Calculate pore and ooids statistics for a set of thin section images.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # para mostrar os valores default na mensagem de ajuda (--help)
    )
    parser.add_argument("input_dir", type=str, help="Path of the input directory containing thin section images.")
    parser.add_argument(
        "output_dir",
        type=str,
        help="Path of the output directory of the final results (prediction images, .LAS files and .csv tables).",
    )
    parser.add_argument(
        "-a",
        "--algorithm",
        choices=["watershed", "islands"],
        default="islands",
        help="Algorithm to split the detected pores. Choose between 'islands' and 'watershed'.",
    )
    parser.add_argument("-ps", "--pixel-size", type=float, default=1.0, help="Pixel size in millimeters.")
    parser.add_argument(
        "-ms",
        "--min-size",
        type=float,
        default=0.0,
        help="Minimum value (mm) of the major axis size (maximum Feret diameter) of a detected pore not to be discarded.",
    )
    parser.add_argument(
        "-s",
        "--sigma",
        type=float,
        default=1.0,
        help="Standard deviation of the Gaussian filter applied to the distance transform that precedes splitting the pores. \
                            Ignored if --algorithm is 'islands'.",
    )
    parser.add_argument(
        "-d",
        "--min-distance",
        type=float,
        default=5.0,
        help="Minimum distance (pixels) which separate distinct pore segment peaks. \
                            Ignored if --algorithm is 'islands'.",
    )
    parser.add_argument(
        "-pm",
        "--pore-model",
        type=str,
        default="unet",
        help="Model to use for the binary pore segmentation. Choose between 'unet' (U-Net), 'sbayes' ([bayes]ian model with [s]mall kernel) and \
                            'bbayes' ([bayes]ian model with [b]ig kernel) for automatic inferring of the trained model to use, or provide the model's path directly \
                            (recommended if using deployed versions of GeoSlicer).",
    )
    parser.add_argument(
        "-mf",
        "--max-frags",
        type=max_frags_validator,
        default="custom",
        help="Limit the maximum number of rock fragments to be analyzed, from largest to smallest. If it is an integer value, the specified number of \
                            fragments is analyzed. If 'all', every fragment is considered. If 'custom', each image listed in the file 'filter_images.csv' have \
                                its maximum number of fragments considered based on the corresponding value specified in the file (0 skips the image), while the \
                                    non-listed images have every fragment considered.",
    )
    parser.add_argument(
        "-nc", "--netcdf", action="store_true", help="Save NetCDF file containing the image and the predicted segments."
    )
    parser.add_argument(
        "-ks", "--keep-spurious", action="store_true", help="If provided, spurious predictions are not removed."
    )
    parser.add_argument(
        "-kr",
        "--keep-residues",
        action="store_true",
        help="If provided, bubbles and residues in pore resin are not cleaned.",
    )
    parser.add_argument(
        "-px",
        "--use-px",
        choices=["none", "custom", "all"],
        default="custom",
        help="Whether to use PX images to aid pore resin cleaning. If 'none', only PP will be used. If 'all', PX will be also used in every case. \
                            If 'custom', images listed in the file 'not_use_px.csv' will not have PX used. Ignored if --keep-residues.",
    )
    parser.add_argument(
        "-reg",
        "--reg-method",
        choices=["centralized", "auto"],
        default="centralized",
        help="Method for registrating PP and PX images for pore resin cleaning. If 'centralized', the images will be overlapped so that each one's \
                            center will share the same location: recommended when the images seem to be naturally registered already. If 'auto', the algorithm will decide \
                                between just centralizing the images (as 'centralized') or cropping their rock region before: recommended when PP and PX have different \
                                    dimensions or do not seem to overlap naturally. Ignored if --keep-residues.",
    )
    parser.add_argument(
        "-ni",
        "--no-images",
        dest="export_images",
        action="store_false",
        help="If provided, do not save the PNG images showing the predicted instances.",
    )
    parser.add_argument(
        "-ns",
        "--no-sheets",
        dest="export_sheets",
        action="store_false",
        help="If provided: if --no-las is provided, do not save the sheets with the predictions properties. \
                            Otherwise, save temporary auxiliar sheets that are deleted after LAS files are saved.",
    )
    parser.add_argument(
        "-nl",
        "--no-las",
        dest="export_las",
        action="store_false",
        help="If provided, do not save the LAS files with statistics of the predictions properties.",
    )
    parser.add_argument(
        "-sc",
        "--seg-cli",
        type=str,
        default=None,
        help="Path to the pore segmentation CLI to use. Must be provided for deployed versions of GeoSlicer. For release versions, it is recommended \
                        not to be provided, so it will be inferred automatically.",
    )
    parser.add_argument(
        "-fc",
        "--foreground-cli",
        type=str,
        default=None,
        help="Path to the foreground segmenter CLI to use. Must be provided for deployed versions of GeoSlicer. For release versions, it is recommended \
                        not to be provided, so it will be inferred automatically.",
    )
    parser.add_argument(
        "-rc",
        "--remove-spurious-cli",
        type=str,
        default=None,
        help="Path to the spurious pores remover CLI to use. Must be provided for deployed versions of GeoSlicer. For release versions, it is recommended \
                        not to be provided, so it will be inferred automatically.",
    )
    parser.add_argument(
        "-cc",
        "--clean-resin-cli",
        type=str,
        default=None,
        help="Path to the resin cleaner CLI to use. Must be provided for deployed versions of GeoSlicer. For release versions, it is recommended \
                        not to be provided, so it will be inferred automatically.",
    )
    parser.add_argument(
        "-ic",
        "--inspector-cli",
        type=str,
        default=None,
        help="Path to the segment inspector CLI to use. Must be provided for deployed versions of GeoSlicer. For release versions, it is recommended \
                        not to be provided, so it will be inferred automatically.",
    )
    parser.add_argument(
        "--resize", action="store_true", help="Resize image to 10%% its original size (for debugging purposes)."
    )
    parser.add_argument(
        "--keep-temp", action="store_true", help="Do not delete temporary files (for debugging purposes)."
    )
    parser.add_argument(
        "--save-unclean-resin",
        action="store_true",
        help="Save NRRD file with spurious pores removed but resin not yet clean (for debugging purposes).",
    )
    parser.add_argument(
        "--exclude-ooids", action="store_true", help="Do not calculate ooids statistics (for debugging purposes)."
    )
    parser.add_argument(
        "--no-inspector",
        action="store_true",
        help="Use simple connectivity labeling instead of Segment Inspector for splitting instances (for debugging purposes).",
    )

    args = parser.parse_args()

    main(args)
