# Manifest System Summary

A complete batch processing system for managing large-scale contrastive QA generation across multiple papers.

## Files Created

### 1. `manifest_utils.py`
Utility library for manifest management with CLI interface.

**Commands:**
- `generate`: Create manifest from directory
- `stats`: Show processing statistics
- `list`: List papers in manifest
- `filter`: Create subset of manifest
- `cleanup`: Remove completed papers

### 2. `run_batch_pipeline.py`
Main batch runner that processes papers sequentially from a manifest.

**Features:**
- Graceful interrupt handling (Ctrl+C)
- Automatic progress saving after each paper
- Resume from any paper with `--start-from`
- All skip flags supported from main pipeline

### 3. `BATCH_PROCESSING.md`
Complete usage guide with examples and workflows.

## Key Features

✅ **Resumable**: Manifest saved after each paper - interrupted runs can resume
✅ **Traceable**: Each paper's status (pending/completed/failed) tracked
✅ **Flexible**: Generate subsets, filter by status, exclude already-processed papers
✅ **Minimal Changes**: Uses existing `run_contrastive_pipeline.py` unchanged
✅ **Scalable**: Handles 5 papers or 5000 papers identically
✅ **Observable**: Real-time progress, statistics, and error tracking

## Quick Reference

### Generate Manifest
```bash
# All papers in mSystems
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology

# First 10 papers only
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --limit 10

# Exclude already-processed papers
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --exclude-existing
```

### Check Progress
```bash
python manifest_utils.py stats manifest_mSystems_molecular_biology.json
```

### Run Batch
```bash
# Process all papers
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json

# Resume from paper 50
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json --start-from msystems_00451_22

# Process only first 20
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json --limit 20
```

### Manage Manifests
```bash
# List papers with their status
python manifest_utils.py list manifest_mSystems_molecular_biology.json

# Show only failed papers
python manifest_utils.py list manifest_mSystems_molecular_biology.json --status failed

# Create new manifest with only pending papers
python manifest_utils.py filter manifest_mSystems_molecular_biology.json \
  --output pending_only.json \
  --status pending
```

## Workflow Examples

### Example 1: Test Run with 5 Papers
```bash
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --limit 5 --output test_manifest.json
python run_batch_pipeline.py test_manifest.json
```

### Example 2: Large Batch with Resume Capability
```bash
# Create manifest for all mSystems papers
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology

# Start processing (can be interrupted)
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json

# If interrupted, check status
python manifest_utils.py stats manifest_mSystems_molecular_biology.json

# Resume from where it stopped
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json --start-from next_paper_id
```

### Example 3: Multiple Domains in Parallel
```bash
# Create manifests for different domains
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology
python manifest_utils.py generate ASM_595/mSystems --domain microbial_biology
python manifest_utils.py generate ASM_595/mSystems --domain infectious_disease

# Run all in parallel
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json &
python run_batch_pipeline.py manifest_mSystems_microbial_biology.json &
python run_batch_pipeline.py manifest_mSystems_infectious_disease.json &
wait
```

### Example 4: Skip Already-Processed Papers
```bash
# After initial run, create new manifest excluding completed papers
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --exclude-existing

# Run on remaining papers
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json
```

### Example 5: Clean Up and Re-process Failures
```bash
# Save only failed papers for review
python manifest_utils.py cleanup manifest_mSystems_molecular_biology.json \
  --output failed_only.json \
  --remove-completed

# View failed papers
python manifest_utils.py list failed_only.json --status failed

# Re-run only failed papers
python run_batch_pipeline.py failed_only.json
```

## Integration Notes

- **No changes needed to `run_contrastive_pipeline.py`**: Batch system calls it as-is
- **Output structure unchanged**: Papers still create `.qa_output/` directories relative to input
- **All skip flags supported**: Pass through to underlying pipeline
- **Python 3.7+**: Compatible with existing environment

## Data Safety

- ✅ Original pipeline files untouched
- ✅ Manifest is version-controlled JSON (human-readable)
- ✅ Progress saved after each paper (safe interruption)
- ✅ Can always regenerate manifest from directory
- ✅ Old `pipeline_output/` not affected by new relative structure

## Next Steps

1. Generate initial manifest: `python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology`
2. Review statistics: `python manifest_utils.py stats manifest_mSystems_molecular_biology.json`
3. Start batch run: `python run_batch_pipeline.py manifest_mSystems_molecular_biology.json`
4. Monitor progress with `--limit` and `--start-from` as needed
5. Check failures and re-run as needed with filters
