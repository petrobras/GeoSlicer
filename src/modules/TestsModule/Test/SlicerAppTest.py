from commons.slicer_utils import LTracePluginTest

import commons.slicer.app as slicer_app


class SlicerAppTest(LTracePluginTest):
    def test_get_application_version_dirty(self):

        jsonData = {
            "GEOSLICER_VERSION": None,
            "GEOSLICER_HASH": "cd487dc4277406fff2827bfafc6e0a5b902d705c",
            "GEOSLICER_HASH_DIRTY": "True",
            "GEOSLICER_BUILD_TIME": "2022-03-04 05:06:08.090000",
        }

        version = slicer_app.parseApplicationVersion(jsonData)
        assert version == "cd487dc4* 2022-03-04", f"Expected: 'cd487dc4* 2022-03-04', got: '{version}'"

    def test_get_application_version_release_with_revision(self):

        jsonData = {
            "GEOSLICER_VERSION": "2.4.9RC10",
            "GEOSLICER_HASH": "cd487dc4277406fff2827bfafc6e0a5b902d705c",
            "GEOSLICER_HASH_DIRTY": "True",
            "GEOSLICER_BUILD_TIME": "2022-03-04 05:06:08.090000",
        }

        version = slicer_app.parseApplicationVersion(jsonData)
        assert version == "2.4.9RC10", f"Expected: '2.4.9RC10', got: '{version}'"

    def test_get_application_version_release_without_revision(self):

        jsonData = {
            "GEOSLICER_VERSION": "2.4",
            "GEOSLICER_HASH": "cd487dc4277406fff2827bfafc6e0a5b902d705c",
            "GEOSLICER_HASH_DIRTY": "False",
            "GEOSLICER_BUILD_TIME": "2022-03-04 05:06:08.090000",
        }

        version = slicer_app.parseApplicationVersion(jsonData)
        assert version == "2.4", f"Expected: '2.4', got: '{version}'"
