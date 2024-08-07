#!/bin/bash

# Exclude regex to filter branches
exclude_regex='master|main|develop|release.*'

# List merged branches that are not excluded
merged_branches=$(git branch --merged develop | grep -Ev "${exclude_regex}" | sed 's/^[[:space:]]*//' | grep -v "^develop$")

# Print list of merged branches
echo "The following branches are merged and will be deleted:"
echo "$merged_branches"

# Ask user for confirmation
read -p "Are you sure you want to delete these branches? (y/n) Please note that this action is irreversible." -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    # Delete local branches
    git branch -d $(echo "$merged_branches")

    # Delete merged branches from remote
    git push --delete origin $(echo "$merged_branches")

    # Prune remote branches
    git remote prune origin
    
    echo "Branches deleted successfully."
else
    echo "Branch deletion aborted."
fi
