#!/usr/bin/env bash
set -euo pipefail
cmd=$(python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))")
printf '%s %s\n' "$(date -Is)" "$cmd" >> .claude/command-log.txt
exit 0
