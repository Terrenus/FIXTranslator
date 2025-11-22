#!/usr/bin/env bash
set -euo pipefail

URL=${1:-http://localhost:9000/parse}
API_KEYS=${API_KEYS:-}  # optionally set via environment variable

if ! command -v jq >/dev/null 2>&1; then
  echo "This script requires 'jq' to build safe JSON payloads. Please install jq and try again."
  exit 1
fi

if [ -z "$API_KEYS" ]; then
  echo "Warning: No API key provided. You can set it via:"
  echo "  export API_KEYS=your_key_here"
  echo "or pass it inline:"
  echo "  API_KEYS=your_key_here ./validate.sh"
fi

while IFS= read -r line || [ -n "$line" ]; do
  if [ -z "$line" ]; then
    continue
  fi
  echo "---- Message ----"
  echo "$line"

  # Build proper JSON safely with jq so control chars are escaped
  payload=$(jq -n --arg raw "$line" '{"raw": $raw}')

  # Include API key header only if provided
  if [ -n "$API_KEYS" ]; then
    response=$(curl -s -X POST "$URL" \
      -H "Content-Type: application/json" \
      -H "x-api-key: $API_KEYS" \
      -d "$payload")
  else
    response=$(curl -s -X POST "$URL" \
      -H "Content-Type: application/json" \
      -d "$payload")
  fi

  echo "$response" | jq
done < sample_fix_messages.txt
