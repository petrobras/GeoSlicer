---
name: gs-exec
description: Executes Python code inside a running GeoSlicer instance for Digital Rock Analysis. Use this to manipulate the 3D scene, process volumetric data, or extract node information via the Web Server API.
compatibility: Requires a running instance of GeoSlicer with the Web Server enabled.
---

# GeoSlicer Remote Execution

Run arbitrary Python code inside **GeoSlicer** via its HTTP Web Server module.

## Workflow

**Avoid editing project source files directly to test behavior.** Always prototype first:

1. Write a throwaway script to `agent_tmp/` (project root).
2. Run it with `gs.py exec` to verify behavior inside GeoSlicer.
3. Only after it works, apply changes to the actual source files.

`agent_tmp/` is the designated scratch space for agent-generated scripts.

When you do edit source files, you must `gs.py restart` for changes to take effect.

## Usage

All commands go through the unified CLI:

```bash
python .claude/skills/gs-exec/scripts/gs.py [--port PORT] <command> [args]
```

`--port` defaults to `2016`. All exec examples below run with:
```bash
python .claude/skills/gs-exec/scripts/gs.py exec agent_tmp/<file>.py
```

### Commands

```bash
gs.py exec agent_tmp/my_script.py          # run a script
gs.py run-tests [--timeout SECS] [FILTER]  # run integration tests
gs.py status                                # show buffered output and state
gs.py cancel                               # request cancellation
gs.py restart [--timeout 120] [--interval 3]
```

## Exec Examples

**Check version:**
```python
import slicer
print(f'GeoSlicer Version: {slicer.app.applicationVersion}')
```

**List loaded volumes:**
```python
import slicer
nodes = slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')
print([n.GetName() for n in nodes])
```

## Integration Tests

`run-tests` blocks until complete, then prints all captured output (stdout is buffered).

If the test is taking too long, use the status command to check partial output.

```bash
python .claude/skills/gs-exec/scripts/gs.py run-tests                      # all tests
python .claude/skills/gs-exec/scripts/gs.py run-tests NetCDFTest            # whole suite
python .claude/skills/gs-exec/scripts/gs.py run-tests NetCDFTest:test_import,test_export
python .claude/skills/gs-exec/scripts/gs.py run-tests SuiteA SuiteB:test_foo
```

Filter syntax: `"SuiteName"` or `"SuiteName:test_foo,test_bar"`.

`--timeout SECONDS` sets HTTP timeout (default 1800 s). On timeout or Ctrl-C the test keeps running server-side; use `status`/`cancel` to recover.

`status` exit code: `0` = SUCCEED, `1` = FAILED/ERROR, `2` = still running.

A `[...]` in the output means "this line has appeared too many times and will be omitted from the file from now on".

### List available tests

`list_tests()` returns `{"suites": [{"name": "SuiteName", "cases": ["test_foo", ...]}]}`. The full list is large; filter by name:

```python
from ltrace.slicer.tests.api import list_tests
import json
result = list_tests()
suite_name = "MyTest"  # change this
matches = [s for s in result["suites"] if suite_name in s["name"]]
print(json.dumps(matches, indent=2))
```

## Enabling Faulthandler

For debugging hard crashes, enable Python's faulthandler to write crash tracebacks to a file. This slows GeoSlicer down, so only enable it when needed.

```python
from ltrace.slicer.tests.api import enable_faulthandler
import json
print(json.dumps(enable_faulthandler()))
```

After a crash, read `agent_tmp/faulthandler.log` for the traceback.

## Error Handling

**Connection error** — GeoSlicer is not running or the Web Server is inactive. Ask the user to start GeoSlicer and enable the Web Server module on port 2016. In developer mode the WebServer auto-starts.

**403 Forbidden** — The "Slicer API exec" option is disabled. Ask the user to enable it in the Web Server settings.
