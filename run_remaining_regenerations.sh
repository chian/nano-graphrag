#!/bin/bash
# Run question regeneration for remaining journal/domain combinations

ASM_BASE="/Users/chia/Documents/ANL/BioData/Argonium.nosync/ASM_595"

# Activate conda environment
source ~/miniconda3/etc/profile.d/conda.sh
conda activate py310

echo "Starting batch regeneration of remaining journal/domain combinations"
echo "================================================================"
echo ""

# Remaining journal/domain combinations that showed 0 questions
declare -a JOBS=(
    "AEM:ecology"
    "AEM:molecular_biology"
    "IAI:infectious_disease"
    "JCM:clinical_microbiology"
    "JVI:infectious_disease"
    "mBio:molecular_biology"
)

total=${#JOBS[@]}
current=0

for job in "${JOBS[@]}"; do
    journal="${job%%:*}"
    domain="${job##*:}"
    current=$((current + 1))

    echo ""
    echo "================================================================"
    echo "[$current/$total] Running: $journal / $domain"
    echo "================================================================"

    python regenerate_questions_from_graphs.py "$ASM_BASE/$journal" "$domain"

    if [ $? -eq 0 ]; then
        echo "✓ Completed: $journal / $domain"
    else
        echo "✗ Failed or skipped: $journal / $domain"
    fi
done

echo ""
echo "================================================================"
echo "All remaining regeneration jobs complete!"
echo "================================================================"
