#!/bin/bash
if git grep -I --files-with-matches --perl-regexp '\r' HEAD -- *.py *.sh *.yml *.md; then
    echo "Error: Carriage return found"
    exit 1
fi
