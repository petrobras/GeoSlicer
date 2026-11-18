"""The part of the execution section that has no Qt in it: what is stored, and what a run is told."""

from commons.remote.backends import BACKEND_AUTO, BACKEND_LOCAL, BACKEND_REMOTE
from commons.slicer.widget.execution.options import (
    INT,
    LIST,
    LOCAL_FIELDS,
    MAP,
    REMOTE_FIELDS,
    ExecutionOptions,
    ExecutionSettings,
    Field,
    fields_for,
    format_value,
    parse_value,
    with_defaults,
)


class FakeSettings:
    """A settings file as far as this widget is concerned: strings in, strings out."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = 0

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced += 1


def field(key, kind, **kwargs):
    return Field(key=key, label=key, kind=kind, **kwargs)


class TestValues:
    def test_a_list_survives_a_round_trip(self):
        assert parse_value(LIST, format_value(LIST, ["openmpi", "apptainer"])) == ["openmpi", "apptainer"]

    def test_a_map_survives_a_round_trip(self):
        env = {"OMP_NUM_THREADS": "4", "LBPM_DEBUG": "1"}
        assert parse_value(MAP, format_value(MAP, env)) == env

    def test_empty_falls_back_to_the_default_of_the_kind(self):
        assert parse_value(LIST, None) == []
        assert parse_value(MAP, "") == {}
        assert parse_value("text", None) == ""
        assert parse_value(INT, None, default=1) == 1

    def test_a_malformed_line_is_dropped_rather_than_raising(self):
        assert parse_value(MAP, "NAME=value\nnonsense\n=orphan") == {"NAME": "value"}


class TestExecutionSettings:
    def test_a_shared_field_goes_to_the_key_it_already_had(self):
        settings = FakeSettings()
        store = ExecutionSettings("LBPM", aliases={"binary": "LBPM/BinaryPath"}, settings=settings)
        binary = field("binary", "path", shared=True)

        store.setValue("atena", binary, "/opt/lbpm.sif")

        assert settings.values == {"LBPM/BinaryPath": "/opt/lbpm.sif"}
        assert store.value("this computer", binary) == "/opt/lbpm.sif", "shared means shared by every backend"

    def test_a_shared_field_without_an_alias_still_lands_under_the_tool(self):
        store = ExecutionSettings("LBPM", settings=FakeSettings())
        assert store.key("atena", field("binary", "path", shared=True)) == "LBPM/binary"

    def test_the_rest_is_kept_once_per_backend(self):
        settings = FakeSettings()
        store = ExecutionSettings("LBPM", settings=settings)
        modules = field("modules", LIST)

        store.setValue("atena", modules, ["openmpi"])
        store.setValue("this computer", modules, [])

        assert settings.values["LBPM/Execution/atena/modules"] == "openmpi"
        assert store.value("atena", modules) == ["openmpi"]
        assert store.value("this computer", modules) == []

    def test_a_backend_named_like_a_path_does_not_open_a_subkey(self):
        store = ExecutionSettings("LBPM", settings=FakeSettings())
        assert store.key("cluster/gpu", field("account", "text")) == "LBPM/Execution/cluster_gpu/account"

    def test_update_writes_only_what_it_was_given_and_syncs(self):
        settings = FakeSettings()
        store = ExecutionSettings("LBPM", settings=settings)
        fields = (field("account", "text"), field("walltime", "text"))

        store.update("atena", fields, {"account": "geo", "unknown": "ignored"})

        assert settings.values == {"LBPM/Execution/atena/account": "geo"}
        assert settings.synced == 1

    def test_values_reads_every_field_of_a_backend(self):
        store = ExecutionSettings("LBPM", settings=FakeSettings({"LBPM/Execution/atena/nodes": "3"}))
        values = store.values("atena", REMOTE_FIELDS)

        assert values["nodes"] == 3
        assert values["partition"] == ""
        assert values["modules"] == []


class TestExecutionOptions:
    def test_compose_keeps_the_settings_it_recognises(self):
        options = ExecutionOptions.compose(
            kind=BACKEND_REMOTE,
            target="atena",
            ranks=16,
            gpu=True,
            values={"nodes": 2, "walltime": "1-00:00:00", "tool_specific": "left alone"},
        )

        assert (options.kind, options.target, options.ranks, options.gpu) == (BACKEND_REMOTE, "atena", 16, True)
        assert (options.nodes, options.walltime) == (2, "1-00:00:00")
        assert not hasattr(options, "tool_specific")

    def test_compose_cannot_be_talked_out_of_the_chosen_backend(self):
        options = ExecutionOptions.compose(
            kind=BACKEND_LOCAL, target=None, ranks=1, gpu=False, values={"kind": "remote", "target": "atena"}
        )
        assert (options.kind, options.target) == (BACKEND_LOCAL, None)

    def test_kwargs_leave_out_what_was_not_answered(self):
        kwargs = ExecutionOptions(kind=BACKEND_AUTO, ranks=8).asKwargs()

        assert kwargs["backend"] == BACKEND_AUTO
        assert kwargs["target_name"] is None
        # Empty is not an answer: the dispatcher's own fallbacks have to stay reachable.
        assert kwargs["walltime"] is None and kwargs["partition"] is None and kwargs["account"] is None
        assert kwargs["nodes"] == 1
        assert kwargs["modules"] == [] and kwargs["env"] == {}

    def test_kwargs_do_not_carry_what_belongs_to_an_installation(self):
        kwargs = ExecutionOptions(binary="/opt/lbpm.sif", remote_root="/nethome/drp").asKwargs()
        assert "binary" not in kwargs and "remote_root" not in kwargs

    def test_each_backend_is_asked_only_what_applies_to_it(self):
        local = {item.key for item in fields_for(BACKEND_LOCAL)}
        remote = {item.key for item in fields_for(BACKEND_REMOTE)}

        assert "binary" in local and "walltime" not in local
        assert {"walltime", "partition", "account", "nodes"} <= remote
        assert local == {item.key for item in LOCAL_FIELDS}


class TestPerModuleDefaults:
    def test_a_module_can_change_what_a_field_falls_back_to(self):
        fields = with_defaults(REMOTE_FIELDS, {"partition": "gpu", "nodes": 2})
        defaults = {item.key: item.default for item in fields}

        assert defaults["partition"] == "gpu"
        assert defaults["nodes"] == 2
        assert defaults["account"] is None, "a field nobody overrode keeps what it was declared with"

    def test_the_declared_fields_are_left_alone_for_everyone_else(self):
        with_defaults(REMOTE_FIELDS, {"partition": "gpu"})
        assert {item.key: item.default for item in REMOTE_FIELDS}["partition"] is None

    def test_a_default_is_only_what_applies_until_the_backend_has_an_answer(self):
        fields = with_defaults(REMOTE_FIELDS, {"partition": "gpu"})
        store = ExecutionSettings("LBPM", settings=FakeSettings())
        partition = next(item for item in fields if item.key == "partition")

        assert store.value("atena", partition) == "gpu"

        store.setValue("atena", partition, "cpu-large")
        assert store.value("atena", partition) == "cpu-large", "a stored answer wins over a default"
