from ltrace.slicer.helpers import resizeNdimArray


class CoreBox:
    """Class to store information related to a single Core box image."""

    def __init__(self, image_array, box_number, core_id, category, height, start_depth):
        self.__image_array = image_array
        self.__box_number = box_number
        self.__core_id = core_id
        self.__category = category
        self.__height = height
        self.__start_depth = start_depth

    def pixels_height(self):
        return self.array.shape[0]

    def pixels_width(self):
        return self.array.shape[1]

    def spacing(self):
        return self.__height / self.pixels_height()

    @property
    def array(self):
        return self.__image_array

    @property
    def box_number(self):
        return self.__box_number

    @property
    def core_id(self):
        return self.__core_id

    @property
    def category(self):
        return self.__category

    @property
    def height(self):
        return self.__height

    @property
    def start_depth(self):
        return self.__start_depth

    @property
    def end_depth(self):
        return self.__start_depth + self.__height

    @height.setter
    def height(self, new_height):
        self.__height = new_height

    def resize(self, height, width):
        print("core box resizing")
        self.__image_array = resizeNdimArray(image=self.__image_array, new_height=height, new_width=width)

    def resize_vertical_spacing(self, spacing):
        scale = self.spacing() / spacing
        new_height = round(scale * self.pixels_height())
        new_width = round(self.pixels_width())
        self.__image_array = resizeNdimArray(image=self.__image_array, new_height=new_height, new_width=new_width)

    def resize_horizontal(self, width):
        new_height = self.pixels_height()
        self.__image_array = resizeNdimArray(image=self.__image_array, new_height=new_height, new_width=width)
