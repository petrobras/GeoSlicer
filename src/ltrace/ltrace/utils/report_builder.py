import base64
import os

import cv2
from jinja2 import Environment, FileSystemLoader


class ReportBuilder:
    def __init__(self, template_file_path):
        directory_path = os.path.dirname(str(template_file_path))
        template_file_name = os.path.basename(str(template_file_path))

        file_loader = FileSystemLoader(directory_path)
        environment = Environment(loader=file_loader)
        self.template = environment.get_template(template_file_name)

        self.variables = {}

    def add_variable(self, variable_name, variable):
        self._add_data_to_variables(variable_name, variable)

    def add_image_file(self, variable_name, image_file_path):
        self._add_data_to_variables(variable_name, self.encode_image_by_path(image_file_path))

    def add_image_data(self, variable_name, image_array_data):
        self._add_data_to_variables(variable_name, self.encode_image_by_variable(image_array_data))

    def generate(self, output_file_path):
        self.template.stream(self.variables).dump(str(output_file_path))

    @staticmethod
    def encode_image_by_variable(image):
        _, buffer = cv2.imencode(".png", image)
        encodedImage = base64.b64encode(buffer)
        return encodedImage.decode("utf-8")

    @staticmethod
    def encode_image_by_path(path):
        with open(path, "rb") as imageFile:
            encodedImage = base64.b64encode(imageFile.read())
        return encodedImage.decode("utf-8")

    def _add_data_to_variables(self, variable_name, data):
        self._add_data_to_dict(self.variables, variable_name.split("."), data)

    def _add_data_to_dict(self, dictionary, keys, data):
        if len(keys) > 1:
            if keys[0] not in dictionary:
                dictionary[keys[0]] = {}
            self._add_data_to_dict(dictionary[keys[0]], keys[1:], data)
        else:
            dictionary[keys[0]] = data
