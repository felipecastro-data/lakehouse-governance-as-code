#!/usr/bin/env bash
# Commit hygiene for a range (default: origin/main..HEAD). See CONTRIBUTING.md.
#   - every non-merge subject is a Conventional Commit:  type(scope): summary
#   - commits over MAX_LINES changed lines get a warning (split by concern instead)
set -euo pipefail

RANGE="${1:-origin/main..HEAD}"
MAX_LINES="${MAX_LINES:-500}"
TYPES="feat|fix|docs|ci|test|refactor|perf|build|chore|revert"
PATTERN="^($TYPES)(\([a-z0-9._-]+\))?!?: .{1,72}$"

status=0
while IFS=$'\t' read -r sha subject; do
  [ -z "$sha" ] && continue
  if ! grep -Eq "$PATTERN" <<<"$subject"; then
    echo "::error::$sha is not a conventional commit: '$subject' (expected '<type>(<scope>): <summary>', type one of $TYPES)"
    status=1
  fi
  lines=$(git show --numstat --format= "$sha" -- . ':(exclude)docs/generated' ':(exclude)*.png' \
          | awk '{a+=$1; d+=$2} END {print a+d+0}')
  if [ "$lines" -gt "$MAX_LINES" ]; then
    echo "::warning::$sha changes $lines lines (> $MAX_LINES): '$subject'. Split it by concern."
  fi
done < <(git log --no-merges --format='%h%x09%s' "$RANGE")

[ "$status" -eq 0 ] && echo "commit subjects OK ($RANGE)"
exit "$status"
