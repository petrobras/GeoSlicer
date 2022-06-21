# Defined according to https://docs.google.com/document/d/13Bz1qkKZuXUjDye6a2I_pz7mG8nQeGJTy234zPl_z2I

from ltrace.units import global_unit_registry as ureg


class PetrobrasRawFileName:
    def __init__(self, raw_file_name):
        self.file_name_parts = []
        self.valid = False

        self.well = None
        self.sample = None
        self.state = None
        self.type = None
        self.data_type = None
        self.nx = None
        self.ny = None
        self.nz = None
        self.resolution = None

        self.parse(raw_file_name)

    def parse(self, raw_file_name):
        try:
            self.file_name_parts = raw_file_name.split("_")

            self.valid = len(self.file_name_parts) == 9

            self.well = self.file_name_parts[0]
            self.sample = self.file_name_parts[1]
            self.state = self.file_name_parts[2]
            self.type = self.file_name_parts[3]
            self.data_type = self.file_name_parts[4]
            self.nx = self.file_name_parts[5]
            self.ny = self.file_name_parts[6]
            self.nz = self.file_name_parts[7]
            self.resolution = ureg.Quantity(self.file_name_parts[8])
        except:
            pass  # if there is any problem resolving the filename string
