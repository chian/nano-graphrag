#!/bin/bash

# Batch Processing Script for ASM Papers with GASL Reasoning QA Generation
# This script processes multiple ASM papers and generates reasoning questions using GASL

# =============================================================================
# CONFIGURATION - EDIT THESE PARAMETERS AS NEEDED
# =============================================================================

# Base directories
BASE_DIR="/Users/chia/Documents/ANL/BioData/cognee/nano-graphrag"
ASM_PAPERS_DIR="/Users/chia/Documents/ANL/BioData/Argonium.nosync/ASM_595"

# Processing options
PROCESSING_MODE="sequential"  # Options: "sequential" or "parallel"
MAX_PARALLEL_JOBS=4          # Only used if PROCESSING_MODE="parallel"

# Conda environment should be activated before running this script

# GraphRAG processing is handled automatically by the QA generation scripts
# No need to call gasl_main.py directly

# Entity type generation task/prompt - CUSTOMIZE THIS
ENTITY_TASK_PROMPT="Study molecular biology, microbiology, and biochemistry concepts. Analyze scientific research on bacterial mechanisms, viral processes, and microbial ecology."

# GASL Reasoning question generation parameters - CUSTOMIZE THESE
GASL_REASONING_SCRIPT="$BASE_DIR/generate_reasoning_qa_gasl.py"
GASL_REASONING_NUM_QUESTIONS=10   # Number of reasoning questions to generate per paper
GASL_REASONING_OUTPUT_FILE="reasoning_qa_gasl.json"  # Output file for GASL reasoning questions

# Logging and output
LOG_FILE="$BASE_DIR/batch_processing_asm_gasl.log"

# Paper selection
SPECIFIC_JOURNAL="AAC"  # Set to specific journal name (e.g., "AEM", "JB") to process only that journal, or leave empty to process all
SPECIFIC_PAPER_ZIP=""  # Set to specific paper zip file path to process only that paper, or leave empty to process all

# =============================================================================
# SCRIPT LOGIC - NO NEED TO EDIT BELOW THIS LINE
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Initialize counters
TOTAL_PROCESSED=0
TOTAL_SUCCESS=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0

# Logging functions
log() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}[$timestamp]${NC} $message" | tee -a "$LOG_FILE"
}

log_success() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${GREEN}[$timestamp] ✓${NC} $message" | tee -a "$LOG_FILE"
}

log_warning() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${YELLOW}[$timestamp] ⚠${NC} $message" | tee -a "$LOG_FILE"
}

log_error() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${RED}[$timestamp] ✗${NC} $message" | tee -a "$LOG_FILE"
}

# Function to extract paper ID from zip filename
get_paper_id() {
    local zip_file="$1"
    basename "$zip_file" .zip
}

