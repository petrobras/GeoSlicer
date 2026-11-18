"""The diagnostics detail level: the parameter definition and the per subprocess gate."""

import pytest

from commons.pore_networks.pnflow_parameter_defs import (
    DIAGNOSTICS_BASIC,
    DIAGNOSTICS_COMPLETE,
    DIAGNOSTICS_OFF,
    PARAMETERS,
    diagnostics_level,
    without_diagnostics,
)


class TestParameterDefinition:
    def test_the_level_is_a_combobox_with_the_three_levels(self):
        definition = PARAMETERS["diagnostics_level"]

        assert definition["dtype"] == "combobox"
        assert list(definition["display_names"].values()) == [
            DIAGNOSTICS_OFF,
            DIAGNOSTICS_BASIC,
            DIAGNOSTICS_COMPLETE,
        ]
        # an index into display_names: diagnostics are opt in
        assert definition["default_value"] == 0
        assert definition["layout"] == "options"

    def test_the_old_checkbox_is_gone(self):
        assert "generate_diagnostics" not in PARAMETERS


class TestLevelLookup:
    def test_a_params_dict_without_the_key_is_off(self):
        assert diagnostics_level({"create_sequence": "F"}) == DIAGNOSTICS_OFF

    @pytest.mark.parametrize("level", [DIAGNOSTICS_OFF, DIAGNOSTICS_BASIC, DIAGNOSTICS_COMPLETE])
    def test_the_stored_level_is_returned(self, level):
        assert diagnostics_level({"diagnostics_level": level}) == level


class TestSubprocessGate:
    """Only the first simulation of a sensitivity run keeps its diagnostics."""

    @pytest.mark.parametrize("level", [DIAGNOSTICS_BASIC, DIAGNOSTICS_COMPLETE])
    def test_diagnostics_are_disabled_for_the_other_subprocesses(self, level):
        params = {"diagnostics_level": level, "create_sequence": "F"}

        gated = without_diagnostics(params)

        assert gated["diagnostics_level"] == DIAGNOSTICS_OFF
        assert gated["create_sequence"] == "F"
        # the caller's dict is left alone
        assert params["diagnostics_level"] == level

    def test_an_off_level_is_passed_through_untouched(self):
        params = {"diagnostics_level": DIAGNOSTICS_OFF}
        assert without_diagnostics(params) is params

    def test_a_params_dict_without_the_key_is_passed_through_untouched(self):
        params = {"create_sequence": "F"}
        assert without_diagnostics(params) is params
