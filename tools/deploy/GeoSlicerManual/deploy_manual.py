import argparse
import git
import logging
import subprocess
import sys

from pathlib import Path


# --- Configuration ---
REPO_DIR = Path(__file__).parents[3]

# The target GitHub repository URL.
GITHUB_REPO_URL = "git@github.com:ltracegeo/GeoSlicerManual.git"

# The name for the git remote URL that points to the GitHub repo.
REMOTE_NAME = "manual"

# The default branch to deploy to.
DEFAULT_TARGET_BRANCH = "gh-page"

# The path to the mkdocs.yml file.
MKDOCS_YML_PATH = (Path(__file__).parent / "mkdocs.yml").as_posix()


logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    logger.addHandler(logging.StreamHandler(sys.stdout))


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    """Executes a shell command, prints its output, and exits if it fails."""
    logger.info(f"🏃 Executing: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = (
            f"Command failed with exit code {result.returncode}\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}"
        )
        raise Exception(message)

    logger.info(result.stdout)
    return result


def setup_git_remote(remote_name: str, remote_url: str) -> None:
    """
    Ensures the git remote is configured correctly using GitPython.
    - Checks for a git repository in the given path.
    - Adds the remote if it doesn't exist.
    - Updates the remote's URL if it's incorrect.
    """
    logger.info(f"👋 Setting up git remote '{remote_name}'...")
    try:
        repo = git.Repo(REPO_DIR)
    except git.InvalidGitRepositoryError:
        logger.error(f"❌ Error: The directory '{REPO_DIR}' is not a valid git repository.")
        sys.exit(1)

    try:
        remote = repo.remote(name=remote_name)
        if remote.url != remote_url:
            logger.warning(
                f"⚠️ Remote '{remote_name}' found, but with incorrect URL '{remote.url}'. Updating to '{remote_url}'..."
            )
            remote.set_url(remote_url)
            logger.info(f"✅ URL for remote '{remote_name}' updated to '{remote_url}'.")
    except ValueError:
        logger.info(f"ℹ️ Remote '{remote_name}' not found. Creating it...")
        repo.create_remote(remote_name, remote_url)
        logger.info(f"✅ Remote '{remote_name}' created with URL '{remote_url}'.")

    logger.info("✅ Git remote setup complete.")


def _process(
    version: str,
    aliases: list[str],
    set_default: bool = False,
    push: bool = True,
    target_branch: str = DEFAULT_TARGET_BRANCH,
    remote_name: str = REMOTE_NAME,
) -> None:
    """
    Runs the main deployment process after argparse has parsed arguments.
    """

    # Ensure the git remote is configured correctly.
    setup_git_remote(remote_name, GITHUB_REPO_URL)

    version = ".".join(version.replace("v", "").split(".")[:2])
    # Deploy the specified version and any aliases using mike.
    logger.info(f"🚀 Deploying documentation version '{version}' to '{GITHUB_REPO_URL}'...")
    deploy_cmd = [
        "mike",
        "deploy",
        "--update-aliases",
        f"--config-file={MKDOCS_YML_PATH}",
        f"--remote={remote_name}",
        f"--branch={target_branch}",
        f'--message="Deploying documentation version {version}"',
    ]
    if push:
        deploy_cmd.append("--push")

    # Add version and aliases to the command
    deploy_cmd.extend([version] + aliases)
    run_command(deploy_cmd)

    # Optionally, set the new version as the default.
    if set_default:
        logger.info(f"👑 Setting default version...")
        default_cmd = [
            "mike",
            "set-default",
            f"--remote={remote_name}",
            f"--branch={target_branch}",
            f'--message="Setting documentation version {version} as default"',
        ]
        if push:
            default_cmd.append("--push")

        # Set the alias 'latest' or the version itself as the default
        default_target = "latest" if "latest" in aliases else version
        default_cmd.append(default_target)
        run_command(default_cmd)

    logger.info("🎉 Deployment successful!")
    logger.info("Check the Pages settings in your GitHub repository to ensure the site is published.")
    logger.info(f"🔗 https://ltracegeo.github.io/GeoSlicerManual/{version}/")


def run(
    version: str,
    aliases: list[str],
    set_default: bool = False,
    push: bool = True,
    target_branch: str = DEFAULT_TARGET_BRANCH,
    remote_name: str = REMOTE_NAME,
) -> None:
    try:
        _process(
            version=version,
            aliases=aliases,
            set_default=set_default,
            push=push,
            target_branch=target_branch,
            remote_name=remote_name,
        )
    except Exception as error:
        logger.error(f"❌ Error: {error}")
        sys.exit(1)


def main():
    """
    Deploys a versioned MkDocs site to a specific GitHub repository.
    This script uses 'mike' for versioning.

    Usage:
        python deploy_manual.py <version> [aliases...] [--set-default]

    Example:
        # Deploy version 1.0.0 and alias it as 'latest'
        python deploy_manual.py 1.0.0 latest

        # Deploy version 1.1.0, alias it as 'latest', and make it the default
        python deploy_manual.py 1.1.0 latest --set-default
    """
    parser = argparse.ArgumentParser(description="Deploy a versioned MkDocs site to GitHub Pages.")
    parser.add_argument("version", help='The version to deploy (e.g., "1.0.0").')
    parser.add_argument("aliases", nargs="*", help='Optional aliases for the version (e.g., "latest").')
    parser.add_argument("--remote", default=REMOTE_NAME, help="The git remote URL repository to deploy to.")
    parser.add_argument("--set-default", action="store_true", default=False, help="Set this version as the default.")
    parser.add_argument(
        "--no-push", dest="push", default=True, action="store_false", help="Disable pushing to the remote repository."
    )
    parser.add_argument("--branch", default=DEFAULT_TARGET_BRANCH, help="The branch to deploy to.")

    parsed_args = parser.parse_args()

    run(
        version=parsed_args.version,
        aliases=parsed_args.aliases,
        set_default=parsed_args.set_default,
        push=parsed_args.push,
        target_branch=parsed_args.branch,
        remote_name=parsed_args.remote,
    )


if __name__ == "__main__":
    main()
    sys.exit(0)
