#!/usr/bin/env bash
set -euo pipefail

URL=${1:-http://localhost:9000/parse}

if ! command -v jq >/dev/null 2>&1; then
  echo "This script requires 'jq' to build safe JSON payloads. Please install jq and try again."
  exit 1
fi

while IFS= read -r line || [ -n "$line" ]; do
  if [ -z "$line" ]; then
    continue
  fi
  echo "---- Message ----"
  echo "$line"
  # Build proper JSON safely with jq so control chars are escaped
  payload=$(jq -n --arg raw "$line" '{"raw": $raw}')
  response=$(curl -s -X POST "$URL" -H "Content-Type: application/json" -d "$payload")
  echo "$response" | jq
done < sample_fix_messages.txt
