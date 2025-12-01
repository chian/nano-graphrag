# Batch Processing Guide

This guide explains how to use the manifest-based batch processing system for running the contrastive QA generation pipeline on multiple papers.

## Quick Start

### 1. Generate a Manifest

Generate a manifest file listing all papers to process:

```bash
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology
```

This creates `manifest_mSystems_molecular_biology.json` with all papers in mSystems folder.

**Options:**
- `--output FILE`: Specify output manifest file
- `--limit N`: Only include first N papers
- `--exclude-existing`: Skip papers that already have `.qa_output` directory

### 2. View Manifest Statistics

Check how many papers and their status:

```bash
python manifest_utils.py stats manifest_mSystems_molecular_biology.json
```

Output shows pending/completed/failed counts and progress percentage.

### 3. Run Batch Pipeline

Process all papers in manifest:

```bash
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json
```

**Options:**
- `--start-from PAPER_ID`: Resume from specific paper (useful after interruptions)
- `--limit N`: Only process first N papers
- `--skip-assessment`: Skip suitability assessment
- `--skip-graph-creation`: Skip graph creation (use existing graphs)
- `--skip-query-generation`: Skip query generation
- `--skip-paper-fetching`: Skip Firecrawl paper fetching
- `--skip-graph-enrichment`: Skip graph enrichment

### 4. Manage Manifests

#### List papers in manifest:
```bash
python manifest_utils.py list manifest_mSystems_molecular_biology.json
```

Show with status filter:
```bash
python manifest_utils.py list manifest_mSystems_molecular_biology.json --status pending
python manifest_utils.py list manifest_mSystems_molecular_biology.json --status failed
```

#### Filter manifest to subset:
```bash
python manifest_utils.py filter manifest_mSystems_molecular_biology.json \
  --output manifest_subset.json \
  --limit 10
```

Keep only pending papers:
```bash
python manifest_utils.py filter manifest_mSystems_molecular_biology.json \
  --output manifest_pending.json \
  --status pending
```

#### Clean up completed papers:
```bash
python manifest_utils.py cleanup manifest_mSystems_molecular_biology.json \
  --output manifest_remaining.json \
  --remove-completed
```

## Common Workflows

### Process a Small Test Batch

```bash
# Generate manifest with only 5 papers
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --limit 5

# Run the batch
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json
```

### Resume After Interruption

If the batch runner is interrupted (Ctrl+C), the manifest is saved with current progress.

To resume:
```bash
# Check which papers failed
python manifest_utils.py list manifest_mSystems_molecular_biology.json --status failed

# Resume from specific paper
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json --start-from msystems_00403_22

# Or process only pending papers
python manifest_utils.py filter manifest_mSystems_molecular_biology.json \
  --output manifest_pending.json \
  --status pending

python run_batch_pipeline.py manifest_pending.json
```

### Process Multiple Domains

Create separate manifests for each domain:

```bash
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology
python manifest_utils.py generate ASM_595/mSystems --domain microbial_biology
python manifest_utils.py generate ASM_595/mSystems --domain infectious_disease
```

Run each:
```bash
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json &
python run_batch_pipeline.py manifest_mSystems_microbial_biology.json &
python run_batch_pipeline.py manifest_mSystems_infectious_disease.json &
```

### Skip Already-Processed Papers

Generate a new manifest that excludes papers where `.qa_output` already exists:

```bash
python manifest_utils.py generate ASM_595/mSystems \
  --domain molecular_biology \
  --exclude-existing
```

This only includes papers that haven't been processed yet.

### Remove Completed Entries from Manifest

After processing completes, clean up the manifest to only keep failed papers for review:

```bash
python manifest_utils.py cleanup manifest_mSystems_molecular_biology.json \
  --output manifest_failed_only.json \
  --remove-completed
```

## Manifest File Structure

A manifest JSON file contains:

```json
{
  "generated": "2025-12-01T12:00:00",
  "directory": "/path/to/ASM_595/mSystems",
  "domain": "molecular_biology",
  "total_papers": 210,
  "papers": [
    {
      "id": "msystems_00403_22",
      "path": "/full/path/to/paper.txt",
      "domain": "molecular_biology",
      "status": "pending",
      "attempts": 0,
      "last_error": null,
      "completed_at": null
    },
    ...
  ]
}
```

**Status values:**
- `pending`: Not yet processed
- `completed`: Successfully processed
- `failed`: Failed to process (check `last_error`)

## Output Structure

For each paper processed, outputs are saved in:

```
paper_directory/.qa_output/paper_name/domain/
├── graphs/
├── queries/
├── fetched_papers/
├── enriched_graphs/
├── contrastive_qa.json
└── pipeline_metadata.json
```

## Advanced Usage

### Chain Multiple Processing Steps

```bash
# Create initial manifest
python manifest_utils.py generate ASM_595/mSystems \
  --domain molecular_biology \
  --limit 50 \
  --output manifest_batch1.json

# Process first batch
python run_batch_pipeline.py manifest_batch1.json

# Clean up completed entries
python manifest_utils.py cleanup manifest_batch1.json \
  --output manifest_batch1_remaining.json \
  --remove-completed

# Process next batch
python run_batch_pipeline.py manifest_batch1_remaining.json
```

### Collect Statistics Across Multiple Manifests

```bash
# Check progress on each journal
python manifest_utils.py stats manifest_AAC_molecular_biology.json
python manifest_utils.py stats manifest_mSystems_molecular_biology.json
python manifest_utils.py stats manifest_mBio_molecular_biology.json
```

## Troubleshooting

### Pipeline Fails on Specific Paper

If a paper fails repeatedly:

1. Check the error: `python manifest_utils.py list manifest_file.json --status failed`
2. Run the pipeline manually on that paper to see full error:
   ```bash
   python run_contrastive_pipeline.py /path/to/paper.txt --domain molecular_biology
   ```
3. Fix the issue or exclude the paper by filtering the manifest

### Partial Processing

If you only want to process first N papers from a journal:

```bash
python manifest_utils.py generate ASM_595/mBio --domain molecular_biology --limit 20
python run_batch_pipeline.py manifest_mBio_molecular_biology.json
```

### Resume from Middle of Batch

If batch runner stops at paper 50 out of 200:

```bash
# Get the next paper ID from the list
python manifest_utils.py list manifest_file.json --status pending --limit 1

# Resume from there
python run_batch_pipeline.py manifest_file.json --start-from msystems_00451_22
```

## Notes

- **Manifest is updated after each paper**: If the batch runner is interrupted, the manifest file records progress automatically
- **No changes to pipeline scripts needed**: The batch system uses existing `run_contrastive_pipeline.py` without modifications
- **Parallel processing**: You can run multiple `run_batch_pipeline.py` commands in parallel on different manifests
- **Graceful interruption**: Press Ctrl+C to stop - the current manifest will be saved with all completed papers marked
