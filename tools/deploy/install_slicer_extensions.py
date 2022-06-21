import json
import logging
import urllib
import urllib.request
import time
from pathlib import Path


def install_extensions(config_path):
    config = read_config(config_path)

    em = slicer.app.extensionsManagerModel()
    if "RequiredExtensions" not in config:
        return

    slicer_dir = Path(slicer.app.slicerHome).resolve().absolute()
    extensions_dir = slicer_dir / "extensions"
    extensions_dir.mkdir(exist_ok=True)

    settings = slicer.app.revisionUserSettings()
    settings.setValue("Extensions/InstallPath", str(extensions_dir))
    settings.sync()

    url = em.serverUrl.__self__.serverUrl().toString() + "/api/json"
    for extension in config["RequiredExtensions"]:
        if extension in em.installedExtensions:
            continue

        try:
            all_item_ids = [(ext["item_id"], ext["extension_id"]) for ext in get_extension_list_by_name(url, extension)]
        except RuntimeError:
            raise RuntimeError("Could not download extension: " + extension)

        if len(all_item_ids) == 0:
            raise RuntimeError(
                "No version of "
                + extension
                + " matching the architecture, the revision and the OS of Slicer was found on the server. It cannot be installed."
            )

        if len(all_item_ids) != 1:
            raise RuntimeError("There should be only one id matching our request. We cannot install " + extension + ".")

        print("Installing: ", extension)

        installed = False

        def wait_for_installation(*args):
            nonlocal installed
            installed = True

        em.connect("extensionInstalled(const QString&)", wait_for_installation)
        if not em.downloadAndInstallExtension(all_item_ids[0][1]):
            raise RuntimeError("Failed to retrieve metadata for extension " + extension)

        while not installed:
            slicer.app.processEvents()
            time.sleep(0.1)

        slicer.app.processEvents()
        em.disconnect("extensionInstalled(const QString&)", wait_for_installation)


def get_extension_list_by_name(url, extensionName):
    method = "midas.slicerpackages.extension.list"
    codebase = "Slicer4"
    data = {
        "method": method,
        "codebase": codebase,
        "productname": extensionName,
        "os": slicer.app.os,
        "arch": slicer.app.arch,
        "slicer_revision": slicer.app.revision,
    }
    return call_midas_url(url, data)


def call_midas_url(url, data):
    url_values = urllib.parse.urlencode(data)
    full_url = url + "?" + url_values
    try:
        response = urllib.request.urlopen(full_url)
        response_read = response.read()
        response_dict = json.loads(response_read)
        response_data = response_dict["data"]
    except Exception as error:
        logging.debug(f"Error: {error}")
    finally:
        response.close()
    return response_data


def read_config(config_path):
    with open(config_path) as f:
        config_json = f.read()
        try:
            return json.JSONDecoder().decode(config_json)
        except ValueError:
            raise RuntimeError("Could not parse json in config file.")
