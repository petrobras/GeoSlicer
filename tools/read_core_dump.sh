#!/bin/bash

if [ $# -ne 2 ]; then
    echo "Helper script to analyse the core dump file from GeoSlicer application generated from the CI/CD pipeline builds"
    echo "Usage: $0 <application_folder_path> <core_dump_file_path>"
    echo ""
    echo "<application_folder_path> is the GeoSlicer application directory path"
    echo "<core_dump_file_path> is the core dump file path"
    exit 1
fi

APP_FOLDER=$(realpath "$1")
CORE_DUMP_FILE_PATH=$(realpath "$2")
CORE_DUMP_FOLDER_PATH=$(dirname "$CORE_DUMP_FILE_PATH")
APP_BINARY_RELATIVE_PATH="bin/GeoSlicerApp-real"

# Validate application binary
if [ -z "${APP_FOLDER}/${APP_BINARY_RELATIVE_PATH}" ]; then
    echo "❌ No executable binary found in $APP_FOLDER!"
    exit 1
fi

echo "Setting up debugging environment..."

DOCKER_COMPOSE_ALIAS=""
DOCKER_COMPOSE_SERVICE="slicerltrace-linux"
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

echo "🗂  Application folder: ${APP_FOLDER}"
echo "💀 Core dump file: ${CORE_DUMP_FILE_PATH}"
echo "🚀 Using binary: ${APP_FOLDER}/${APP_BINARY_RELATIVE_PATH}"
echo ""
echo ""
echo "✅ Starting debugging!"
echo "⌛ Loading the core dump file might take a while..."


# Use metadata if available
METADATA_FILE_PATH="${CORE_DUMP_FOLDER_PATH}/metadata.json"
if [ ! -f "$METADATA_FILE_PATH" ]; then
    ${DOCKER_COMPOSE_ALIAS} run --rm -i \
        --volume "$APP_FOLDER:/app" \
        --volume "$CORE_DUMP_FILE_PATH:/core" \
        ${DOCKER_COMPOSE_SERVICE} \
        bash -c "
            gdb /app/${APP_BINARY_RELATIVE_PATH} -c /core
        "
else
    METADATA_HASH=$(jq -r '.hash' "$METADATA_FILE_PATH")
    METADATA_BASE=$(jq -r '.base' "$METADATA_FILE_PATH")
    APPLICATION_SOURCE_PATH="/root/gs${METADATA_HASH}/${METADATA_BASE}"
    ${DOCKER_COMPOSE_ALIAS} run --rm -i \
        --volume "$APP_FOLDER:/app" \
        --volume "$CORE_DUMP_FILE_PATH:/core" \
        ${DOCKER_COMPOSE_SERVICE}  \
        /bin/bash -c "
            mkdir -p $APPLICATION_SOURCE_PATH && \
            ln -sf /app/* $APPLICATION_SOURCE_PATH && \
            gdb /app/${APP_BINARY_RELATIVE_PATH} -c /core \
        "
fi

exit 0