# Function to process a single paper
process_paper() {
    local zip_file="$1"
    local paper_id=$(get_paper_id "$zip_file")
    local journal_dir=$(dirname "$zip_file")
    local journal_name=$(basename "$journal_dir")
    
    log "Processing paper: $paper_id (Journal: $journal_name)"
    
    # Check if zip file exists
    if [ ! -f "$zip_file" ]; then
        log_error "Zip file does not exist: $zip_file"
        ((TOTAL_FAILED++))
        return 1
    fi
    
    # Create working directory for this paper
    local work_dir="$journal_dir/$paper_id"
    mkdir -p "$work_dir"
    
    # Extract zip file (only if directory doesn't exist or is empty)
    if [ ! -d "$work_dir" ] || [ -z "$(ls -A "$work_dir" 2>/dev/null)" ]; then
        log "Extracting $zip_file to $work_dir"
        if ! unzip -q "$zip_file" -d "$work_dir"; then
            log_error "Failed to extract $zip_file"
            ((TOTAL_FAILED++))
            return 1
        fi
    else
        log "Directory $work_dir already exists and is not empty, skipping extraction"
    fi
    
    # Navigate to work directory
    cd "$work_dir"
    
    # Check for text files, extract PDFs if needed
    local text_files=$(find . -name "*.txt" -type f)
    if [ -z "$text_files" ]; then
        log "No text files found, checking for PDFs to extract..."
        
        # Find PDFs in the extracted content
        local pdf_files=$(find . -name "*.pdf" -type f)
        if [ -z "$pdf_files" ]; then
            log_error "No PDF files found in extracted content for $paper_id"
            ((TOTAL_FAILED++))
            return 1
        fi
        
        # Create source_files directory structure expected by extract_pdfs_to_text.py
        local source_files_dir="source_files"
        mkdir -p "$source_files_dir"
        
        # Copy main PDF to source_files directory
        local main_pdf=$(find . -name "*.pdf" -type f | grep -v suppl | head -1)
        if [ -n "$main_pdf" ]; then
            cp "$main_pdf" "$source_files_dir/"
            log "Copied main PDF to source_files directory: $(basename "$main_pdf")"
        else
            # If no main PDF found, copy the first PDF
            local first_pdf=$(find . -name "*.pdf" -type f | head -1)
            cp "$first_pdf" "$source_files_dir/"
            log "Copied first PDF to source_files directory: $(basename "$first_pdf")"
        fi
        
        # Extract PDFs to text
        log "Extracting PDFs to text files..."
        cd "$BASE_DIR"
        if python extract_pdfs_to_text.py --input-dir "$work_dir"; then
            log_success "PDF extraction completed for $paper_id"
            cd "$work_dir"
        else
            log_error "PDF extraction failed for $paper_id"
            cd "$BASE_DIR"
            ((TOTAL_FAILED++))
            return 1
        fi
        
        # Check again for text files
        text_files=$(find . -name "*.txt" -type f)
        if [ -z "$text_files" ]; then
            log_error "No text files found after PDF extraction for $paper_id"
            ((TOTAL_FAILED++))
            return 1
        fi
    else
        log "Text files found, proceeding with graph creation"
    fi
    
    local text_count=$(echo $text_files | wc -w)
    log "Found $text_count text file(s) in $paper_id"
    
    # Create necessary directories
    mkdir -p graphrag_cache
    mkdir -p graph_versions
    
    # Step 1: Create knowledge graph
    log "Starting knowledge graph creation for $paper_id..."
    
    # Find the subdirectory where text files are located (handles variable structure)
    text_dir=$(find . -name "*.txt" -type f | head -1 | xargs dirname)
    if [ -z "$text_dir" ]; then
        log_error "No text files found in extracted directory"
        return 1
    fi
    
    # Store the working subdirectory path (absolute path)
    working_subdir="$work_dir/$text_dir"
    log "Graph working directory: $working_subdir"
    
    # Create graph using create_graph_only.py
    log "Creating knowledge graph with entity task prompt..."
    
    # Change to base directory so prompts/ can be found, then call with relative path
    cd "$BASE_DIR"
    if python create_graph_only.py --source-dir "$working_subdir" --entity-prompt "$ENTITY_TASK_PROMPT"; then
        log_success "Knowledge graph created successfully for $paper_id"
    else
        log_error "Graph creation failed for $paper_id"
        cd "$BASE_DIR"  # Make sure we're back at base
        ((TOTAL_FAILED++))
        return 1
    fi
    
    # Step 2: Generate GASL reasoning questions (run from base directory like debug script)
    log "Generating GASL reasoning questions for $paper_id..."
    
    # Run from base directory so prompts/ can be found
    cd "$BASE_DIR"
    if python "$GASL_REASONING_SCRIPT" --working-dir "$working_subdir" --output-file "$work_dir/$GASL_REASONING_OUTPUT_FILE" --num-questions "$GASL_REASONING_NUM_QUESTIONS"; then
        # Check if output file was actually created
        if [ -f "$work_dir/$GASL_REASONING_OUTPUT_FILE" ]; then
            log_success "GASL reasoning questions generated for $paper_id"
        else
            log_error "GASL reasoning questions script completed but output file not found: $work_dir/$GASL_REASONING_OUTPUT_FILE"
            ((TOTAL_FAILED++))
            return 1
        fi
    else
        log_error "GASL reasoning question generation failed for $paper_id"
        ((TOTAL_FAILED++))
        return 1
    fi
    
    # Return to base directory
    cd "$BASE_DIR"
    
    log_success "Completed processing: $paper_id"
    ((TOTAL_SUCCESS++))
    return 0
}

