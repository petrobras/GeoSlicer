#!/bin/bash
# Script to wrapper the deploy_script.py execution through the docker container.
# The arguments will be passed to the deploy_script call, but it will check if the '--output-dir' argument exists.
# If the 'output-dir' argument doesn't exist, then the script will not execute.

ARGUMENTS=()
ARCHIVE=""
OUTPUT_DIR=""
BUILD_DOCKER=0
while test $# -gt 0; do
  case "$1" in
    -h|--help)
      echo "Deploy slicerltrace application script wrapper within a docker container. Use the same flags as used in the python script deploy_slicer.py and define the output directory."
      echo " "
      echo "$(basename "$0") [options] application [arguments]"
      echo " "
      echo "options:"
      echo "-h, --help                show brief help"
      echo "-b, --build               build docker image"
      echo "-o, --output-dir=DIR      specify a directory to store output in"
      exit 0
      ;;
     -o| --output-dir)
      shift
      if test $# -gt 0; then
        OUTPUT_DIR=$1
      fi
      shift
      ;;
     -b| --build)
      shift
      BUILD_DOCKER=1
      ;;

    *)
    if [[ -f $1 || -d $1 ]]; then
        ARCHIVE=$1
    else
        # Add unmatched arguments to the ARGUMENTS array
        ARGUMENTS+=("$1")
    fi
    shift
      ;;
  esac
done

ARGUMENTS="${ARGUMENTS[@]}"

# Function to determine if one path is relative to another
function test_path_relative {
    local base_path="$1"
    local target_path="$2"
    
    # Resolve absolute paths
    local resolved_base
    local resolved_target
    resolved_base=$(realpath "$base_path" 2>/dev/null)
    resolved_target=$(realpath "$target_path" 2>/dev/null)

    if [[ -z "$resolved_base" || -z "$resolved_target" ]]; then
        echo "false"
        return
    fi

    # Check if the target path starts with the base path
    if [[ "$resolved_target" == "$resolved_base"* ]]; then
        echo "true"
    else
        echo "false"
    fi
}

# Function to get the mount path for a given path.
# It avoids drives other than '/c' due to Docker container limitation
function get_mount_path {
    local path="$1"

    local mount_path="$path"
    if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* || "$OSTYPE" == "win32"* ]]; then
      if [[ "$(test_path_relative 'C:' "$path")" != "true" ]]; then
          local drive
          drive=$(echo "$path" | awk -F':' '{print $1}')
          mount_path="${path//${drive}:/C:}"
      fi
    fi

    echo "$mount_path"
}

# Function to retrieve only the unique paths from the path list, also considering the relative paths
function get_unique_paths {
    local paths=("$@")
    local sorted_paths=($(printf "%s\n" "${paths[@]}" | sort -u))
    local unique_paths=()

    for current_path in "${sorted_paths[@]}"; do
        local is_relative="false"

        for unique_path in "${unique_paths[@]}"; do
            if [[ "$(test_path_relative "$unique_path" "$current_path")" == "true" ]]; then
                is_relative="true"
                break
            fi
        done

        if [[ "$is_relative" == "false" ]]; then
            unique_paths+=("$current_path")
        fi
    done

    echo "${unique_paths[@]}"
}

if [[ -z ${OUTPUT_DIR} ]]; then
    echo "The argument '--output-dir' is missing."
    exit 1
fi

# Check for docker compose installation
docker compose &>/dev/null

DOCKER_COMPOSE_ALIAS=""
if [ $? -eq 0 ]; then
    DOCKER_COMPOSE_ALIAS="docker compose"
else # Check for docker-compose instead
    docker-compose &>/dev/null
    if [ $? -eq 0 ]; then
        DOCKER_COMPOSE_ALIAS="docker-compose"
    else
        echo "Docker compose is not installed. Please install it and try again."
        exit 2
    fi
fi

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    DOCKER_SERVICE_NAME="slicerltrace-linux"
elif [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* || "$OSTYPE" == "win32"* ]]; then
    DOCKER_SERVICE_NAME="slicerltrace-windows"
else
    echo "Unsupported operating system: $OSTYPE" >&2
    exit 3
fi

echo "Output Directory: $OUTPUT_DIR"
echo "Build Docker: $BUILD_DOCKER"
echo "Archive: $ARCHIVE"
echo "Arguments: $ARGUMENTS"

if [ $BUILD_DOCKER -eq 1 ]; then
  echo "Docker build flag is set. Proceeding with the Docker image build..."
  ${DOCKER_COMPOSE_ALIAS} build ${DOCKER_SERVICE_NAME}
fi

if [ $? -ne 0 ]; then
    echo "Failed to build the docker image. Check the logs and try again."
    exit 4
