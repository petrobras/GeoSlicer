import os
import sys
from pathlib import Path
import paramiko


def livePrint(msg):
    print(msg)
    sys.stdout.flush()


class SSHClient(object):
    def __init__(self, host, port, user, password, **kwargs):
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.load_system_host_keys()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        user = user.lower()  # TODO should we check for OS?

        key_filename = kwargs.get("key_filename", "").strip()
        if len(key_filename) > 1:
            self.ssh_client.connect(host, port, user, key_filename=kwargs["key_filename"], timeout=5)
        else:
            self.ssh_client.connect(host, port, user, password, timeout=5)

    def checkTransport(self):
        # use the code below if is_active() returns True
        try:
            transport = self.ssh_client.get_transport()
            if transport is not None and transport.is_active():
                transport.send_ignore()
                return True
            return False

        except EOFError as e:
            return False

    def close(self):
        try:
            self.ssh_client.close()
        except Exception as sshError:
            pass

    def exec_cmd(self, cmd):
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd)
            if stderr.channel.recv_exit_status() != 0:
                return stderr.read()
            return stdout.read()
        except paramiko.SSHException as sshError:
            raise RuntimeError(f"Missing connection to remote server. Cause: {repr(sshError)}")


def send_files_over_ftp(ftp_client, files, destination):
    try:
        # ftp_client = self.ssh_client.open_sftp()
        for file in files:
            cpname = str(Path(file).name)
            ftp_client.put(file, f"./{destination}/{cpname}")
    except paramiko.SSHException as sshError:
        raise RuntimeError(f"Missing connection remote to server. Cause: {repr(sshError)}")
    except paramiko.SFTPError as ftpError:
        raise RuntimeError(f"SFTP Missing connection to remote server. Cause: {repr(ftpError)}")


def fetch_files(ftp_client, files, destination):

    progressDict = {}
    progressEveryPercent = 10

    for i in range(0, 101):
        if i % progressEveryPercent == 0:
            progressDict[str(i)] = ""

    def printProgressDecimal(x, y):
        if (
            int(100 * (int(x) / int(y))) % progressEveryPercent == 0
            and progressDict[str(int(100 * (int(x) / int(y))))] == ""
        ):
            livePrint(
                "{}% ({} Transfered(B)/ {} Total File Size(B))".format(str("%.2f" % (100 * (int(x) / int(y)))), x, y)
            )
            progressDict[str(int(100 * (int(x) / int(y))))] = "1"

    try:
        os.makedirs(destination, exist_ok=True)

        for file in files:
            cpname = str(Path(file).name)
            ftp_client.get(file, localpath=f"{destination}/{cpname}", callback=printProgressDecimal)
    except paramiko.SSHException as sshError:
        raise RuntimeError(f"Missing connection remote to server. Cause: {repr(sshError)}")
    except paramiko.SFTPError as ftpError:
        raise RuntimeError(f"SFTP Missing connection to remote server. Cause: {repr(ftpError)}")
