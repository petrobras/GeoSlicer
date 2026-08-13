"""
Standalone fuzzer for the Interactive Segmenter module.

Drives the real module widget the way a person would -- random inputs, random
actions, realistic timing -- and runs until a traceback shows up. It touches
nothing in the module itself: it only clicks the public widgets, writes
annotation labelmaps (the same data path real painting feeds), nudges and
reorients the slice views (XY/XZ/YZ via the module combo, via the slice node
directly, and occasionally to an oblique plane the module is expected to
ignore), switches the layout away and back through the Resume button, and
watches several independent sinks for crashes.

USAGE (via /gs-exec, exec this file's text in the running GeoSlicer):

    exec(open(r"<path>/InteractiveSegmenter/tools/fuzz_interactive_segmenter.py").read())

It installs a QTimer-driven scheduler and returns immediately, so GeoSlicer
stays live and you can watch the side-by-side views pan, paint and re-predict in
real time. Status is printed to the console and mirrored to a JSON file (path is
printed on start).

    slicer.modules._interactive_seg_fuzzer.stop()       # stop and restore
    slicer.modules._interactive_seg_fuzzer.status()     # print a status line

Re-exec'ing the file stops any previous run first, so it is safe to relaunch.

WHY IT CAN SEE CRASHES IT DID NOT RAISE ITSELF
----------------------------------------------
Two leaks make a naive try/except useless here, so the fuzzer watches several
independent sinks and freezes on the first hit from any of them:

  1. Exceptions inside the module's QTimer slots (update_loop, _check_progress)
     are swallowed by PythonQt and only *printed* to stderr; the consumer
     subprocess likewise swallows its tracebacks into its inherited stdout.
     GeoSlicer mirrors both streams into the session log file.
     -> caught by the log-file tail.
  2. A consumer that dies surfaces only as a suppressed "process has crashed"
     warning dialog and a silent reset.
     -> caught by the dialog interceptor and the is_running() poll.
  3. An action the fuzzer runs on the main thread that raises directly.
     -> caught by the per-action guard.

The log-file tail is the workhorse: it is clean (no interleaving with the
fuzzer's own prints) and needs no global side effects. We deliberately avoid
wrapping sys.stdout/stderr, which would otherwise swallow the output of every
later /gs-exec call in this session.

Modal dialogs would otherwise block the whole scheduler, so every warning/error
dialog and QMessageBox.exec_ is intercepted (recorded + auto-dismissed). Input
volumes are kept small, which also avoids the large-3D crop prompt entirely.
"""

import glob
import json
import os
import sys
import time
import traceback

import numpy as np
import qt
import slicer
import vtk

ANNOTATION_SLICE = "SideBySideDumb1"
VIEW_PLANES = ("XY", "XZ", "YZ")  # matches seg_widget.VIEW_PLANES

# Substrings in an intercepted dialog message that mean "the module is unhappy".
# The fuzzer avoids the benign triggers (it only applies when trained, never
# feeds a mismatched inference image), so any of these is treated as a finding.
DIALOG_CRASH_PATTERNS = (
    "crashed",
    "terminated",
    "failed to",
    "could not",
    "error",
)

# Messages that are expected/benign even though they reach a dialog, so they do
# not count as findings.
DIALOG_BENIGN_PATTERNS = ("features are not ready",)