fi

REPO_PATH=$(git rev-parse --show-toplevel 2>/dev/null)

if [ $? -ne 0 ]; then
  echo "Error: This script must be run inside a Git repository." >&2
  exit 5
fi

ARCHIVE_PARENT_DIR=$(dirname "$ARCHIVE")

REPO_PATH=$(realpath "$REPO_PATH" 2>/dev/null)
OUTPUT_DIR=$(realpath "$OUTPUT_DIR" 2>/dev/null)
ARCHIVE_PARENT_DIR=$(realpath "$ARCHIVE_PARENT_DIR" 2>/dev/null)

if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* || "$OSTYPE" == "win32"* ]]; then
 REPO_PATH="${REPO_PATH//\\//}"
 OUTPUT_DIR="${OUTPUT_DIR//\\//}"
 ARCHIVE_PARENT_DIR="${ARCHIVE_PARENT_DIR//\\//}"
fi

# Define mounted paths
MOUNTED_REPO_PATH=$(get_mount_path "$REPO_PATH") # Call the `get_mount_path` function
MOUNTED_OUTPUT_DIR_PATH=$(get_mount_path "$OUTPUT_DIR")
MOUNTED_ARCHIVE_PATH=$(get_mount_path "$ARCHIVE_PARENT_DIR")
MOUNTED_ARCHIVE_FILE_PATH=$ARCHIVE

if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* || "$OSTYPE" == "win32"* ]]; then
  # Avoid long path problems in windows
  MOUNTED_OUTPUT_DIR_PATH="C:/output/"
  MOUNTED_ARCHIVE_PATH="C:/archive/"
  ARCHIVE_FILE_NAME=$(basename "$ARCHIVE")
  MOUNTED_ARCHIVE_FILE_PATH="${MOUNTED_ARCHIVE_PATH}${ARCHIVE_FILE_NAME}"
fi

declare -A VOLUME_PATHS_MAP

VOLUME_PATHS_MAP["${REPO_PATH}"]="$MOUNTED_REPO_PATH"
VOLUME_PATHS_MAP["${OUTPUT_DIR}"]="$MOUNTED_OUTPUT_DIR_PATH"
VOLUME_PATHS_MAP["${ARCHIVE_PARENT_DIR}"]="$MOUNTED_ARCHIVE_PATH"

VOLUME_PATHS=(
    "$REPO_PATH" 
    "$OUTPUT_DIR" 
    "$ARCHIVE_PARENT_DIR"
)

# Remove duplicate paths (get unique paths)
UNIQUE_VOLUME_PATHS=($(get_unique_paths "${VOLUME_PATHS[@]}"))

# Construct the string for the volume arguments
VOLUME_ARGS=()
for path in "${UNIQUE_VOLUME_PATHS[@]}"; do
    MOUNT_PATH=${VOLUME_PATHS_MAP["$path"]}
    VOLUME_ARGS+=("--volume ${path}:${MOUNT_PATH}")
done

VOLUME_ARGS="${VOLUME_ARGS[@]}"

# Run the Docker Compose command
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  ${DOCKER_COMPOSE_ALIAS} run --rm -T \
    --user $(id -u):$(id -g) \  
    --env PYTHONUNBUFFERED=1 \
    ${VOLUME_ARGS} \
    ${DOCKER_SERVICE_NAME} \
    python ${MOUNTED_REPO_PATH}/tools/deploy/deploy_slicer.py ${MOUNTED_ARCHIVE_FILE_PATH} ${ARGUMENTS} --output-dir ${MOUNTED_OUTPUT_DIR_PATH}
else
  echo "command is ${DOCKER_COMPOSE_ALIAS} run --rm -T ${VOLUME_ARGS} --env PYTHONUNBUFFERED=1 ${DOCKER_SERVICE_NAME} python ${MOUNTED_REPO_PATH}/tools/deploy/deploy_slicer.py ${MOUNTED_ARCHIVE_FILE_PATH} ${ARGUMENTS} --output-dir ${MOUNTED_OUTPUT_DIR_PATH}"
  ${DOCKER_COMPOSE_ALIAS} run --rm -T \
    ${VOLUME_ARGS} \
    --env PYTHONUNBUFFERED=1 \
    ${DOCKER_SERVICE_NAME} \
    python ${MOUNTED_REPO_PATH}/tools/deploy/deploy_slicer.py ${MOUNTED_ARCHIVE_FILE_PATH} ${ARGUMENTS} --output-dir ${MOUNTED_OUTPUT_DIR_PATH}
fi

if [ $? -ne 0 ]; then
    echo "Failed to run the deploy script. Check the logs and try again."
    exit 6
fi