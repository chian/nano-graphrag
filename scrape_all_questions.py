#!/usr/bin/env python
"""
Scrape questions from all journals and domains using scrape_questions.py
"""

import subprocess
import json
from pathlib import Path

BASE_DIR = "/Users/chia/Documents/ANL/BioData/Argonium.nosync/ASM_595"

JOURNALS = ["AAC", "AEM", "CMR", "IAI", "JB", "JCM", "JMBE", "JVI", "MMBR", "Spectrum", "mBio", "mSphere", "mSystems"]
DOMAINS = ["clinical_microbiology", "disease_biology", "ecology", "epidemiology", "infectious_disease", "microbial_biology", "molecular_biology"]

results = []

for journal in JOURNALS:
    for domain in DOMAINS:
        journal_path = Path(BASE_DIR) / journal
        output_file = f"scraped_questions_{journal}_{domain}.json"

        print(f"\n{'='*60}")
        print(f"Scraping {journal} / {domain}")
        print(f"{'='*60}")

        subprocess.run([
            "python", "scrape_questions.py",
            str(journal_path),
            "--domain", domain,
            "--output", output_file
        ])

        # Check if output file was created and has questions
        output_path = Path(output_file)
        if output_path.exists():
            with open(output_path) as f:
                data = json.load(f)
                questions = data.get("total_questions", 0)
                papers = data.get("total_papers", 0)
                if questions > 0:
                    results.append({
                        "journal": journal,
                        "domain": domain,
                        "papers": papers,
                        "questions": questions
                    })

# Print summary table
print("\n")
print("=" * 70)
print("SUMMARY: Non-zero QA Results")
print("=" * 70)
print(f"{'Journal':<12} {'Domain':<25} {'Papers':>8} {'Questions':>10}")
print("-" * 70)

total_papers = 0
total_questions = 0

for r in sorted(results, key=lambda x: (x["journal"], x["domain"])):
    print(f"{r['journal']:<12} {r['domain']:<25} {r['papers']:>8} {r['questions']:>10}")
    total_papers += r["papers"]
    total_questions += r["questions"]

print("-" * 70)
print(f"{'TOTAL':<12} {'':<25} {total_papers:>8} {total_questions:>10}")
print("=" * 70)
