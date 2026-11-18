# Code Signing

## Overview
Code signing is the process of digitally signing executables and scripts to confirm the software author and guarantee that the code has not been altered or corrupted since it was signed. For GeoSlicer, this is critical for Windows deployments to avoid "Unknown Publisher" warnings and to ensure system integrity.

Code signing happens once, at the GeoSlicer base build (`geoslicerbase`). Because the base application is already signed by the time it is downloaded and extended with LTrace modules. This means CI/CD pipelines that build on top of the base never need direct access to the signing script or its credentials.

## Why Remote Code Signing?
In a typical CI/CD environment, build agents are often ephemeral containers (Linux or Windows) that do not have access to physical USB hardware tokens or highly sensitive private keys. Remote code signing allows:
- **Security**: The signing certificate and its hardware token stay on a single, secure Windows machine.
- **Flexibility**: Any build agent (even Linux containers) can request a signature via SSH.
- **Automation**: The process is fully integrated into the `geoslicerbase` build pipeline without manual intervention.

## How it Works
The system uses a client-server architecture over SSH:
1. **Client**: A Python script (`remote_codesign.py`, in `geoslicerbase/tools/pipeline/`) uploads the executable to a remote Windows host via SFTP.
2. **Server**: The remote host runs `signtool.exe` using a pre-configured certificate and token.
3. **Completion**: The client downloads the signed executable back and cleans up the remote workspace.

## Setup Guide

### 1. Server Setup (Remote Windows Host)
The "Signing Server" must be a Windows machine with the certificate installed.
- **OpenSSH Server**: Must be enabled and configured to allow SSH access.
- **Windows SDK**: Install the Windows SDK to get `signtool.exe`.
- **Drivers**: Install the hardware token drivers (e.g., SafeNet Authentication Client).
- **Environment Variables**: Define the following for the user that will log in via SSH:
    - `signtool`: Path to `signtool.exe`.
    - `TOKEN_CERTIFICATE_PATH`: Path to the `.cer` or `.pfx` file.
    - `TOKEN_PROVIDER`: The CSP name (e.g., "eToken Enumerator").
    - `SAFENET_PIN`: The hardware token password.
    - `TOKEN_CONTAINER_NAME`: The unique name of the certificate container.

### 2. Client Setup (Build Agent)
The client needs:
- **Python 3.x**
- **Paramiko**
- **SSH Private Key**: A key that is authorized on the signing server.

### 3. Environment Variables (CI/CD)
The following variables must be set in the `geoslicerbase` build environment (Jenkins or Docker):
- `CODESIGN_SERVER`: IP or Hostname of the signing server.
- `CODESIGN_USER`: SSH username.
- `CODESIGN_KEY`: Path to the SSH private key file.
- `CODESIGN_KEY_STRING`: Content of the SSH private key (Alternative to `CODESIGN_KEY`, useful for builds within containers).
- `CODESIGN_SERVER_PORT`: SSH port (default 22).

## CI/CD Integration

### GeoSlicer Base Build Pipeline
`geoslicerbase/tools/build_and_pack.py` accepts a `--code-signed` flag (plus `--codesign-server`, `--codesign-user`, `--codesign-key`, `--codesign-port`, defaulting to the `CODESIGN_*` environment variables above). When enabled, it signs the launcher executable it finds in the packaged application directory, before compressing and exporting it to the bucket.

### SlicerLTrace / Partner Deploy Scripts
Neither `deploy_slicer.py` nor `generate_test_deploy.py` (partner repository) sign anything anymore â€” they simply consume an already-signed base executable and build/package on top of it.

## Troubleshooting
- **Permission Denied**: Ensure the SSH public key is in the `authorized_keys` file on the server and that the user has write access to their home directory.
- **Signtool Error**: Verify that the hardware token is plugged in and the `SAFENET_PIN` variable is correct.
- **Network Issues**: Ensure SSH port is open on the signing server's firewall.