# Function to process papers in parallel
process_papers_parallel() {
    local max_parallel="$1"
    local papers=()
    
    # Collect papers to process
    if [ -n "$SPECIFIC_PAPER_ZIP" ]; then
        log "Processing specific paper: $SPECIFIC_PAPER_ZIP"
        if [ -f "$SPECIFIC_PAPER_ZIP" ]; then
            papers=("$SPECIFIC_PAPER_ZIP")
        else
            log_error "Specified paper zip file does not exist: $SPECIFIC_PAPER_ZIP"
            exit 1
        fi
    elif [ -n "$SPECIFIC_JOURNAL" ]; then
        log "Processing all papers in journal: $SPECIFIC_JOURNAL"
        while IFS= read -r -d '' zip_file; do
            papers+=("$zip_file")
        done < <(find "$ASM_PAPERS_DIR/$SPECIFIC_JOURNAL" -name "*.zip" -type f -print0 | sort -z)
    else
        log "Processing all papers in all journals"
        while IFS= read -r -d '' zip_file; do
            papers+=("$zip_file")
        done < <(find "$ASM_PAPERS_DIR" -name "*.zip" -type f -not -path "*/AAC/*" -print0 | sort -z)
    fi
    
    local total_papers=${#papers[@]}
    log "Starting parallel processing of $total_papers papers (max $max_parallel parallel jobs)"
    
    # Process papers in parallel
    for zip_file in "${papers[@]}"; do
        # Wait if we have too many parallel jobs
        while [ $(jobs -r | wc -l) -ge $max_parallel ]; do
            sleep 1
        done
        
        # Process paper in background
        (
            if process_paper "$zip_file"; then
                echo "SUCCESS:$(get_paper_id "$zip_file")"
            else
                echo "FAILED:$(get_paper_id "$zip_file")"
            fi
        ) &
        
        ((TOTAL_PROCESSED++))
    done
    
    # Wait for all background jobs to complete
    wait
    
    log "All parallel processing completed"
}

# Function to process papers sequentially
process_papers_sequential() {
    local papers=()
    
    # Collect papers to process
    if [ -n "$SPECIFIC_PAPER_ZIP" ]; then
        log "Processing specific paper: $SPECIFIC_PAPER_ZIP"
        if [ -f "$SPECIFIC_PAPER_ZIP" ]; then
            papers=("$SPECIFIC_PAPER_ZIP")
        else
            log_error "Specified paper zip file does not exist: $SPECIFIC_PAPER_ZIP"
            exit 1
        fi
    elif [ -n "$SPECIFIC_JOURNAL" ]; then
        log "Processing all papers in journal: $SPECIFIC_JOURNAL"
        while IFS= read -r -d '' zip_file; do
            papers+=("$zip_file")
        done < <(find "$ASM_PAPERS_DIR/$SPECIFIC_JOURNAL" -name "*.zip" -type f -print0 | sort -z)
    else
        log "Processing all papers in all journals"
        while IFS= read -r -d '' zip_file; do
            papers+=("$zip_file")
        done < <(find "$ASM_PAPERS_DIR" -name "*.zip" -type f -not -path "*/AAC/*" -print0 | sort -z)
    fi
    
    local total_papers=${#papers[@]}
    log "Starting sequential processing of $total_papers papers"
    
    # Process each paper
    for zip_file in "${papers[@]}"; do
        process_paper "$zip_file"
        ((TOTAL_PROCESSED++))
        
        # Progress update
        log "Progress: $TOTAL_PROCESSED/$total_papers (Success: $TOTAL_SUCCESS, Failed: $TOTAL_FAILED, Skipped: $TOTAL_SKIPPED)"
    done
    
    log "Sequential processing completed"
}

# Function to show configuration
show_config() {
    log "ASM Papers GASL Batch Processing Configuration:"
    log "  Base Directory: $BASE_DIR"
    log "  ASM Papers Directory: $ASM_PAPERS_DIR"
    log "  Processing Mode: $PROCESSING_MODE"
    if [ "$PROCESSING_MODE" = "parallel" ]; then
        log "  Max Parallel Jobs: $MAX_PARALLEL_JOBS"
    fi
    log "  GASL Reasoning Script: $GASL_REASONING_SCRIPT"
    log "  GASL Reasoning Questions per Paper: $GASL_REASONING_NUM_QUESTIONS"
    log "  GASL Reasoning Output File: $GASL_REASONING_OUTPUT_FILE"
    log "  Log File: $LOG_FILE"
    if [ -n "$SPECIFIC_JOURNAL" ]; then
        log "  Specific Journal: $SPECIFIC_JOURNAL"
    fi
    if [ -n "$SPECIFIC_PAPER_ZIP" ]; then
        log "  Specific Paper: $SPECIFIC_PAPER_ZIP"
    fi
    log ""
}

# Function to show final summary
show_summary() {
    log "=========================================="
    log "ASM GASL BATCH PROCESSING SUMMARY"
    log "=========================================="
    log "Total Processed: $TOTAL_PROCESSED"
    log "Successful: $TOTAL_SUCCESS"
    log "Failed: $TOTAL_FAILED"
    log "Skipped: $TOTAL_SKIPPED"
    if [ $((TOTAL_PROCESSED - TOTAL_SKIPPED)) -gt 0 ]; then
        log "Success Rate: $(( TOTAL_SUCCESS * 100 / (TOTAL_PROCESSED - TOTAL_SKIPPED) ))%"
    else
        log "Success Rate: N/A (no papers processed)"
    fi
    log "Log File: $LOG_FILE"
    log "=========================================="
}

# Main script logic
main() {
    # Initialize log file
    echo "=== ASM Papers GASL Batch Processing Started at $(date) ===" > "$LOG_FILE"
    
    log "ASM Papers GASL Batch Processing Script"
    log "======================================"
    
    # Conda environment should be activated before running this script
    log "Using inherited conda environment"
    
    # Check if ASM papers directory exists
    if [ ! -d "$ASM_PAPERS_DIR" ]; then
        log_error "ASM papers directory does not exist: $ASM_PAPERS_DIR"
        exit 1
    fi
    
    # Show configuration
    show_config
    
    # Start processing
    log "Starting batch processing..."
    
    if [ "$PROCESSING_MODE" = "parallel" ]; then
        process_papers_parallel "$MAX_PARALLEL_JOBS"
    else
        process_papers_sequential
    fi
    
    # Show final summary
    show_summary
}

# Handle script interruption
trap 'log_error "Script interrupted by user"; show_summary; exit 1' INT TERM

# Run main function
main "$@"
