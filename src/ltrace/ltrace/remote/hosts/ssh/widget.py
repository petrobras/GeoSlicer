import dataclasses
import os

import qt
import ctk
from ltrace.slicer.widget.elided_label import ElidedLabel
from pathlib import Path

from ltrace.remote.hosts.base import Host
from ltrace.remote import paths as storage_paths
from ltrace.remote.hosts.ssh.ssh import SshHost


class SshConfigWidget(qt.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.rsa_key: Path = None
        # The host this widget was populated from, kept so that getData() can
        # return an edited copy rather than a rebuilt one. Fields the widget
        # does not show (storage layout, remote paths, remote_version) would
        # otherwise be silently reset to their defaults every time someone
        # opened Edit -- wiping whatever the organisation's template shipped.
        self._source: SshHost = None
        # The host as it arrived, so Reset can go back to it.
        self._template: SshHost = None
        self.setupUi()

    def setupUi(self) -> None:
        self.hostLineEdit = qt.QLineEdit(self)
        self.hostLineEdit.setToolTip("Server name or IP address")
        self.hostLineEdit.setPlaceholderText("ex: server1.example.com or 192.168.0.121")
        self.hostLineEdit.textChanged.connect(self._onHostChanged)

        self.portSpinBox = qt.QSpinBox(self)
        self.portSpinBox.setToolTip("Port number on server ")
        self.portSpinBox.setRange(1, 65535)
        self.portSpinBox.setSingleStep(1)
        self.portSpinBox.setValue(22)
        self.portSpinBox.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)

        self.customNameLineEdit = qt.QLineEdit(self)
        self.customNameLineEdit.setToolTip(
            "A configuration name for this connection, to be displayed in the list of connections. If left blank, the server name will be used."
        )
        self.customNameLineEdit.setPlaceholderText("ex: My Server")

        self.usernameLineEdit = qt.QLineEdit(self)
        self.usernameLineEdit.setToolTip("Username for this server")
        self.usernameLineEdit.setPlaceholderText("ex: user1")

        self.stayConnectedCheckBox = qt.QCheckBox("Stay connected", self)
        self.stayConnectedCheckBox.setToolTip(
            "Keep the connection open between executions. If unchecked, the password will be required for each execution. Disable this if you are using a shared client."
        )
        self.stayConnectedCheckBox.setChecked(True)

        self.addPublicKeyButton = qt.QPushButton("Add SSH key", self)
        self.addPublicKeyButton.setToolTip(
            "Add an SSH key (certificate or identity file) to use for authentication. This is the recommended method for authentication."
        )
        self.addPublicKeyButton.clicked.connect(self._onAddPublicKeyClicked)

        self.keyLabel = ElidedLabel(self)
        self.keyLabel.setToolTip("The certificate/identity file selected for authentication")
        self.keyLabel.setText("No certificate/identity selected")

        keyLayout = qt.QHBoxLayout()
        keyLayout.addWidget(self.stayConnectedCheckBox)
        keyLayout.addStretch(1)
        keyLayout.addWidget(self.addPublicKeyButton)

        self.openingCommandLineEdit = qt.QLineEdit(self)
        self.openingCommandLineEdit.setToolTip(
            "Run an opening command on the server before executing the script. This can be used to set up the environment, for example."
        )

        # self.remoteMountLineEdit = qt.QLineEdit(self)
        # self.remoteMountLineEdit.setToolTip(
        #     "The remote mount point to be used for the script. This must refer to a directory on the server that is also mounted locally."
        # )

        self.GPU_PartitionLineEdit = qt.QLineEdit(self)
        self.GPU_PartitionLineEdit.setText("default")
        self.GPU_PartitionLineEdit.setToolTip(
            "The GPU partition name to be used for the script. The target cluster must have a partition with this name or the script will fall back to the default partition."
        )

        self.CPU_PartitionLineEdit = qt.QLineEdit(self)
        self.CPU_PartitionLineEdit.setText("default")
        self.CPU_PartitionLineEdit.setToolTip(
            "The CPU partition name to be used for the script. The target cluster must have a partition with this name or the script will fall back to the default partition."
        )

        self._setupStorageUi()

        self.advSettingsArea = ctk.ctkCollapsibleButton()
        self.advSettingsArea.text = "Advanced"
        self.advSettingsArea.flat = True
        self.advSettingsArea.collapsed = True
        self.advancedSettingsLayout = qt.QFormLayout(self.advSettingsArea)

        self.advancedSettingsLayout.addRow("Command setup: ", self.openingCommandLineEdit)
        self.advancedSettingsLayout.addRow("CPU Partition: ", self.CPU_PartitionLineEdit)
        self.advancedSettingsLayout.addRow("GPU Partition: ", self.GPU_PartitionLineEdit)
        self.advancedSettingsLayout.addRow(self.storageGroupBox)

        layout = qt.QFormLayout(self)
        layout.addRow("Connection Name: ", self.customNameLineEdit)
        layout.addRow("Server: ", self.hostLineEdit)
        layout.addRow("Port: ", self.portSpinBox)
        layout.addRow("Username: ", self.usernameLineEdit)

        layout.addRow(keyLayout)
        layout.addRow(self.keyLabel)
        layout.addRow(self.advSettingsArea)

        self.setLayout(layout)

    def _setupStorageUi(self) -> None:
        """The cluster's shared storage, described from both sides.

        Deliberately framed as one folder seen from two vantage points rather
        than as a per-platform matrix: only the root for the machine you are on
        is shown, and the others are carried through untouched. These values
        come from the organisation's account template and are read-only until
        'Override' is ticked, because almost nobody should be changing them.
        """
        self.storageGroupBox = qt.QGroupBox("Cluster storage (NFS)")
        layout = qt.QFormLayout(self.storageGroupBox)

        self.clusterRootLineEdit = qt.QLineEdit(self)
        self.clusterRootLineEdit.setToolTip(
            "Root of the shared filesystem as the cluster itself sees it. Jobs run with these paths."
        )

        self.localRootLineEdit = qt.QLineEdit(self)
        self.localRootLineEdit.setToolTip(
            "Where this computer reaches that same folder. GeoSlicer writes job inputs and reads "
            "results through this path, so it must point at the same storage."
        )

        self.storageNoteLabel = qt.QLabel()
        self.storageNoteLabel.setStyleSheet("QLabel { color: gray; }")
        self.storageNoteLabel.setWordWrap(True)

        self.storageOverrideCheckBox = qt.QCheckBox("Override", self)
        self.storageOverrideCheckBox.setToolTip(
            "These paths are set by your organization. Tick to edit them for this account."
        )
        self.storageOverrideCheckBox.toggled.connect(self._onStorageOverrideToggled)

        self.storageVerifyButton = qt.QPushButton("Verify", self)
        self.storageVerifyButton.setToolTip(
            "Check that this computer can reach the shared storage, and that it is the same "
            "folder the cluster sees."
        )
        self.storageVerifyButton.clicked.connect(self._onVerifyStorage)

        self.storageResetButton = qt.QPushButton("Reset", self)
        self.storageResetButton.setToolTip("Restore the paths shipped in your organization's template.")
        self.storageResetButton.clicked.connect(self._onResetStorage)

        self.storageStatusLabel = qt.QLabel()
        self.storageStatusLabel.setWordWrap(True)

        buttons = qt.QHBoxLayout()
        buttons.addWidget(self.storageOverrideCheckBox)
        buttons.addStretch(1)
        buttons.addWidget(self.storageVerifyButton)
        buttons.addWidget(self.storageResetButton)

        layout.addRow("Path on the cluster: ", self.clusterRootLineEdit)
        layout.addRow("Path on this computer: ", self.localRootLineEdit)
        layout.addRow("", self.storageNoteLabel)
        layout.addRow(buttons)
        layout.addRow(self.storageStatusLabel)

        self._onStorageOverrideToggled(False)

    def _onStorageOverrideToggled(self, checked: bool) -> None:
        self.clusterRootLineEdit.setReadOnly(not checked)
        self.localRootLineEdit.setReadOnly(not checked)
        self.storageResetButton.setEnabled(checked)

    def _storageConfig(self) -> dict:
        """The storage block for the host being edited, with this form's values."""
        config = dict(getattr(self._source, "storage", None) or {})
        config["cluster_root"] = self.clusterRootLineEdit.text.strip() or storage_paths.DEFAULT_STORAGE["cluster_root"]

        roots = dict(config.get("local_root") or {})
        roots[storage_paths.current_platform()] = self.localRootLineEdit.text.strip()
        config["local_root"] = roots
        return config

    def _showStorage(self, host) -> None:
        storage = storage_paths.storage_for(host)
        self.clusterRootLineEdit.setText(str(storage.cluster_root))
        self.localRootLineEdit.setText(str(storage.local_root))

        this = storage_paths.current_platform()
        others = [
            f"{name} uses {value}"
            for name, value in sorted(storage.local_roots.items())
            if name != this
        ]
        note = f"Detected: {this}."
        if others:
            note += "  Other clients: " + "; ".join(others) + "."
        if storage_paths.running_on_cluster():
            note = "GeoSlicer is running inside the cluster, so both paths are the same."
        self.storageNoteLabel.setText(note)
        self.storageStatusLabel.setText("")

    def _onResetStorage(self) -> None:
        """Back to whatever the organization's template shipped."""
        self._showStorage(self._template or self._source)
        self.storageStatusLabel.setText("Restored the paths from your organization's template.")

    def _onVerifyStorage(self) -> None:
        """Say plainly whether the shared storage is reachable.

        A wrong path here fails silently deep inside a job handler -- the job
        directory is created on the cluster and then nothing happens -- so it
        is worth being able to ask the question directly.
        """
        local_root = Path(self.localRootLineEdit.text.strip())
        cluster_root = self.clusterRootLineEdit.text.strip()

        if not cluster_root:
            self.storageStatusLabel.setText("Set the cluster path first.")
            return

        if not local_root.exists():
            self.storageStatusLabel.setText(
                f"Not reachable: {local_root} does not exist on this computer. "
                "The share is probably not mounted."
            )
            return

        if not os.access(str(local_root), os.W_OK):
            self.storageStatusLabel.setText(f"Found {local_root}, but it is not writable.")
            return

        self.storageStatusLabel.setText(
            f"{local_root} is reachable and writable. Connect to the account to confirm "
            "the cluster sees the same folder."
        )

    def _onHostChanged(self, text: str) -> None:
        if self.customNameLineEdit.text == "" or self.customNameLineEdit.text == text[:-1]:
            self.customNameLineEdit.setText(text)

    def _onAddPublicKeyClicked(self) -> None:
        sshPath = Path(Path.home()) / ".ssh"

        if not sshPath.exists():
            sshPath = Path.home()

        fileDialog = qt.QFileDialog(
            self,
            "Select a SSH certificate/identity file",
            str(sshPath),
            "Certificate/Identity files (*.pem *.pub)",
        )
        fileDialog.setFileMode(qt.QFileDialog.ExistingFiles)

        if fileDialog.exec_():
            self.rsa_key = Path(fileDialog.selectedFiles()[0])
            self.keyLabel.setText(f" - {self.rsa_key}")

        fileDialog.deleteLater()

    def getRSAKeyPathString(self) -> str:
        return str(self.rsa_key) if self.rsa_key else None

    def setData(self, data: SshHost) -> None:
        self._source = data
        self._template = data
        blockState = self.blockSignals(True)
        self.usernameLineEdit.setText(data.username)
        self.customNameLineEdit.setText(data.name)
        self.hostLineEdit.setText(data.address)

        self.keyLabel.setText(f" - {data.rsa_key}")

        self.portSpinBox.setValue(data.port)

        self.openingCommandLineEdit.setText(data.opening_command)

        # self.remoteMountLineEdit.setText(data.remote_mount)
        self.CPU_PartitionLineEdit.setText(data.cpu_partition)
        self.GPU_PartitionLineEdit.setText(data.gpu_partition)

        self._showStorage(data)

        self.blockSignals(blockState)

    def getData(self) -> SshHost:
        edited = dict(
            name=self.customNameLineEdit.text.strip(),
            address=self.hostLineEdit.text.strip(),
            username=self.usernameLineEdit.text.strip(),
            port=self.portSpinBox.value,
            rsa_key=self.getRSAKeyPathString(),
            opening_command=self.openingCommandLineEdit.text.strip(),
            cpu_partition=self.CPU_PartitionLineEdit.text.strip(),
            gpu_partition=self.GPU_PartitionLineEdit.text.strip(),
            storage=self._storageConfig(),
        )

        # Only overwrite what this form owns. Anything else on the source host
        # -- including fields added later -- carries through untouched.
        if self._source is not None:
            return dataclasses.replace(self._source, **edited)

        return SshHost(**edited)
