#!/usr/bin/env bash
set -euo pipefail

git add .

if git diff --cached --quiet; then
  exit 0
fi

files=$(git diff --cached --name-only)
count=$(echo "$files" | wc -l | tr -d ' ')

if [ "$count" -eq 1 ]; then
  msg="hook: update $files"
elif [ "$count" -le 3 ]; then
  summary=$(echo "$files" | tr '\n' ',' | sed 's/,$//' | sed 's/,/, /g')
  msg="hook: update $summary"
else
  first=$(echo "$files" | head -1)
  rest=$((count - 1))
  msg="hook: update $first and $rest others"
fi

git commit -m "$msg"
exit 0
