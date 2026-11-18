import argparse
import shutil
import sys
import git
import tomli
from deploy.utils import get_repo_root


def revert_customization(partner_name):
    repo_root = get_repo_root()
    partner_dir = repo_root / "src" / "partners" / partner_name

    if not partner_dir.exists():
        print(f"Error: Partner directory not found: {partner_dir}")
        return False

    overwrite_toml_path = partner_dir / "overwrite.toml"
    if not overwrite_toml_path.exists():
        print(f"Error: No overwrite.toml found for partner {partner_name} at {overwrite_toml_path}")
        return False

    print(f"Reverting partner '{partner_name}' customizations...")

    try:
        repo = git.Repo(repo_root)
    except git.InvalidGitRepositoryError:
        print(f"Error: {repo_root} is not a valid git repository.")
        return False

    with open(overwrite_toml_path, "rb") as f:
        try:
            content = tomli.load(f)
        except Exception as e:
            print(f"Error parsing {overwrite_toml_path}: {e}")
            return False

    overwrites = content.get("overwrites", {})
    if not overwrites:
        print("No overwrites found in overwrite.toml.")
        return True

    success = True
    for src_rel, dst_rel in overwrites.items():
        dst_path = repo_root / dst_rel

        print(f"\tReverting {dst_rel}...")

        if dst_path.exists() or dst_path.is_symlink():
            try:
                if dst_path.is_symlink():
                    dst_path.unlink()
                elif dst_path.is_dir():
                    shutil.rmtree(dst_path)
                else:
                    dst_path.unlink()
            except Exception as e:
                print(f"Warning: Failed to remove {dst_path}: {e}")
                # We continue anyway to try git checkout

        # Check if tracked by git before attempting restore
        try:
            is_tracked = repo.git.ls_files(str(dst_rel)) != ""

            if is_tracked:
                # git checkout -- <path> restores the file from the index
                repo.git.checkout("--", str(dst_rel))

                # If it was a directory, we also want to clean any untracked files
                # that were copied from the partner folder but weren't in git.
                repo.git.clean("-fd", "--", str(dst_rel))

        except git.GitCommandError as e:
            print(f"Warning: Failed to git restore {dst_rel}: {e.stderr.strip() if e.stderr else str(e)}")
            success = False

    if success:
        print("Successfully reverted partner customizations.")
    else:
        print("Completed with some errors.")

    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Revert partner customizations applied to the core folder.")
    parser.add_argument("partner", help="The name of the partner (e.g., petrobras)")
    args = parser.parse_args()

    if not revert_customization(args.partner):
        sys.exit(1)
