# ASM Papers Processing

This directory contains scripts for processing ASM (American Society for Microbiology) papers from the ASM_595 dataset.

## Directory Structure

The ASM_595 dataset has a different structure than the AAC papers:

```
/Users/chia/Documents/ANL/BioData/Argonium.nosync/ASM_595/
├── AAC/          # Applied and Environmental Microbiology
├── AEM/          # Applied and Environmental Microbiology  
├── ASM/          # ASM journals
├── CMR/          # Clinical Microbiology Reviews
├── EcoSalPlus/   # EcoSal Plus
├── IAI/          # Infection and Immunity
├── JB/           # Journal of Bacteriology
├── JCM/          # Journal of Clinical Microbiology
├── JMBE/         # Journal of Microbiology & Biology Education
├── JVI/          # Journal of Virology
├── mBio/         # mBio
├── MMBR/         # Microbiology and Molecular Biology Reviews
├── MRA/          # Microbiology Resource Announcements
├── mSphere/      # mSphere
├── mSystems/     # mSystems
└── Spectrum/     # Spectrum
```

Each journal directory contains zip files directly (unlike AAC which had individual paper directories).

## Scripts

### 1. `batch_process_asm_papers.sh`
Main batch processing script for ASM papers. Key differences from AAC script:
- Processes zip files directly from journal directories
- Extracts each zip file to a temporary working directory
- Handles the different directory structure automatically

### 2. `asm_processing_config.sh`
Configuration file with example settings for different processing scenarios.

### 3. `test_asm_processing.sh`
Test script to verify the setup works with a single paper.

## Usage

### Basic Usage
```bash
# Process all papers in all journals (reasoning questions only)
./batch_process_asm_papers.sh
```

### Process Specific Journal
Edit `batch_process_asm_papers.sh` and set:
```bash
SPECIFIC_JOURNAL="AEM"  # Process only AEM papers
```

### Process Single Paper
Edit `batch_process_asm_papers.sh` and set:
```bash
SPECIFIC_PAPER_ZIP="/path/to/specific/paper.zip"
```

### Custom Configuration
1. Copy `asm_processing_config.sh` to create your own config
2. Modify the parameters as needed
3. Source the config file in your batch script

## Configuration Options

### Processing Mode
- `PROCESSING_MODE="sequential"` - Process papers one by one
- `PROCESSING_MODE="parallel"` - Process multiple papers simultaneously

### Question Generation
- `GENERATE_REASONING=true` - Generate reasoning questions (default: 50)
- `GENERATE_MULTIHOP=false` - Generate multihop questions
- `GENERATE_SYNTHESIS=false` - Generate synthesis questions  
- `GENERATE_SHORT_ANSWER=false` - Generate short answer questions

### Entity Task Prompt
The default prompt is tailored for microbiology and molecular biology:
```
"Study molecular biology, microbiology, and biochemistry concepts. Analyze scientific research on bacterial mechanisms, viral processes, and microbial ecology."
```

## Example Configurations

### Process AEM Journal Only
```bash
SPECIFIC_JOURNAL="AEM"
GENERATE_REASONING=true
REASONING_NUM_QUESTIONS=25
```

### Process Single Paper for Testing
```bash
SPECIFIC_PAPER_ZIP="/Users/chia/Documents/ANL/BioData/Argonium.nosync/ASM_595/AEM/AEMv89i10_10_1128_aem_00143_23-20240609085801-8048634.zip"
```

### Parallel Processing
```bash
PROCESSING_MODE="parallel"
MAX_PARALLEL_JOBS=2
GENERATE_REASONING=true
REASONING_NUM_QUESTIONS=30
```

## Output Structure

For each processed paper, the script creates:
```
{journal_dir}/{paper_id}/
├── graphrag_cache/          # GraphRAG cache files
├── graph_versions/          # Graph version files
├── reasoning_qa.json        # Generated reasoning questions (if enabled)
├── multihop_qa.json         # Generated multihop questions (if enabled)
├── synthesis_qa.json        # Generated synthesis questions (if enabled)
└── short_answer_qa.json     # Generated short answer questions (if enabled)
```

## Logging

All processing is logged to `batch_processing_asm.log` with timestamps and status updates.

## Prerequisites

1. Conda environment must be activated before running
2. All required Python scripts must be present:
   - `create_graph_only.py`
   - `generate_reasoning_qa.py`
   - `generate_multihop_qa.py`
   - `generate_synthesis_qa.py`
   - `generate_short_answer_qa.py`

## Differences from AAC Processing

1. **Directory Structure**: ASM papers are in zip files within journal directories, not individual paper directories
2. **Extraction**: Each zip file is extracted to a temporary working directory
3. **Journal Organization**: Papers are organized by journal type (AEM, JB, etc.)
4. **File Naming**: Paper IDs are derived from zip filenames

## Troubleshooting

### Common Issues

1. **No text files found**: Ensure PDFs have been extracted to text files
2. **Permission errors**: Make sure scripts are executable (`chmod +x`)
3. **Missing dependencies**: Verify all Python scripts and dependencies are installed
4. **Disk space**: Processing creates temporary directories - ensure sufficient disk space

### Testing

Use the test script to verify setup:
```bash
./test_asm_processing.sh
```

This will process a single paper to verify everything works correctly.
