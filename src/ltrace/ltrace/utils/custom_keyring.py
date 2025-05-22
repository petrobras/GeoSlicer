import keyring
import keyring.backend
import keyring.errors


class InMemoryKeyring(keyring.backend.KeyringBackend):
    """A keyring that stores secrets in memory (RAM only)."""

    # System keyrings have priority 5
    priority = 4

    def __init__(self):
        self._storage = {}

    def get_password(self, service, username):
        return self._storage.get((service, username))

    def set_password(self, service, username, password):
        self._storage[(service, username)] = password

    def delete_password(self, service, username):
        try:
            del self._storage[(service, username)]
        except KeyError:
            raise keyring.errors.PasswordDeleteError("Password not found")
