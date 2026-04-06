#!/usr/bin/env bash
# Reminder hook: prints a note if there are uncommitted changes.
# Does NOT commit automatically — leaves that to Claude's judgment.

unstaged=$(git diff --name-only 2>/dev/null)
untracked=$(git ls-files --others --exclude-standard 2>/dev/null)

if [ -n "$unstaged" ] || [ -n "$untracked" ]; then
  echo "Reminder: there are uncommitted changes. Commit if the work reached a logical stopping point."
fi

exit 0
