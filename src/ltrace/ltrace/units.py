import pint
import locale as loc

global_unit_registry = pint.UnitRegistry()

SLICER_LENGTH_UNIT = global_unit_registry.millimeter


def convert_to_global_registry(quantity):
    return global_unit_registry.Quantity.from_tuple(quantity.to_tuple())


def safe_atof(number, locale="pt_BR"):
    try:
        clean_number = number.strip(", .%$")
        current_locale = loc.getlocale(loc.LC_NUMERIC)
        loc.setlocale(loc.LC_NUMERIC, locale)
        value = loc.atof(clean_number)
        return value
    except Exception as e:
        return None
    finally:
        loc.setlocale(loc.LC_NUMERIC, current_locale)
