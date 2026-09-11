"""
Extract text from PDFs using PyMuPDF and save as .txt files.
This prepares PDFs for the batch processing pipeline.

Usage:
    python extract_pdfs_to_text.py --input-dir ./aac-papers
"""

import argparse
import sys
from pathlib import Path
import fitz  # PyMuPDF


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a single PDF file."""
    try:
        doc = fitz.open(str(pdf_path))
        text_content = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                text_content.append(text)
        
        doc.close()
        return "\n\n".join(text_content)
    
    except Exception as e:
        print(f"  ⚠️  Error extracting {pdf_path.name}: {e}")
        return ""


def process_folder(folder_path: Path):
    """Process all PDFs in a folder's source_files directory."""
    folder_name = folder_path.name
    print(f"\n{'='*80}")
    print(f"Processing: {folder_name}")
    print(f"{'='*80}")
    
    # Find source_files directory
    source_dir = folder_path / "source_files"
    if not source_dir.exists():
        print(f"  ⏭️  No source_files directory found, skipping...")
        return {'folder': folder_name, 'status': 'skipped'}
    
    # Find all PDFs recursively
    pdf_files = list(source_dir.rglob("*.pdf"))
    
    if not pdf_files:
        print(f"  ⏭️  No PDF files found, skipping...")
        return {'folder': folder_name, 'status': 'skipped'}
    
    print(f"  📄 Found {len(pdf_files)} PDF file(s)")
    
    # Extract text from each PDF
    extracted_count = 0
    for pdf_path in pdf_files:
        print(f"    - Processing {pdf_path.name}...")
        
        # Extract text
        text = extract_text_from_pdf(pdf_path)
        
        if not text:
            print(f"      ⚠️  No text extracted")
            continue
        
        # Save as .txt file in the same directory
        txt_path = pdf_path.with_suffix('.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        char_count = len(text)
        print(f"      ✅ Saved {char_count:,} characters to {txt_path.name}")
        extracted_count += 1
    
    print(f"  ✅ Extracted {extracted_count}/{len(pdf_files)} PDF files")
    
    return {
        'folder': folder_name,
        'status': 'success',
        'pdf_count': len(pdf_files),
        'extracted_count': extracted_count
    }


def main(args):
    """Main processing function."""
    input_path = Path(args.input_dir)
    
    print(f"\n{'='*80}")
    print(f"PDF TEXT EXTRACTION")
    print(f"{'='*80}")
    print(f"Input directory: {input_path}")
    print(f"{'='*80}\n")
    
    if not input_path.exists():
        print(f"❌ Input directory does not exist: {input_path}")
        return
    
    # Check if this is a single folder or directory of folders
    if (input_path / "source_files").exists():
        # Single folder mode
        print("📁 Single folder mode")
        result = process_folder(input_path)
        results = [result]
    else:
        # Multi-folder mode
        print("📂 Multi-folder mode")
        folders = [f for f in input_path.iterdir() if f.is_dir()]
        print(f"Found {len(folders)} folders\n")
        
        results = []
        for folder in folders:
            result = process_folder(folder)
            results.append(result)
    
    # Summary
    print(f"\n{'='*80}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'='*80}")
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    skipped_count = sum(1 for r in results if r['status'] == 'skipped')
    
    print(f"  Total folders: {len(results)}")
    print(f"  ✅ Extracted: {success_count}")
    print(f"  ⏭️  Skipped: {skipped_count}")
    
    if success_count > 0:
        total_pdfs = sum(r.get('pdf_count', 0) for r in results if r['status'] == 'success')
        total_extracted = sum(r.get('extracted_count', 0) for r in results if r['status'] == 'success')
        print(f"  📄 Total PDFs processed: {total_extracted}/{total_pdfs}")
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract text from PDFs and save as .txt files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract all PDFs in aac-papers directory
  python extract_pdfs_to_text.py --input-dir ./aac-papers

  # Extract PDFs from a single folder
  python extract_pdfs_to_text.py --input-dir ./aac-papers/AACv67i10_00051_23

After extraction, run batch processing:
  ./batch_process_aac_papers.sh
        """
    )
    
    parser.add_argument(
        "--input-dir",
        type=str,
        required=True,
        help="Directory containing folders with PDFs in source_files subdirectories"
    )
    
    args = parser.parse_args()
    main(args)

