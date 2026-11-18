import argparse
import logging
import os
import shutil
import subprocess
import sys
import tomli
import traceback

from pathlib import Path
from typing import Optional, Union, List
from deploy.utils import FlushStreamHandler, find_submodules_setup_directory, get_repo_root

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    logger.addHandler(FlushStreamHandler(sys.stdout))

# Constants
SLICERLTRACE_REPO_FOLDER = get_repo_root()


def resolve_conflict_prompt(existing_mapping: dict, new_mapping: dict) -> str:
    """Prompt user in terminal to resolve a conflict. Returns the winning partner name."""
    dst_rel = existing_mapping["dst_rel"]
    print(f"\nConflict detected for destination path: {dst_rel}")
    print(f"  1. Partner '{existing_mapping['partner']}' ({existing_mapping['src_rel']})")
    print(f"  2. Partner '{new_mapping['partner']}' ({new_mapping['src_rel']})")
    while True:
        try:
            choice = input("Select which partner's file should take priority (enter 1 or 2): ").strip()
            if choice == "1":
                return existing_mapping["partner"]
            elif choice == "2":
                return new_mapping["partner"]
            else:
                print("Invalid selection. Please enter 1 or 2.")
        except ValueError:
            print("Invalid input. Please enter 1 or 2.")
        except EOFError:
            # Fallback for non-interactive environments: default to the first one defined.
            logger.warning("Non-interactive terminal detected. Defaulting to first partner option.")
            return existing_mapping["partner"]


def inject_partner_files(
    partner_name: Union[str, List[str], None], development: bool = False, repo_root: Optional[Path] = None
) -> None:
    """Inject partner-specific files into the repository workspace."""
    if not partner_name:
        return

    if isinstance(partner_name, str):
        partner_names = [partner_name]
    else:
        partner_names = partner_name

    root = repo_root or SLICERLTRACE_REPO_FOLDER

    all_mappings = []
    for name in partner_names:
        partner_dir = root / "src" / "partners" / name
        if not partner_dir.exists():
            raise RuntimeError(f"Partner directory not found: {partner_dir}")

        overwrite_toml_path = partner_dir / "overwrite.toml"
        if not overwrite_toml_path.exists():
            logger.info(f"No overwrite.toml found for partner {name}. Skipping file injection.")
            continue

        with open(overwrite_toml_path, "rb") as f:
            content = tomli.load(f)

        overwrites = content.get("overwrites", {})
        for src_rel, dst_rel in overwrites.items():
            src_path = partner_dir / src_rel
            if not src_path.exists():
                src_path = partner_dir / "src" / src_rel

            if not src_path.exists():
                logger.warning(f"Source file/folder for overwrite not found: {src_rel} (checked under {partner_dir})")
                continue

            all_mappings.append(
                {
                    "partner": name,
                    "src_rel": src_rel,
                    "dst_rel": dst_rel,
                    "src_path": src_path,
                    "dst_path": root / dst_rel,
                }
            )

    resolved_mappings = []
    decision_cache = {}

    for new_m in all_mappings:
        conflicting_existing = []
        for existing_m in resolved_mappings:
            p1 = existing_m["dst_path"].resolve()
            p2 = new_m["dst_path"].resolve()
            if p1 == p2 or p1 in p2.parents or p2 in p1.parents:
                conflicting_existing.append(existing_m)

        if not conflicting_existing:
            resolved_mappings.append(new_m)
            continue

        keep_new = True
        for existing_m in conflicting_existing:
            p1 = existing_m["dst_path"].resolve()
            p2 = new_m["dst_path"].resolve()

            # Determine the highest common denominator path causing the conflict
            conflict_root = p1 if (p1 == p2 or p1 in p2.parents) else p2
            cache_key = (existing_m["partner"], new_m["partner"], str(conflict_root))

            if cache_key in decision_cache:
                chosen_partner = decision_cache[cache_key]
            else:
                chosen_partner = resolve_conflict_prompt(existing_m, new_m)
                decision_cache[cache_key] = chosen_partner

            if chosen_partner == existing_m["partner"]:
                # 'Existing' wins, 'New' loses. 'New' is fully discarded
                # if 'Existing' is the exact same path or a parent folder of 'New'.
                if p1 == p2 or p1 in p2.parents:
                    keep_new = False
                    break
            else:
                # 'New' wins, 'Existing' loses. 'Existing' is fully removed
                # if 'New' is the exact same path or a parent folder of 'Existing'.
                if p1 == p2 or p2 in p1.parents:
                    if existing_m in resolved_mappings:
                        resolved_mappings.remove(existing_m)

        if keep_new:
            resolved_mappings.append(new_m)

    # Sort resolved_mappings so all folder injections occur before individual file injections.
    # This prevents folder copies (shutil.copytree) from wiping out specific winning files.
    resolved_mappings.sort(key=lambda m: 0 if m["src_path"].is_dir() else 1)
    for m in resolved_mappings:
        dst_path = m["dst_path"]
        src_path = m["src_path"]
        partner_dir = root / "src" / "partners" / m["partner"]

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Overwriting {m['dst_rel']} with {src_path.relative_to(partner_dir)}")

        # Overwrite folder contents, removing pre-existing files
        if dst_path.exists() or dst_path.is_symlink():
            if dst_path.is_dir() and not dst_path.is_symlink():
                shutil.rmtree(dst_path)
            else:
                dst_path.unlink()

        if development:
            try:
                logger.info(f"Creating symbolic link: {dst_path} -> {src_path}")
                os.symlink(src_path, dst_path, target_is_directory=src_path.is_dir())
            except OSError as e:
                message = f"Symlink creation failed: {e}.\n{traceback.format_exc()}"
                if sys.platform == "win32":
                    message += "\nYou need to enable developer mode on Windows to create symlinks."
                raise PermissionError(message)
        else:
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)


