# Quick Start: Batch Processing mSystems Papers

## Setup (One Time)

The batch processing system is ready to use. No additional setup needed - all scripts are included.

## Generate Manifest

Choose your approach:

### Option A: All papers in mSystems
```bash
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology
# Creates: manifest_mSystems_molecular_biology.json
```

### Option B: First 10 papers (test)
```bash
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --limit 10
# Creates: manifest_mSystems_molecular_biology.json
```

### Option C: Skip already-processed papers
```bash
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --exclude-existing
# Only includes papers without .qa_output directory
```

## Check Manifest

View papers and progress:
```bash
python manifest_utils.py stats manifest_mSystems_molecular_biology.json
python manifest_utils.py list manifest_mSystems_molecular_biology.json
```

## Run Batch

Start processing:
```bash
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json
```

**That's it!** The system will:
- Process papers one by one
- Update manifest after each paper
- Show progress: `[1/10] Processing: paper_id`
- Show final statistics

## Interrupt and Resume

If you need to stop (Ctrl+C):
1. The manifest is automatically saved with progress
2. Resume anytime: `python run_batch_pipeline.py manifest_mSystems_molecular_biology.json`
3. It will skip already-completed papers and continue

## Monitor Progress

Anytime during or after a run:
```bash
python manifest_utils.py stats manifest_mSystems_molecular_biology.json
```

Shows: Total, Pending, Completed, Failed, Progress %

## Troubleshooting

### See which papers failed
```bash
python manifest_utils.py list manifest_mSystems_molecular_biology.json --status failed
```

### Re-run only failed papers
```bash
python manifest_utils.py filter manifest_mSystems_molecular_biology.json \
  --output failed_only.json \
  --status failed

python run_batch_pipeline.py failed_only.json
```

### Start over with specific paper
```bash
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json --start-from msystems_00451_22
```

### Process only first N papers
```bash
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json --limit 20
```

## Output Location

Each processed paper creates outputs at:
```
paper_directory/.qa_output/paper_name/molecular_biology/
├── graphs/
├── contrastive_qa.json          (main output)
├── pipeline_metadata.json
└── ...
```

## Key Features

✅ **Resumable**: Stop anytime with Ctrl+C, resume later
✅ **Tracked**: See status of every paper
✅ **Flexible**: Skip papers, filter, subset, re-run failures
✅ **Fast**: First manifest generation, then batch run

## Common Commands Reference

```bash
# Generate manifest
python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology [--limit N] [--exclude-existing]

# Check status
python manifest_utils.py stats manifest_mSystems_molecular_biology.json

# List papers
python manifest_utils.py list manifest_mSystems_molecular_biology.json [--status pending|completed|failed]

# Create subset
python manifest_utils.py filter manifest_mSystems_molecular_biology.json --output subset.json --limit 50

# Run batch
python run_batch_pipeline.py manifest_mSystems_molecular_biology.json [--start-from ID] [--limit N]
```

## Next Steps

1. **Generate test manifest** (5 papers):
   ```bash
   python manifest_utils.py generate ASM_595/mSystems --domain molecular_biology --limit 5
   ```

2. **Check what's in it**:
   ```bash
   python manifest_utils.py list manifest_mSystems_molecular_biology.json
   ```

3. **Run it**:
   ```bash
   python run_batch_pipeline.py manifest_mSystems_molecular_biology.json
   ```

4. **Monitor it**:
   ```bash
   # In another terminal
   python manifest_utils.py stats manifest_mSystems_molecular_biology.json
   ```

## Questions?

See full documentation:
- `BATCH_PROCESSING.md` - Complete user guide with examples
- `MANIFEST_SYSTEM_SUMMARY.md` - Feature overview and workflows
- `IMPLEMENTATION_COMPLETE.md` - Technical details
