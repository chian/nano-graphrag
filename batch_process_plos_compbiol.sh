#!/bin/bash

# Batch Processing Script for PLOS Computational Biology Papers
# Runs the contrastive QA generation pipeline on all papers

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR="/Users/chia/Documents/ANL/BioData/cognee/nano-graphrag"
PAPERS_DIR="$BASE_DIR/plos_compbiol_papers"
LOG_FILE="$BASE_DIR/batch_plos_compbiol.log"

# Pipeline parameters
DOMAIN="molecular_biology"
MAX_PAPERS=20
ENRICH_INFO_PIECES=30
ENRICH_GRAPH_DEPTH=10
SAMPLE_NODES=50
NUM_QUESTIONS=20

# Processing options
LIMIT="${LIMIT:-}"  # Can be set via environment variable or here
START_FROM=""  # Set to a paper filename to resume from

# =============================================================================
# SCRIPT LOGIC
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Counters
TOTAL_PROCESSED=0
TOTAL_SUCCESS=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0

log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}[$timestamp]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${GREEN}[$timestamp] ✓${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${RED}[$timestamp] ✗${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${YELLOW}[$timestamp] ⚠${NC} $1" | tee -a "$LOG_FILE"
}

# Process a single paper
process_paper() {
    local paper_path="$1"
    local paper_name=$(basename "$paper_path" .txt)

    log "Processing: $paper_name"

    # Check if output already exists
    local output_dir="$PAPERS_DIR/.qa_output/$paper_name/$DOMAIN"
    local output_file="$output_dir/contrastive_qa.json"

    if [ -f "$output_file" ]; then
        log_warning "Output already exists, skipping: $paper_name"
        ((TOTAL_SKIPPED++))
        return 0
    fi

    # Run pipeline
    cd "$BASE_DIR"
    python run_contrastive_pipeline.py "$paper_path" \
        --domain "$DOMAIN" \
        --max-papers "$MAX_PAPERS" \
        --num-questions "$NUM_QUESTIONS" \
        --enrich-info-pieces "$ENRICH_INFO_PIECES" \
        --enrich-graph-depth "$ENRICH_GRAPH_DEPTH" \
        --sample-nodes "$SAMPLE_NODES" \
        --skip-assessment \
        2>&1 | tee -a "$LOG_FILE"

    local exit_code=${PIPESTATUS[0]}

    if [ $exit_code -eq 0 ]; then
        log_success "Completed: $paper_name"
        ((TOTAL_SUCCESS++))
        return 0
    else
        log_error "Failed: $paper_name (exit code: $exit_code)"
        ((TOTAL_FAILED++))
        return 1
    fi
}

show_config() {
    log "PLOS Computational Biology Batch Processing"
    log "============================================"
    log "  Papers directory: $PAPERS_DIR"
    log "  Domain: $DOMAIN"
    log "  Max Firecrawl papers: $MAX_PAPERS"
    log "  Enrich info pieces: $ENRICH_INFO_PIECES"
    log "  Enrich graph depth: $ENRICH_GRAPH_DEPTH"
    log "  Sample nodes: $SAMPLE_NODES"
    log "  Num questions: $NUM_QUESTIONS"
    log "  Log file: $LOG_FILE"
    [ -n "$LIMIT" ] && log "  Limit: $LIMIT papers"
    [ -n "$START_FROM" ] && log "  Start from: $START_FROM"
    log ""
}

show_summary() {
    log ""
    log "=========================================="
    log "BATCH PROCESSING SUMMARY"
    log "=========================================="
    log "Total Processed: $TOTAL_PROCESSED"
    log "Successful: $TOTAL_SUCCESS"
    log "Failed: $TOTAL_FAILED"
    log "Skipped: $TOTAL_SKIPPED"
    if [ $((TOTAL_PROCESSED - TOTAL_SKIPPED)) -gt 0 ]; then
        log "Success Rate: $(( TOTAL_SUCCESS * 100 / (TOTAL_PROCESSED - TOTAL_SKIPPED) ))%"
    fi
    log "=========================================="
}

main() {
    echo "=== PLOS CompBiol Batch Processing Started at $(date) ===" > "$LOG_FILE"

    show_config

    # Check papers directory
    if [ ! -d "$PAPERS_DIR" ]; then
        log_error "Papers directory not found: $PAPERS_DIR"
        exit 1
    fi

    # Count papers
    local total_papers=$(ls -1 "$PAPERS_DIR"/*.txt 2>/dev/null | wc -l)
    log "Found $total_papers papers to process"
    log ""

    # Track if we should start processing (for resume functionality)
    local should_process=1
    if [ -n "$START_FROM" ]; then
        should_process=0
    fi

    # Process papers
    for paper in "$PAPERS_DIR"/*.txt; do
        # Handle resume
        if [ -n "$START_FROM" ] && [ $should_process -eq 0 ]; then
            if [[ "$(basename "$paper")" == "$START_FROM"* ]]; then
                should_process=1
                log "Resuming from: $(basename "$paper")"
            else
                continue
            fi
        fi

        # Check limit
        if [ -n "$LIMIT" ] && [ $TOTAL_PROCESSED -ge $LIMIT ]; then
            log "Reached limit of $LIMIT papers"
            break
        fi

        process_paper "$paper"
        ((TOTAL_PROCESSED++))

        # Progress
        log "Progress: $TOTAL_PROCESSED (Success: $TOTAL_SUCCESS, Failed: $TOTAL_FAILED, Skipped: $TOTAL_SKIPPED)"
        log ""
    done

    show_summary
}

# Handle interrupts
trap 'log_error "Interrupted by user"; show_summary; exit 1' INT TERM

# Run
main "$@"