def install_partner_dependencies(
    partner_name: Union[str, List[str], None],
    development: bool = False,
    repo_root: Optional[Path] = None,
    sys_executable: Optional[str] = None,
) -> None:
    """Install dependencies found in partner submodules."""
    if not partner_name:
        return

    if isinstance(partner_name, str):
        partner_names = [partner_name]
    else:
        partner_names = partner_name

    root = repo_root or SLICERLTRACE_REPO_FOLDER

    for name in partner_names:
        partner_dir = root / "src" / "partners" / name
        if not partner_dir.exists():
            logger.warning(f"Partner directory not found: {partner_dir}")
            continue

        submodules_to_install = []
        if (partner_dir / "setup.py").exists() or (partner_dir / "pyproject.toml").exists():
            submodules_to_install.append(partner_dir)

        for tp_dir in partner_dir.rglob("third-parties"):
            if tp_dir.is_dir():
                submodules_to_install.extend(find_submodules_setup_directory(tp_dir))

        logger.info(f"Installing dependencies for partner '{partner_name}'...")
        for path in submodules_to_install:
            if not sys_executable:
                sys_executable = sys.executable

            logger.info(f"Installing submodule from {path}")
            pip_cmd = [sys_executable, "-m", "pip", "install"]
            if development:
                pip_cmd.append("-e")
            pip_cmd.append(str(path))
            subprocess.check_call(pip_cmd)


def main():
    parser = argparse.ArgumentParser(description="Manage partner-specific workspace configurations.")
    parser.add_argument("partner", help="Name of the partner to setup.", nargs="+")
    parser.add_argument(
        "--dev", action="store_true", help="Use symbolic links for file injection and editable mode for installs."
    )
    parser.add_argument("--install", action="store_true", help="Install partner-specific dependencies.")
    parser.add_argument("--root", help="Override repository root path.")

    args = parser.parse_args()
    repo_root = Path(args.root) if args.root else None

    try:
        inject_partner_files(args.partner, args.dev, repo_root)
        if args.install:
            install_partner_dependencies(args.partner, args.dev, repo_root)

        logger.info(f"Partner '{args.partner}' setup completed successfully.")
    except Exception as e:
        logger.error(f"Error during partner setup: {e}. {traceback.print_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
