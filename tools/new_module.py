import argparse
import os
import re
import shutil

from pathlib import Path


def replace_content(path, words_to_replace: dict):
    with open(path, "r") as f:
        content = f.read()

    for old, new in words_to_replace.items():
        content = content.replace("{{" + old + "}}", new)

    with open(path, "w") as f:
        f.write(content)


def get_modules_directory_path():
    match = re.search(r"(\S+slicerltrace)\S+", __file__)
    if not match:
        raise RuntimeError(
            "Couldn't find the slicerltrace module's directory. Please, use the script from inside the slicerltrace tools directory."
        )

    path_string = match.group(1)
    return Path(path_string)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="LTrace Extension Starter Kit.")
    parser.add_argument("-n", "--name", default="", type=str, help="The modules' name. Example: 'New Module'")
    parser.add_argument(
        "-t",
        "--title",
        type=str,
        default="",
        help="The module's title. Example: 'New Module'. Default to the same as the name input string.",
    )
    parser.add_argument(
        "-c", "--category", type=str, default="Tools", help="The module's category. Default to 'LTrace Tools'."
    )
    parser.add_argument("--cli", action="store_true", help="Add CLI related files", default=False)

    args = parser.parse_args()
    if args.name == "":
        raise AttributeError("Missing modules name.")

    name = args.name
    name_only_words = re.findall(r"[A-Z]+[a-z]*|[a-z]+", name)
    name = "".join(name_only_words)
    title = args.title if args.title.replace(" ", "") else " ".join(name_only_words)
    category = args.category

    modules_dir_path = get_modules_directory_path()

    # Create module directory
    new_module_path = modules_dir_path / "src" / "modules" / name
    if new_module_path.exists():
        raise RuntimeError(f"Unable to create new module as {name}. A module named {name} already exists!")

    # Copy template files to the new module directory
    module_template_directory = Path(__file__).parent / "resources" / "ModuleTemplate"
    shutil.copytree(module_template_directory, new_module_path)

    new_module_file_path_list = [
        Path(root) / file for root, _, files in os.walk(new_module_path.as_posix()) for file in files
    ]
    new_module_dir_path_list = [Path(root) for root, _, _ in os.walk(new_module_path.as_posix())]

    if not args.cli:
        # Remove CLI files
        cli_file_path_list = [file for file in new_module_file_path_list if "CLI" in file.name]
        for file in cli_file_path_list:
            new_module_file_path_list.remove(file)
            file.unlink()

        # Remove CLI directories
        cli_dir_path_list = [dir for dir in new_module_dir_path_list if "CLI" in dir.name]
        for dir in cli_dir_path_list:
            new_module_dir_path_list.remove(dir)
            shutil.rmtree(dir)

    else:
        template_file_with_cli = new_module_path / "ModuleTemplate_with_CLI.py"
        template_default_file = new_module_path / "ModuleTemplate.py"
        # Remove template without CLI
        template_default_file.unlink()

        # Rename template with CLI with default name
        template_file_with_cli.rename(template_default_file)

        # Remove old reference from file path list
        new_module_file_path_list = [
            file for file in new_module_file_path_list if "ModuleTemplate_with_CLI" not in file.name
        ]

    # Replace templates contents based on the new module input
    words_to_replace = {
        "name": name,
        "name_lower_case": name.lower(),
        "title": title,
        "category": category,
    }

    ## Python files
    py_file_path_list = [file for file in new_module_file_path_list if file.suffix == ".py"]
    for py_file in py_file_path_list:
        replace_content(py_file, words_to_replace)

    ## XML files
    xml_file_path_list = [file for file in new_module_file_path_list if file.suffix == ".xml"]
    for xml_file in xml_file_path_list:
        replace_content(xml_file, words_to_replace)

    ## README file
    replace_content(new_module_path / "README.md", words_to_replace)

    # Rename template files/directories name to the name related to the new module
    ## Files
    template_name_path_list = [file for file in new_module_file_path_list if "ModuleTemplate" in file.as_posix()]

    ## Directories
    template_name_path_list.extend(
        [directory for directory in new_module_dir_path_list if "ModuleTemplate" in directory.name]
    )

    for file in template_name_path_list:
        new_filename = file.name.replace("ModuleTemplate", name)
        file.rename(file.parent / new_filename)
