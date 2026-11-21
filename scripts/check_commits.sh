#!/usr/bin/env bash
# Commit hygiene for a range (default: origin/main..HEAD). See CONTRIBUTING.md.
#   - every non-merge subject is a Conventional Commit:  type(scope): summary
#   - commits over MAX_LINES changed lines get a warning (split by concern instead)
# With --subject "<text>" it checks only that one subject (CI uses it on the PR title, which
# becomes the squash-merge commit subject on main).
set -euo pipefail

MAX_LINES="${MAX_LINES:-300}"
TYPES="feat|fix|docs|ci|test|refactor|perf|build|chore|revert"
PATTERN="^($TYPES)(\([a-z0-9._-]+\))?!?: .{1,72}$"

if [ "${1:-}" = "--subject" ]; then
  if grep -Eq "$PATTERN" <<<"${2:-}"; then
    echo "subject OK: '${2}'"
    exit 0
  fi
  echo "::error::not a conventional subject: '${2:-}' (expected '<type>(<scope>): <summary>', type one of $TYPES)"
  exit 1
fi

RANGE="${1:-origin/main..HEAD}"

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
