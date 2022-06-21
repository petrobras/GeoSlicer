import json
import jsonschema

from typing import Union, Dict

from ltrace.slicer.equations.line_equation import LineEquation
from ltrace.slicer.equations.timur_coates_equation import TimurCoatesEquation

LINE_EQUATION_SCHEMA = {
    "title": "Line Equation",
    "type": "object",
    "required": ["m", "b", "x_min", "x_max"],
    "properties": {
        "m": {"type": "object"},
        "b": {"type": "object"},
        "x_min": {
            "type": "object",
        },
        "x_max": {
            "type": "object",
        },
    },
}

TIMUR_COATES_EQUATION_SCHEMA = {
    "title": "Timur Coates Equation",
    "type": "object",
    "required": ["A", "B", "C", "x_min", "x_max", "bins"],
    "properties": {
        "A": {
            "type": "object",
        },
        "B": {
            "type": "object",
        },
        "C": {
            "type": "object",
        },
        "x_min": {
            "type": "object",
        },
        "x_max": {
            "type": "object",
        },
        "bins": {
            "type": "object",
        },
    },
}


def validateSchema(data: Union[Dict, str]):
    if isinstance(data, str):
        data = json.loads(data)

    _type = data.get("Fitting equation")["0"]
    if not _type:
        raise ValueError("Missing 'Fitting equation' property")

    if _type == LineEquation.NAME:
        jsonschema.validate(instance=data, schema=LINE_EQUATION_SCHEMA)
    elif _type == TimurCoatesEquation.NAME:
        jsonschema.validate(instance=data, schema=TIMUR_COATES_EQUATION_SCHEMA)
    else:
        raise ValueError("Invalid 'Fitting equation' property")
