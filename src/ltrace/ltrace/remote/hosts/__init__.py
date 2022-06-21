from .base import Host
from .ssh.ssh import SshHost

try:
    from .biaep.biaep import BiaepHost
except ImportError:
    pass

from .utils import protocol_to_host

PROTOCOL_HANDLERS = protocol_to_host()
