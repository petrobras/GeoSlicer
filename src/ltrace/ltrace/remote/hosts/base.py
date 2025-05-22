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

    def get_password(self):
        return keyring.get_password(self.get_key(), self.username)

    def set_password(self, password):
        keyring.set_password(self.get_key(), self.username, password)

    def delete_password(self):
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
