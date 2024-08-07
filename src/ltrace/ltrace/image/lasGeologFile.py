# Imports to customize LASFile.write
from lasio.las import *
import lasio

# Imports to customize lasio.writer
import logging
import textwrap

import numpy as np

from copy import deepcopy

from lasio.las_items import HeaderItem, CurveItem, SectionItems, OrderedDict
from lasio import defaults
from lasio import exceptions

logger = logging.getLogger(__name__)


# Inherits LASFile so we call lasGeologWrite
class lasGeologFile(lasio.las.LASFile):
    def write(self, file_ref, **kwargs):
        opened_file = False
        if isinstance(file_ref, basestring) and not hasattr(file_ref, "write"):
            opened_file = True
            file_ref = open(file_ref, "w")
        lasGeoLogWrite(self, file_ref, **kwargs)
        if opened_file:
            file_ref.close()


# Custom lasio.writer.write
# It's mostly duplicated code from the original lasio, but may be the base for a full LAS 3.0 support
# Changes:
# - Accepts value 3 as version argument
# - When value==3:
#   - VERS header item is written as 3
#   - Parameter section string is "~Parameter " (instead of 2.0 "~Params ")
# From the LAS 3.0 spec, the indication that a curve is 2-D is made via specific strings in the mnemonics names and descritptions.
# These are set in the src/ltrace/image/las.py, but in the future they may be set here
#   - Specifically, the mnemonics have to have an index surrounded by []'s appended to their names,
#   and their description string (which is surrounded by {}'s) has to start with "AF" (array of floats)
def lasGeoLogWrite(
    las,
    file_object,
    version=None,
    wrap=None,
    STRT=None,
    STOP=None,
    STEP=None,
    fmt="%.5f",
    column_fmt=None,
    len_numeric_field=None,
    lhs_spacer=" ",
    spacer=" ",
    data_width=79,
    header_width=60,
    data_section_header="~ASCII",
    mnemonics_header=False,
):
    """Write a LAS files.

    Arguments:
        las (:class:`lasio.LASFile`)
        file_object (file-like object open for writing): output
        version (float or None): version of written file, either 1.2 or 2.
            If this is None, ``las.version.VERS.value`` will be used.
        wrap (bool or None): whether to wrap the output data section.
            If this is None, ``las.version.WRAP.value`` will be used.
        STRT (float or None): value to use as STRT (note the data will not
            be clipped). If this is None, the data value in the first column,
            first row will be used.
        STOP (float or None): value to use as STOP (note the data will not
            be clipped). If this is None, the data value in the first column,
            last row will be used.
        STEP (float or None): value to use as STEP (note the data will not
            be resampled and/or interpolated). If this is None, the STEP will
            be estimated from the first two rows of the first column.
        fmt (str): Python string formatting operator for numeric data to be
            used.
        column_fmt (dict or None): use this to set a different format string
            for specific columns from the data ndarray. E.g. to use ``'%.3f'``
            for the depth column and ``'%.2f'`` for all the other columns,
            you would use ``fmt='%.2f', column_fmt={0: '%.3f'}``.
        len_numeric_field (int): width of each numeric field column (must be
            greater than than all the formatted numeric values in the file).
            If it is None, the maximum necessary value will be used automatically
            (i.e. all columns will have the same width). If it is -1, then
            the columns will not have consistent widths. You can combine
            -1 with the *fmt* keyword argument to control column widths closely.
        data_width (79): width of data field in characters
        lhs_spacer (str): string which goes on left hand side of data
            section - by default it is `" "`.
        spacer (str): string which goes between each column of the data section
        data_section_header (str): default "~ASCII"
        mnemonics_header (bool): include mnemonic curve names in the
            data_section_header at the top of data section

    Creating an output file is not the only side-effect of this function. It
    will also modify the STRT, STOP and STEP HeaderItems so that they correctly
    reflect the ~Data section's units and the actual first, last, and interval
    values.

    However, passing a version to this write() function only changes the version
    of the object written to. Example: las.write(myfile, version=2).
    Lasio's internal-las-object version will remain separate and defined by
    las.version.VERS.value

    You should avoid calling this function directly - instead use the
    :meth:`lasio.LASFile.write` method.

    """
    if column_fmt is None:
        column_fmt = {}
    if wrap is None:
        wrap = las.version["WRAP"] == "YES"
    elif wrap is True:
        las.version["WRAP"] = HeaderItem("WRAP", "", "YES", "Multiple lines per depth step")
    elif wrap is False:
        las.version["WRAP"] = HeaderItem("WRAP", "", "NO", "One line per depth step")
    lines = []

    version_section_to_write = deepcopy(las.version)

    assert version in (1.2, 2, 3, None)
    if version is None:
        version = las.version["VERS"].value
    if version == 1.2:
        version_section_to_write.VERS = HeaderItem("VERS", "", 1.2, "CWLS LOG ASCII STANDARD - VERSION 1.2")
    elif int(version) == 2:
        version_section_to_write.VERS = HeaderItem("VERS", "", 2.0, "CWLS log ASCII Standard - VERSION 2.0")
    elif int(version) == 3:
        version_section_to_write.VERS = HeaderItem("VERS", "", 3.0, "CWLS log ASCII Standard - VERSION 3.0")

    # -------------------------------------------------------------------------
    # If an initial curve index was not read from a las file (las.index_initial)
    # or the curve index has changed during processing
    # or if the STOP value doesn't match the final index value
    # then update the step variables before writing to a new las file object.
    # -------------------------------------------------------------------------
    index_changed = False
    stop_is_different = False

    if las.index_initial is not None:
        index_changed = not np.array_equal(las.index_initial, las.index)
        stop_is_different = las.index_initial[-1] != las.well.STOP.value
    else:
        index_changed = True

    if index_changed or stop_is_different:
        las.update_start_stop_step(STRT, STOP, STEP)

    las.update_units_from_index_curve()

    # Write each section.
    # get_formatter_function ( ** get_section_widths )

    # ~Version
    logger.debug("LASFile.write Version section, Version: %s" % (version))
    lines.append("~Version ".ljust(header_width, "-"))
    order_func = lasio.writer.get_section_order_function("Version", version)
    section_widths = lasio.writer.get_section_widths("Version", version_section_to_write, version, order_func)
    for header_item in version_section_to_write.values():
        mnemonic = header_item.original_mnemonic
        # logger.debug('LASFile.write ' + str(header_item))
        order = order_func(mnemonic)
        # logger.debug('LASFile.write order = %s' % (order, ))
        logger.debug("LASFile.write %s order=%s section_widths=%s" % (header_item, order, section_widths))
        formatter_func = lasio.writer.get_formatter_function(order, **section_widths)
        line = formatter_func(header_item)
        lines.append(line)

    # ~Well
    logger.debug("LASFile.write Well section")
    lines.append("~Well ".ljust(header_width, "-"))
    order_func = lasio.writer.get_section_order_function("Well", version)
    section_widths = lasio.writer.get_section_widths("Well", las.well, version, order_func)
    # logger.debug('LASFile.write well section_widths=%s' % section_widths)
    for header_item in las.well.values():
        header_item.value = lasio.writer.standardize_value(header_item.value, header_item.unit)
        mnemonic = header_item.original_mnemonic
        order = order_func(mnemonic)
        logger.debug("LASFile.write %s order=%s section_widths=%s" % (header_item, order, section_widths))
        formatter_func = lasio.writer.get_formatter_function(order, **section_widths)
        line = formatter_func(header_item)
        lines.append(line)

    # ~Curves
    logger.debug("LASFile.write Curves section")
    lines.append("~Curve Information ".ljust(header_width, "-"))
    order_func = lasio.writer.get_section_order_function("Curves", version)
    section_widths = lasio.writer.get_section_widths("Curves", las.curves, version, order_func)
    for header_item in las.curves:
        mnemonic = header_item.original_mnemonic
        order = order_func(mnemonic)
        formatter_func = lasio.writer.get_formatter_function(order, **section_widths)
        line = formatter_func(header_item)
        lines.append(line)

    # ~Params
    logger.debug("LASFile.write Params section")
    parameter_section_header = "~Parameter " if int(version) == 3 else "~Params "
    lines.append(parameter_section_header.ljust(header_width, "-"))
    order_func = lasio.writer.get_section_order_function("Parameter", version)
    section_widths = lasio.writer.get_section_widths("Parameter", las.params, version, order_func)
    for header_item in las.params.values():
        header_item.value = lasio.writer.standardize_value(header_item.value, header_item.unit)
        mnemonic = header_item.original_mnemonic
        order = order_func(mnemonic)
        formatter_func = lasio.writer.get_formatter_function(order, **section_widths)
        line = formatter_func(header_item)
        lines.append(line)

    # ~Other
    logger.debug("LASFile.write Other section")
    lines.append("~Other ".ljust(header_width, "-"))
    lines += las.other.splitlines()

    logger.debug("LASFile.write ASCII section")

    file_object.write("\n".join(lines))
    file_object.write("\n")
    line_counter = len(lines)

    # Set empty defaults for nrows and ncols
    nrows, ncols = (0, 0)

    # data_arr = np.column_stack([c.data for c in las.curves])
    try:
        data_arr = las.data
        nrows, ncols = data_arr.shape
        logger.debug("Data section shape: {}".format((nrows, ncols)))
    except ValueError as err:
        logger.debug("Data section is empty")

    logger.debug("len_numeric_field = {}".format(len_numeric_field))
    if len_numeric_field is None:
        logger.debug("Calculating len_numeric_field. fmt = {}".format(fmt))
        len_numeric_field = 10
        test_fmt = fmt % np.pi
        while len(test_fmt) > (len_numeric_field - 1):
            logger.debug("test_fmt = {}".format(test_fmt))
            len_numeric_field += 1

    def format_data_section_line(n, fmt, l=len_numeric_field, spacing_chars=" "):
        try:
            if np.isnan(n):
                value = str(las.well["NULL"].value)
            else:
                value = fmt % n
        except TypeError:
            value = str(n)

        if l != -1:
            result = value.rjust(l)
        else:
            result = value
        return spacing_chars + result

    def get_column_fmt(j):
        """Get format string for column *j*."""
        if j in column_fmt:
            return column_fmt[j]
        else:
            return fmt

    def get_left_spacing(j):
        """Get left-hand-side spacing for column *j*."""
        if j == 0:
            left_spacing = lhs_spacer
        else:
            left_spacing = spacer
        return left_spacing

    # Place curve mnemonics in the "~A" line.
    if mnemonics_header:
        # Calculate width of numeric values from the first line,
        header_col_widths = []
        for col_idx in range(ncols):
            col_fmt = get_column_fmt(col_idx)
            left_spacing = get_left_spacing(col_idx)
            data_value = format_data_section_line(data_arr[0, col_idx], col_fmt, spacing_chars=left_spacing)
            header_col_widths.append(len(data_value))

        # Construct mnemonics for header line.
        header_values = []
        for j, curve in enumerate(las.curves):
            col_width = header_col_widths[j]
            if len(curve.mnemonic) > (col_width - 1):
                width = len(curve.mnemonic) + 1
            else:
                width = col_width
            value = curve.mnemonic.rjust(width)
            header_values.append(value)

        # Add data section header prefix
        data_section_header += " "
        if len(header_values):
            hv = header_values[0]
            for k in range(len(data_section_header)):
                if k < len(hv):
                    if hv[0] == " ":
                        hv = hv[1:]
            header_values = [hv] + header_values[1:]

        file_object.write(data_section_header + "".join(header_values) + "\n")
    else:
        file_object.write((data_section_header + " ").ljust(header_width, "-") + "\n")

    twrapper = textwrap.TextWrapper(width=data_width)

    for i in range(nrows):
        logger.debug("Writing data array row {} of {}".format(i + 1, nrows))
        depth_slice = ""
        for j in range(ncols):
            col_fmt = get_column_fmt(j)
            left_spacing = get_left_spacing(j)
            depth_slice += format_data_section_line(data_arr[i, j], col_fmt, spacing_chars=left_spacing)

        if wrap:
            lines = twrapper.wrap(depth_slice)
            logger.debug("LASFile.write Wrapped %d lines out of %s" % (len(lines), depth_slice))
        else:
            lines = [depth_slice]

        for line in lines:
            if version_section_to_write.VERS == 1.2 and len(line) > 255:
                logger.warning("[v1.2] line #{} has {} chars (>256)".format(line_counter + 1, len(line)))
            file_object.write(line + "\n")
            line_counter += 1
