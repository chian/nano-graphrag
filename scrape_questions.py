"""
Scrape all generated QA questions from .qa_output directories.

Searches for contrastive_qa.json files and consolidates all questions
into a single output file with metadata about source papers and domains.
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


def find_qa_files(base_directory: Path, domain: Optional[str] = None) -> List[Path]:
    """
    Find all contrastive_qa.json files in .qa_output directories.

    Args:
        base_directory: Root directory to search
        domain: Optional domain filter (e.g., 'molecular_biology', 'ecology')

    Returns:
        List of paths to contrastive_qa.json files
    """
    base_directory = Path(base_directory).resolve()

    if not base_directory.exists():
        print(f"✗ ERROR: Directory not found: {base_directory}")
        return []

    # Find all contrastive_qa.json files
    pattern = "**/contrastive_qa.json"
    qa_files = []

    for qa_file in base_directory.glob(pattern):
        # Only include files in .qa_output directories
        if ".qa_output" not in qa_file.parts:
            continue

        # Filter by domain if specified
        if domain:
            # Check if domain is in path
            if domain not in qa_file.parts:
                continue

        qa_files.append(qa_file)

    return sorted(qa_files)


def extract_paper_id(qa_file_path: Path) -> str:
    """
    Extract paper ID from QA file path.

    Expected path: .../source_files/.qa_output/{paper_id}/{domain}/contrastive_qa.json
    """
    parts = qa_file_path.parts
    try:
        qa_output_idx = parts.index('.qa_output')
        # Paper ID is the directory after .qa_output
        return parts[qa_output_idx + 1]
    except (ValueError, IndexError):
        return "unknown"


def scrape_questions(
    base_directory: Path,
    domain: Optional[str] = None,
    output_file: Optional[Path] = None
) -> Dict:
    """
    Scrape all questions from QA output files.

    Args:
        base_directory: Root directory to search
        domain: Optional domain filter
        output_file: Where to save output (default: scraped_questions.json)

    Returns:
        Dictionary containing all scraped questions with metadata
    """
    qa_files = find_qa_files(base_directory, domain)

    if not qa_files:
        print(f"\n✗ No QA files found in {base_directory}")
        if domain:
            print(f"  (with domain filter: {domain})")
        return {}

    print(f"\nFound {len(qa_files)} QA output files")
    if domain:
        print(f"Domain filter: {domain}")

    all_questions = []
    papers_processed = 0
    total_questions = 0
    errors = []

    for qa_file in qa_files:
        try:
            with open(qa_file, 'r') as f:
                qa_data = json.load(f)

            paper_id = extract_paper_id(qa_file)
            questions = qa_data.get("questions", [])

            # Add metadata to each question
            for q in questions:
                question_with_meta = {
                    "paper_id": paper_id,
                    "domain": qa_data.get("domain", "unknown"),
                    "source_file": str(qa_file),
                    **q  # Include all original question fields
                }
                all_questions.append(question_with_meta)

            papers_processed += 1
            total_questions += len(questions)

            print(f"  ✓ {paper_id}: {len(questions)} questions")

        except Exception as e:
            error_msg = f"Error processing {qa_file}: {str(e)}"
            errors.append(error_msg)
            print(f"  ✗ {error_msg}")

    # Create output structure
    output = {
        "scraped_at": datetime.now().isoformat(),
        "base_directory": str(base_directory),
        "domain_filter": domain,
        "total_papers": papers_processed,
        "total_questions": total_questions,
        "questions": all_questions,
        "errors": errors
    }

    # Save to file
    if not output_file:
        if domain:
            output_file = Path(f"scraped_questions_{domain}.json")
        else:
            output_file = Path("scraped_questions_all.json")
    else:
        output_file = Path(output_file)

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Scraping complete!")
    print(f"{'='*60}")
    print(f"Papers processed: {papers_processed}")
    print(f"Total questions: {total_questions}")
    print(f"Errors: {len(errors)}")
    print(f"Output saved to: {output_file}")
    print(f"{'='*60}\n")

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Scrape all generated QA questions into a single file"
    )

    parser.add_argument(
        "directory",
        help="Base directory to search for QA outputs"
    )

    parser.add_argument(
        "--domain",
        help="Filter by domain (e.g., molecular_biology, ecology)"
    )

    parser.add_argument(
        "--output",
        help="Output file path (default: scraped_questions_{domain}.json)"
    )

    args = parser.parse_args()

    scrape_questions(
        Path(args.directory),
        domain=args.domain,
        output_file=Path(args.output) if args.output else None
    )


if __name__ == "__main__":
    main()
