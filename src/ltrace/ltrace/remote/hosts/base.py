import keyring

from dataclasses import asdict, dataclass
from typing import Dict, ClassVar


@dataclass
class Host:
    username: str
    name: str
    protocol: ClassVar[str] = ""
    protocol_name: ClassVar[str] = "Empty"

    def get_key(self):
        pass

    @staticmethod
    def check_keyring():
        kr = keyring.get_keyring()
        if isinstance(kr, keyring.backends.chainer.ChainerBackend):
            kr = kr.backends[0]

        try:
            current_key = kr._keyring_key
        except AttributeError:
            # Keyring does not use a master password, no action required
            return

        if current_key is None:
            if kr._check_file():
                msg = "Please enter your master password in order to unlock the accounts keyring."
            else:
                msg = "No system keyring found. Please set up a new master password for the accounts keyring."
        else:
            return

        import qt

        dialog = qt.QInputDialog()
        dialog.setLabelText(msg)
        dialog.setWindowTitle("Enter master password")
        dialog.setTextEchoMode(qt.QLineEdit.Password)
        dialog.setModal(True)
        dialog.exec_()
        kr.keyring_key = dialog.textValue()

    def get_password(self):
        self.check_keyring()
        return keyring.get_password(self.get_key(), self.username)

    def set_password(self, password):
        self.check_keyring()
        keyring.set_password(self.get_key(), self.username, password)

    def delete_password(self):
        self.check_keyring()
        try:
            keyring.delete_password(self.get_key(), self.username)
        except keyring.errors.PasswordDeleteError:
            pass

    def to_dict(self):
        return {**asdict(self), "protocol": self.protocol}

    @classmethod
    def from_dict(cls, data: Dict):
        protocol = data.pop("protocol")
        if cls.protocol != protocol:
            raise ValueError(f"Protocol mismatch. Expected {cls.protocol}, got {protocol}")
        return cls(**data)

    @staticmethod
    def createWidget(self) -> "qt.QWidget":
        pass
