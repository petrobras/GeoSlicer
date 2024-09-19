import os
import time
import nrrd
import numpy as np
from netCDF4 import Dataset
from workflow.commons import no_extra_dim_read


class NetCDFExporter:

    ## NetCDFExporter (Opcional): Gerador de arquivo NetCDF das segmentações

    # Gera um arquivo NetCDF contendo a imagem PP original e um labelmap para cada tipo de instância
    # (poros e oóides), em que cada instância é aleatoriamente colorida e pode ser visualizada sobre a
    # região real em que aparece na imagem.

    def __init__(self, output_dir, pixel_size):
        self.output_dir = output_dir
        self.pixel_size = pixel_size

    def _generate_random_hex_color(self):
        r = np.random.randint(0, 256)
        g = np.random.randint(0, 256)
        b = np.random.randint(0, 256)
        return "#{:02x}{:02x}{:02x}".format(r, g, b)

    def run(self, image_file_path, instance_seg_files_dict):
        image_name = os.path.splitext(os.path.basename(image_file_path))[0]

        image = no_extra_dim_read(image_file_path)

        image_name = os.path.splitext(os.path.basename(image_file_path))[0]
        output_path = os.path.join(self.output_dir, f"{image_name}.nc")

        print("Writing", output_path)
        start_time = time.time()
        with Dataset(output_path, "w") as nc:
            nc.createDimension("z", 1)
            nc.createDimension("y", image.shape[0])
            nc.createDimension("x", image.shape[1])
            nc.createDimension("c", image.shape[2])

            rgb_var = nc.createVariable(image_name, "u1", ("z", "y", "x", "c"))

            c_var = nc.createVariable("c", str, ("c",))
            z_var = nc.createVariable("z", "d", ("z",))
            y_var = nc.createVariable("y", "d", ("y",))
            x_var = nc.createVariable("x", "d", ("x",))

            rgb_var[:, :, :, :] = image.reshape(1, *image.shape)

            # spacing
            y_var[:] = np.linspace(0, self.pixel_size * (image.shape[0] - 1), image.shape[0])
            x_var[:] = np.linspace(0, self.pixel_size * (image.shape[1] - 1), image.shape[1])
            z_var[:] = [0]

            for seg_name, seg_path in instance_seg_files_dict.items():
                instance_seg = nrrd.read(seg_path, index_order="C")[0][0]

                segmentation_var = nc.createVariable(seg_name, "i2", ("z", "y", "x"))
                segmentation_var[:, :, :] = instance_seg.reshape(1, *instance_seg.shape)

                segmentation_var.type = "labelmap"
                segmentation_var.labels = ["Name,Index,Color"] + [
                    f"Segment_{i},{i},{self._generate_random_hex_color()}" for i in range(1, instance_seg.max() + 1)
                ]
                segmentation_var.reference = image_name
        print(f"Done ({time.time() - start_time}s).")
