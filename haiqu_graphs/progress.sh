#!/usr/bin/env bash
# Usage: bash haiqu_graphs/progress.sh [logfile]
LOG=${1:-haiqu_graphs/v1/build.log}

if [[ ! -f "$LOG" ]]; then
    echo "No log file at $LOG"
    exit 1
fi

echo "=== HAIQU Build Progress ==="
echo "Log: $LOG"
echo "Updated: $(date)"
echo ""

# Completed groups (have a SUMMARY line)
echo "--- Completed groups ---"
grep "→ haiqu_" "$LOG" | sed 's/^[[:space:]]*//' || echo "  (none yet)"

echo ""
echo "--- Current group ---"
# Last GROUP line
current_group=$(grep "^GROUP:" "$LOG" | tail -1 | awk '{print $2}')
echo "  $current_group"

# Last paper line
last_paper=$(grep -E "^\s+\[[0-9]+/[0-9]+\]" "$LOG" | tail -1 | sed 's/^[[:space:]]*//')
echo "  $last_paper"

# Last checkpoint
last_checkpoint=$(grep "checkpoint:" "$LOG" | tail -1 | sed 's/^[[:space:]]*//')
[[ -n "$last_checkpoint" ]] && echo "  $last_checkpoint"

# Last nodes line (final write for completed group)
last_nodes=$(grep "^\s*nodes:" "$LOG" | tail -1 | sed 's/^[[:space:]]*//')
[[ -n "$last_nodes" ]] && echo "  $last_nodes"

echo ""
echo "--- Errors ---"
chunk_fails=$(grep -c "chunk.*failed:" "$LOG" 2>/dev/null || echo 0)
filtered=$(grep -c "Filtered entity" "$LOG" 2>/dev/null || echo 0)
json_fails=$(grep -c "JSON parsing failed" "$LOG" 2>/dev/null || echo 0)
echo "  chunk failures: $chunk_fails"
echo "  filtered entities: $filtered"
echo "  JSON parse failures: $json_fails"
