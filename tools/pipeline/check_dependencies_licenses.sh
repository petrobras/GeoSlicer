#!/bin/bash

repository_path=$( cd "$(dirname "$0")" ; pwd -P )\\..\\..
requirement_files=$(find ./src -iname "requirements.txt" -type f)

echo -e "\
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n\
%%%%%%% Starting dependencies license checking %%%%%%%%\n\
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n"


for requirement_file in $requirement_files; do
    module_name=$(basename $(dirname ${requirement_file}))
    echo "Checking licenses for '${module_name}' dependencies"
    echo -e "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n"
    python -m liccheck -r "${requirement_file}"
    exit_status=$?
    echo -e "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n"
    if [ "${exit_status}" -ne 0 ]; then
        echo -e "License checking failed for the following requirements file: ${requirement_file}"
        exit 1
    fi
done

echo -e "\
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n\
%%%%%%%%%%%% All licenses were validated! %%%%%%%%%%%%%\n\
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n"

exit 0