class InteractiveSegmenterFuzzer:
    def __init__(self, seed=None):
        self.seed = int(time.time()) if seed is None else int(seed)
        self.rng = np.random.default_rng(self.seed)

        self.status_dir = os.path.join(slicer.app.temporaryPath, "interactive_seg_fuzz")
        os.makedirs(self.status_dir, exist_ok=True)
        self.status_path = os.path.join(self.status_dir, "fuzz_status.json")

        # --- counters / live state ---
        self.tick_count = 0
        self.session_count = 0
        self.action_counts = {}
        self.history = []  # recent (config, action) for crash reports
        self.crashed = False
        self.crash_info = None
        self.running = True

        # --- per-session state ---
        self.config = None
        self.source = None
        self.session_nodes = []  # node ids to delete when the session ends
        self.master = None  # spatial-shaped uint8 annotation, the source of truth
        self.classes = set()
        self.next_class = 1
        self.actions_left = 0
        self.intentional_stop = False
        # Every few sessions, close the whole scene instead of just deleting this
        # session's nodes: keeps the scene from growing unbounded and exercises
        # the module's StartCloseEvent handling / "works again after a close".
        self._scene_close_every = int(self.rng.integers(4, 9))

        # --- crash sinks ---
        self._log_path = None
        self._log_pos = 0
        self._saved_dialogs = {}
        # Live status goes to the real interpreter console, not the per-/gs-exec
        # capture stream, so it never depends on whoever called us last.
        self._console = sys.__stdout__ or sys.stdout

        self.frame = self._get_frame()

        self._install_dialog_interceptors()
        self._open_log_tail()

        self._timer = qt.QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

        self._log(
            f"Fuzzer started. seed={self.seed}  status={self.status_path}\n"
            f"  log tail: {self._log_path or '(none found; relying on tee/dialog/poll)'}"
        )
        self._write_status()
        self._schedule(0.5)

    # ------------------------------------------------------------------
    # Widget access
    # ------------------------------------------------------------------
    def _get_frame(self):
        slicer.util.selectModule("InteractiveSegmenter")
        slicer.app.processEvents()
        module = slicer.modules.interactivesegmenter
        return module.widgetRepresentation().self().interactive_segmenter_frame

    # ------------------------------------------------------------------
    # Crash sinks
    # ------------------------------------------------------------------
    def _install_dialog_interceptors(self):
        """Replace the blocking dialog calls with recorders so the scheduler is
        never frozen, and so a suppressed 'process crashed' warning becomes a
        finding rather than an invisible reset."""

        def record(kind):
            def handler(*args, **kwargs):
                text = " ".join(str(a) for a in args)
                self._on_dialog(kind, text)
                return None

            return handler

        for name in ("warningDisplay", "errorDisplay", "infoDisplay"):
            if hasattr(slicer.util, name):
                self._saved_dialogs[name] = getattr(slicer.util, name)
                setattr(slicer.util, name, record(name))

        # The large-3D crop prompt and any stray QMessageBox would block on
        # exec_(); auto-dismiss with a default and record the text.
        self._saved_dialogs["QMessageBox.exec_"] = qt.QMessageBox.exec_

        def msgbox_exec(box, *args, **kwargs):
            try:
                self._on_dialog("QMessageBox", box.text)
            except Exception:
                pass
            return 0

        qt.QMessageBox.exec_ = msgbox_exec

    def _on_dialog(self, kind, text):
        low = text.lower()
        benign = any(p in low for p in DIALOG_BENIGN_PATTERNS)
        is_finding = (not benign) and any(p in low for p in DIALOG_CRASH_PATTERNS)
        self._log(f"[dialog:{kind}] {text}")
        if is_finding and not self.crashed:
            self._flag_crash("dialog", f"{kind}: {text}")

    def _open_log_tail(self):
        """Locate the session log file and seek to its end, so the tail only
        reports tracebacks produced from now on (covers the consumer subprocess,
        whose stdout the launcher mirrors here)."""
        candidates = []
        try:
            fp = slicer.app.errorLogModel().filePath
            if fp:
                candidates.append(fp)
        except Exception:
            pass
        try:
            settings_dir = os.path.dirname(slicer.app.slicerUserSettingsFilePath)
            candidates += glob.glob(os.path.join(settings_dir, "*.log"))
        except Exception:
            pass
        existing = [c for c in candidates if c and os.path.isfile(c)]
        if not existing:
            return
        self._log_path = max(existing, key=os.path.getmtime)
        try:
            self._log_pos = os.path.getsize(self._log_path)
        except OSError:
            self._log_pos = 0

    def _poll_log_tail(self):
        if self.crashed or not self._log_path:
            return
        try:
            size = os.path.getsize(self._log_path)
            if size < self._log_pos:  # rotated
                self._log_pos = 0
            if size == self._log_pos:
                return
            with open(self._log_path, "r", errors="replace") as f:
                f.seek(self._log_pos)
                chunk = f.read()
                self._log_pos = f.tell()
        except OSError:
            return
        if "Traceback (most recent call last)" in chunk:
            self._flag_crash("logfile", chunk[-4000:])

    def _read_log_tail(self, nbytes):
        """Read the last `nbytes` of the session log, where the launcher/consumer
        tracebacks land cleanly (no interleaving with the fuzzer's own prints)."""
        if not self._log_path:
            return "(no session log file found)"
        try:
            with open(self._log_path, "r", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - nbytes))
                return f.read()
        except OSError as exc:
            return f"(could not read log: {exc})"

    def _flag_crash(self, sink, trigger):
        if self.crashed:
            return
        self.crashed = True
        self._crash_sink = sink
        self._crash_trigger = trigger
        self._log(f"\n[fuzz] crash trigger via [{sink}] -- capturing log tail...")
        self._write_status()
        # The traceback body may still be flushing to the log/stderr when the
        # first line trips a sink. Finalize shortly after so the captured detail
        # includes the whole traceback rather than just its header.
        qt.QTimer.singleShot(400, self._finalize_crash)

    def _finalize_crash(self):
        detail = (
            f"trigger ({self._crash_sink}):\n{self._crash_trigger}\n\n"
            f"--- session log tail ---\n{self._read_log_tail(8000)}"
        )
        self.crash_info = {
            "sink": self._crash_sink,
            "detail": detail,
            "seed": self.seed,
            "config": self.config,
            "phase": self._phase(),
            "plane": self._current_plane(),
            "recent_actions": self.history[-40:],
            "tick": self.tick_count,
            "session": self.session_count,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        report = os.path.join(self.status_dir, f"fuzz_crash_{int(time.time())}.json")
        try:
            with open(report, "w") as f:
                json.dump(self.crash_info, f, indent=2, default=str)
        except Exception:
            pass
        self._write_status()
        banner = "=" * 70
        self._log(
            f"\n{banner}\nCRASH DETECTED via [{self._crash_sink}]  (seed={self.seed})\n{banner}\n"
            f"config: {self.config}\nphase: {self.crash_info['phase']}\n"
            f"recent actions: {[h['action'] for h in self.history[-12:]]}\n"
            f"report: {report}\n--- detail ---\n{detail}\n{banner}\n"
            f"Scheduler frozen for inspection. Call "
            f"slicer.modules._interactive_seg_fuzzer.stop() when done."
        )

    # ------------------------------------------------------------------
    # Input generation
    # ------------------------------------------------------------------
    def _make_volume(self, name, dim, channels, spatial=None):
        """Create a synthetic volume with separable bands plus noise so the
        classifier sometimes trains cleanly and sometimes degenerates. Returns
        (node, spatial_shape)."""
        if spatial is None:
            if dim == 2:
                h = int(self.rng.integers(96, 320))
                w = int(self.rng.integers(96, 320))
                spatial = (1, h, w)
            else:
                k = int(self.rng.integers(24, 72))
                j = int(self.rng.integers(24, 72))
                i = int(self.rng.integers(24, 72))
                spatial = (k, j, i)

        full = spatial + ((3,) if channels == 3 else ())
        arr = self.rng.integers(0, 40, full).astype(np.int16)

        # Two or three bands along the last spatial axis at distinct base levels.
        width = spatial[-1]
        n_bands = int(self.rng.integers(2, 4))
        edges = np.linspace(0, width, n_bands + 1).astype(int)
        levels = self.rng.integers(60, 230, (n_bands, full[-1] if channels == 3 else 1))
        for b in range(n_bands):
            sl = [slice(None)] * len(spatial) + ([slice(None)] if channels == 3 else [])
            sl[len(spatial) - 1] = slice(edges[b], edges[b + 1])
            arr[tuple(sl)] += levels[b]
        arr += self.rng.integers(-15, 15, full)
        arr = np.clip(arr, 0, 255).astype(np.uint8)

        node_class = "vtkMRMLVectorVolumeNode" if channels == 3 else "vtkMRMLScalarVolumeNode"
        node = slicer.mrmlScene.AddNewNodeByClass(node_class, name)
        slicer.util.updateVolumeFromArray(node, arr)
        self.session_nodes.append(node.GetID())
        return node, spatial

    def _random_config(self):
        dim = int(self.rng.choice([2, 3], p=[0.55, 0.45]))
        channels = int(self.rng.choice([1, 3], p=[0.5, 0.5]))
        n_inputs = int(self.rng.choice([1, 2, 3], p=[0.5, 0.3, 0.2]))
        scale = str(self.rng.choice(["Auto", "1x", "2x", "4x"]))
        # A custom inference image is only valid without extra inputs.
        use_inference = bool(self.rng.random() < 0.25) and n_inputs == 1
        preset = str(self.rng.choice(["Sharp", "Balanced", "Smooth", "Extra Smooth", "Complete"]))
        uncertainty = bool(self.rng.random() < 0.7)
        return {
            "dim": dim,
            "channels": channels,
            "n_inputs": n_inputs,
            "feature_scale": scale,
            "use_inference": use_inference,
            "preset": preset,
            "uncertainty": uncertainty,
        }

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def _cleanup_session_nodes(self):
        if self.source is not None:
            try:
                seg_name = f"{self.source.GetName()}_Segmented"
                node = slicer.mrmlScene.GetFirstNodeByName(seg_name)
                if node:
                    slicer.mrmlScene.RemoveNode(node)
            except Exception:
                pass
            try:
                ann_id = self.source.GetAttribute("InteractiveSegmenterAnnotationNode")
                if ann_id:
                    ann = slicer.mrmlScene.GetNodeByID(ann_id)
                    if ann:
                        slicer.mrmlScene.RemoveNode(ann)
            except Exception:
                pass
        for node_id in self.session_nodes:
            node = slicer.mrmlScene.GetNodeByID(node_id)
            if node:
                try:
                    slicer.mrmlScene.RemoveNode(node)
                except Exception:
                    pass
        self.session_nodes = []
        self.source = None

    def _close_scene(self):
        """Clear the entire MRML scene. Half the time we stop the session first;
        the other half we close mid-session so the module's StartCloseEvent
        observer (_onCloseEvent -> _stopSegmentation) has to tear down a live
        session and its consumer subprocess."""
        self._log(f"[fuzz] closing scene at session {self.session_count}")
        if self.frame._state is not None and self.rng.random() < 0.5:
            self._end_session()
            slicer.app.processEvents()
        slicer.mrmlScene.Clear(0)
        slicer.app.processEvents()
        # Everything we created is gone; forget the stale references.
        self.session_nodes = []
        self.source = None
        self.master = None
        self.classes = set()
        self._scene_close_every = int(self.rng.integers(4, 9))

    def _start_session(self):
        # Periodically close the scene instead of per-node cleanup.
        if self.session_count > 0 and self.session_count % self._scene_close_every == 0:
            self._close_scene()
        else:
            self._cleanup_session_nodes()
        cfg = self._random_config()
        self.config = cfg
        self.session_count += 1

        self.source, spatial = self._make_volume("fuzz_src", cfg["dim"], cfg["channels"])
        self.master = np.zeros(spatial, dtype=np.uint8)
        self.classes = set()
        self.next_class = 1

        frame = self.frame
        frame._inputSelector.setCurrentNode(self.source)

        for idx in range(2):
            extra_node = None
            if idx + 2 <= cfg["n_inputs"]:
                extra_node, _ = self._make_volume(
                    f"fuzz_extra{idx}", cfg["dim"], int(self.rng.choice([1, 3])), spatial=spatial
                )
            frame._extraImageSelectors[idx].setCurrentNode(extra_node)

        if cfg["use_inference"]:
            inf_node, _ = self._make_volume("fuzz_inf", cfg["dim"], cfg["channels"], spatial=spatial)
            frame._inferenceImageSelector.setCurrentNode(inf_node)
        else:
            frame._inferenceImageSelector.setCurrentNode(self.source)

        frame._featureScaleComboBox.setCurrentText(cfg["feature_scale"])
        frame._featurePresetComboBox.setCurrentText(cfg["preset"])
        frame._showUncertaintyCheckBox.setChecked(cfg["uncertainty"])

        # Let the selectors register before clicking Run, the way time passes for
        # a real user. Right after a scene clear the subject-hierarchy-backed
        # input selector can momentarily report no current node, so re-select if
        # needed rather than clicking Run with an empty input.
        slicer.app.processEvents()
        if frame._inputSelector.currentNode() is None:
            frame._inputSelector.setCurrentNode(self.source)
            slicer.app.processEvents()
        if frame._inputSelector.currentNode() is None:
            self._log("[fuzz] input selection did not register; skipping start this tick")
            return

        self.intentional_stop = False
        frame._runButton.click()  # start
        self.actions_left = int(self.rng.integers(15, 45))
        # Note: the action is recorded by _tick (the caller), not here, to avoid
        # double-counting.

    def _end_session(self):
        """Cancel the current session (if any) so a fresh config can start."""
        frame = self.frame
        if frame._state is not None:
            self.intentional_stop = True
            try:
                frame._runButton.click()  # cancel toggles stop
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Annotation mechanics (master array is the source of truth)
    # ------------------------------------------------------------------
    def _annotation_node(self):
        if self.source is None:
            return None
        ann_id = self.source.GetAttribute("InteractiveSegmenterAnnotationNode")
        return slicer.mrmlScene.GetNodeByID(ann_id) if ann_id else None

    def _push_annotation(self):
        ann = self._annotation_node()
        if ann is None:
            return
        ann.GetSegmentation().RemoveAllSegments()
        if self.master.any():
            # ImportLabelmapToSegmentationNode re-points the segmentation's
            # reference-image-geometry node reference at the temp labelmap; once
            # we delete the temp, that reference dangles and getSourceVolume()
            # returns None -- a crash the module never sees from real painting,
            # which edits segments in place and never touches the reference.
            # Snapshot and restore the reference so we stay a faithful stand-in.
            role = slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
            saved_ref = ann.GetNodeReferenceID(role)
            tmp = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "fuzz_tmp_strokes")
            try:
                tmp.CopyOrientation(self.source)
                slicer.util.updateVolumeFromArray(tmp, self.master)
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(tmp, ann)
            finally:
                slicer.mrmlScene.RemoveNode(tmp)
                if saved_ref:
                    ann.SetNodeReferenceID(role, saved_ref)

    def _paint_blob(self, cls):
        sp = self.master.shape
        k0 = k1 = 0
        if len(sp) == 3 and sp[0] > 1:
            kc = int(self.rng.integers(0, sp[0]))
            kr = int(self.rng.integers(1, max(2, sp[0] // 3)))
            k0, k1 = max(0, kc - kr), min(sp[0], kc + kr + 1)
        h, w = sp[-2], sp[-1]
        jc, ic = int(self.rng.integers(0, h)), int(self.rng.integers(0, w))
        jr = int(self.rng.integers(2, max(3, h // 4)))
        ir = int(self.rng.integers(2, max(3, w // 4)))
        j0, j1 = max(0, jc - jr), min(h, jc + jr + 1)
        i0, i1 = max(0, ic - ir), min(w, ic + ir + 1)
        if len(sp) == 3 and sp[0] > 1:
            self.master[k0:k1, j0:j1, i0:i1] = cls
        else:
            self.master[0, j0:j1, i0:i1] = cls

    # ------------------------------------------------------------------
    # View manipulation
    # ------------------------------------------------------------------
    def _annotation_slice(self):
        lm = slicer.app.layoutManager()
        widget = lm.sliceWidget(ANNOTATION_SLICE)
        return widget.sliceLogic() if widget else None

    def _zoom(self):
        logic = self._annotation_slice()
        if not logic:
            return
        node = logic.GetSliceNode()
        fov = node.GetFieldOfView()
        f = float(self.rng.choice([0.5, 0.7, 1.4, 2.0]))
        node.SetFieldOfView(fov[0] * f, fov[1] * f, fov[2])
        node.UpdateMatrices()

    def _pan(self):
        logic = self._annotation_slice()
        if not logic:
            return
        node = logic.GetSliceNode()
        fov = node.GetFieldOfView()
        m = node.GetSliceToRAS()
        m.SetElement(0, 3, m.GetElement(0, 3) + float(self.rng.uniform(-0.4, 0.4)) * fov[0])
        m.SetElement(1, 3, m.GetElement(1, 3) + float(self.rng.uniform(-0.4, 0.4)) * fov[1])
        node.UpdateMatrices()

    def _scroll(self):
        logic = self._annotation_slice()
        if not logic:
            return
        offset = logic.GetSliceOffset()
        logic.SetSliceOffset(offset + float(self.rng.uniform(-10, 10)))

    def _current_plane(self):
        """What the annotation view actually shows ('XY'/'XZ'/'YZ', or 'Reformat'
        after an oblique rotation). None when the view is unavailable."""
        logic = self._annotation_slice()
        if not logic:
            return None
        try:
            return str(logic.GetSliceNode().GetOrientation())
        except Exception:
            return None

    def _switch_plane(self):
        """Change the view plane the supported way: through the module's combo
        box. Picking a plane different from the current text guarantees the
        change signal fires, which also recovers from a prior oblique state."""
        combo = self.frame._viewPlaneComboBox
        if not combo.enabled:
            return
        others = [p for p in VIEW_PLANES if p != combo.currentText]
        combo.setCurrentText(str(self.rng.choice(others)))

    def _rotate_in_view(self):
        """Reorient the slice node directly, the way the view's own orientation
        selector does, exercising the module's _sync_view_plane adoption path.
        Occasionally rotate to an oblique plane instead -- the module is expected
        to ignore orientations outside XY/XZ/YZ, and that path is otherwise
        never hit."""
        logic = self._annotation_slice()
        if not logic:
            return
        node = logic.GetSliceNode()
        if self.rng.random() < 0.25:
            t = vtk.vtkTransform()
            t.SetMatrix(node.GetSliceToRAS())
            axis = self.rng.normal(size=3)
            axis /= np.linalg.norm(axis) + 1e-9
            t.RotateWXYZ(float(self.rng.uniform(5.0, 40.0)), *axis.tolist())
            node.GetSliceToRAS().DeepCopy(t.GetMatrix())
        else:
            node.SetOrientation(str(self.rng.choice(VIEW_PLANES)))
        node.UpdateMatrices()

    # ------------------------------------------------------------------
    # Action selection + execution
    # ------------------------------------------------------------------
    def _phase(self):
        # Tie "idle" to our own source node, not just frame._state: a scene close
        # removes the node and resets our session, and frame._state may lag a tick
        # behind. Treating a vanished source as idle forces a fresh start_session.
        if self.source is None or not slicer.mrmlScene.IsNodePresent(self.source):
            return "idle"
        st = self.frame._state
        if st is None:
            return "idle"
        if getattr(st, "applying_full_image", False):
            return "applying"
        if not getattr(st, "features_ready", False):
            return "warmup"
        if self.frame._applyButton.enabled:
            return "trained"
        return "ready"

    def _choose_action(self, phase):
        if phase == "idle":
            return "start_session"
        if phase == "applying":
            return "cancel" if self.rng.random() < 0.1 else "wait"

        is_3d = bool(self.config and self.config["dim"] == 3)
        away = bool(self.frame._resumeSegFrame.visible)
        weights = {
            "paint": 30,
            "add_class": 10,
            "remove_class": 6,
            "add_segment_button": 5,
            "remove_segment_button": 5,
            "pan": 12,
            "zoom": 10,
            "scroll": 8 if is_3d else 0,
            "switch_plane": 7 if is_3d else 0,
            "rotate_in_view": 4 if is_3d else 0,
            # Leave the module's layout occasionally; once away, come back fast
            # through the Resume button so most of the run stays productive.
            "layout_away": 0 if away else 2,
            "layout_resume": 30 if away else 0,
            "toggle_uncertainty": 6,
            "switch_preset": 6,
            "apply": 5 if phase == "trained" else 0,
            "cancel": 3,
            "close_scene": 2,
            "wait": 8,
        }
        actions = [a for a, wgt in weights.items() if wgt > 0]
        probs = np.array([weights[a] for a in actions], dtype=float)
        probs /= probs.sum()
        return str(self.rng.choice(actions, p=probs))

    def _execute(self, action):
        frame = self.frame
        if action == "start_session":
            self._start_session()
            return
        if action == "wait":
            return
        if action == "cancel":
            self._end_session()
            return
        if action == "close_scene":
            self._close_scene()
            return
        # Every remaining action needs a live session/source; if the scene was
        # cleared out from under us, skip until the next start_session.
        if self.source is None or not slicer.mrmlScene.IsNodePresent(self.source):
            return
        if action == "apply":
            if frame._applyButton.enabled:
                self.intentional_stop = True  # apply ends the session on completion
                frame._applyButton.click()
            return
        if action == "toggle_uncertainty":
            frame._showUncertaintyCheckBox.toggle()
            return
        if action == "switch_preset":
            if frame._featurePresetComboBox.enabled:
                preset = str(self.rng.choice(["Sharp", "Balanced", "Smooth", "Extra Smooth", "Complete"]))
                frame._featurePresetComboBox.setCurrentText(preset)
            return
        if action == "add_segment_button":
            btn = frame._segmentEditor.findChild(qt.QPushButton, "AddSegmentButton")
            if btn:
                btn.click()
            return
        if action == "remove_segment_button":
            btn = frame._segmentEditor.findChild(qt.QPushButton, "RemoveSegmentButton")
            if btn:
                btn.click()
            return
        if action == "pan":
            self._pan()
            return
        if action == "zoom":
            self._zoom()
            return
        if action == "scroll":
            self._scroll()
            return
        if action == "switch_plane":
            self._switch_plane()
            return
        if action == "rotate_in_view":
            self._rotate_in_view()
            return
        if action == "layout_away":
            slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
            return
        if action == "layout_resume":
            if frame._resumeSegFrame.visible:
                frame._resumeSegButton.click()
            return
        if action == "paint":
            if len(self.classes) < 2:
                cls = self.next_class
                self.next_class += 1
                self.classes.add(cls)
            else:
                cls = int(self.rng.choice(sorted(self.classes)))
            self._paint_blob(cls)
            self._push_annotation()
            return
        if action == "add_class":
            cls = self.next_class
            self.next_class += 1
            self.classes.add(cls)
            self._paint_blob(cls)
            self._push_annotation()
            return
        if action == "remove_class":
            if self.classes:
                cls = int(self.rng.choice(sorted(self.classes)))
                self.master[self.master == cls] = 0
                self.classes.discard(cls)
                self._push_annotation()
            return

    def _record_action(self, action, phase):
        """Record with the phase the action was chosen in (not the post-action
        phase, which would mislabel e.g. start_session as non-idle)."""
        self.action_counts[action] = self.action_counts.get(action, 0) + 1
        self.history.append({"action": action, "config": self.config, "phase": phase, "plane": self._current_plane()})
        self.history = self.history[-200:]

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    def _schedule(self, seconds):
        self._timer.start(int(max(0.05, seconds) * 1000))

    def _next_delay(self, action):
        if action == "wait":
            return float(self.rng.uniform(1.5, 5.0))
        if self.rng.random() < 0.12:  # occasional "think" pause
            return float(self.rng.uniform(2.0, 7.0))
        if action in ("paint", "add_class") and self.rng.random() < 0.4:
            return float(self.rng.uniform(0.15, 0.4))  # stroke burst
        d = float(self.rng.exponential(0.6))
        return min(3.0, max(0.12, d))

    def _tick(self):
        if not self.running:
            return
        # Crash sinks that need active polling.
        self._poll_log_tail()
        self._poll_consumer_death()
        if self.crashed:
            return  # frozen for inspection

        self.tick_count += 1
        phase = self._phase()

        # Force a new session when the budget runs out or the module ended one
        # (e.g. apply completed and reset state to idle).
        if phase != "idle" and not getattr(self.frame._state, "applying_full_image", False):
            if self.actions_left <= 0:
                self._end_session()
                self._write_status()
                self._schedule(self._next_delay("wait"))
                return

        action = self._choose_action(phase)
        try:
            self._execute(action)
            self._record_action(action, phase)
            if phase != "idle" and action not in ("wait",):
                self.actions_left -= 1
        except Exception:
            self._flag_crash("action", f"action={action} phase={phase}\n{traceback.format_exc()}")
            return

        if self.tick_count % 10 == 0:
            self.status()
        self._write_status()
        self._schedule(self._next_delay(action))

    def _poll_consumer_death(self):
        """Catch a consumer that died without a Python traceback (e.g. a native
        segfault), which otherwise only triggers a suppressed reset."""
        if self.crashed or self.intentional_stop:
            return
        st = self.frame._state
        if st is None:
            return
        proc = getattr(st, "consumer_process", None)
        if proc is not None and proc.poll() is not None and not getattr(st, "applying_full_image", False):
            self._flag_crash("consumer_death", f"consumer exited with code {proc.returncode}")

    # ------------------------------------------------------------------
    # Status / teardown
    # ------------------------------------------------------------------
    def _summary(self):
        return {
            "seed": self.seed,
            "running": self.running,
            "crashed": self.crashed,
            "ticks": self.tick_count,
            "sessions": self.session_count,
            "phase": self._phase(),
            "plane": self._current_plane(),
            "config": self.config,
            "actions_left": self.actions_left,
            "action_counts": self.action_counts,
            "status_dir": self.status_dir,
            "crash_info": self.crash_info,
        }

    def _write_status(self):
        try:
            with open(self.status_path, "w") as f:
                json.dump(self._summary(), f, indent=2, default=str)
        except Exception:
            pass

    def status(self):
        s = self._summary()
        self._log(
            f"[fuzz] session={s['sessions']} tick={s['ticks']} phase={s['phase']} plane={s['plane']} "
            f"left={s['actions_left']} crashed={s['crashed']} cfg={s['config']}"
        )

    def _log(self, message):
        try:
            self._console.write(message + "\n")
            self._console.flush()
        except Exception:
            pass

    def stop(self):
        self.running = False
        try:
            self._timer.stop()
        except Exception:
            pass
        # Restore intercepted dialogs.
        for name, fn in self._saved_dialogs.items():
            if name == "QMessageBox.exec_":
                qt.QMessageBox.exec_ = fn
            else:
                setattr(slicer.util, name, fn)
        if not self.crashed:
            self._end_session()
            slicer.app.processEvents()
            self._cleanup_session_nodes()
        self._log("Fuzzer stopped.")


def start(seed=None):
    existing = getattr(slicer.modules, "_interactive_seg_fuzzer", None)
    if existing is not None:
        try:
            existing.stop()
        except Exception:
            pass
    fuzzer = InteractiveSegmenterFuzzer(seed=seed)
    slicer.modules._interactive_seg_fuzzer = fuzzer
    return fuzzer


# Auto-start when exec'd via /gs-exec.
start()
