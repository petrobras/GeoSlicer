#!/bin/bash

branch="$1"
shift
ACCEPT_BRANCH_ROOT_ARRAY=( "$@" )

match=0
for root in "${ACCEPT_BRANCH_ROOT_ARRAY[@]}"; do
    if [[ "$branch" =~ "$root/"*"."*  ]]; then
        match=1
        break
    fi
done

if [[ $match == 0 ]]; then
    echo "This branch its not related to a release/hotfix/master branch. "$branch;
    exit 1
fi

exit 0