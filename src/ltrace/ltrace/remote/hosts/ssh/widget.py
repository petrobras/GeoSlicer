import qt
import ctk
from ltrace.slicer.widget.elided_label import ElidedLabel
from pathlib import Path

from ltrace.remote.hosts.base import Host
from ltrace.remote.hosts.ssh.ssh import SshHost


class SshConfigWidget(qt.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.rsa_key: Path = None
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

        self.advSettingsArea = ctk.ctkCollapsibleButton()
        self.advSettingsArea.text = "Advanced"
        self.advSettingsArea.flat = True
        self.advSettingsArea.collapsed = True
        self.advancedSettingsLayout = qt.QFormLayout(self.advSettingsArea)

        self.advancedSettingsLayout.addRow("Command setup: ", self.openingCommandLineEdit)
        # self.advancedSettingsLayout.addRow("Remote Mount (NFS): ", self.remoteMountLineEdit)
        self.advancedSettingsLayout.addRow("CPU Partition: ", self.CPU_PartitionLineEdit)
        self.advancedSettingsLayout.addRow("GPU Partition: ", self.GPU_PartitionLineEdit)

        layout = qt.QFormLayout(self)
        layout.addRow("Connection Name: ", self.customNameLineEdit)
        layout.addRow("Server: ", self.hostLineEdit)
        layout.addRow("Port: ", self.portSpinBox)
        layout.addRow("Username: ", self.usernameLineEdit)

        layout.addRow(keyLayout)
        layout.addRow(self.keyLabel)
        layout.addRow(self.advSettingsArea)

        self.setLayout(layout)

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

    def getRSAKeyPathString(self) -> str:
        return str(self.rsa_key) if self.rsa_key else None

    def setData(self, data: SshHost) -> None:
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

        self.blockSignals(blockState)

    def getData(self) -> SshHost:
        return SshHost(
            name=self.customNameLineEdit.text.strip(),
            address=self.hostLineEdit.text.strip(),
            username=self.usernameLineEdit.text.strip(),
            port=self.portSpinBox.value,
            rsa_key=self.getRSAKeyPathString(),
            opening_command=self.openingCommandLineEdit.text.strip(),
            remote_mount="",  # self.remoteMountLineEdit.text.strip(),
            cpu_partition=self.CPU_PartitionLineEdit.text.strip(),
            gpu_partition=self.GPU_PartitionLineEdit.text.strip(),
        )
