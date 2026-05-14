import argparse
import os
from pathlib import Path
from parser import run


def main():
    file_name = os.path.basename(__file__)
    prog = os.environ.get("PARSE_PAPER_PROG", file_name)
    parser = argparse.ArgumentParser(description='''Parse scientific paper PDFs into AI-friendly structured outputs.

For each paper, the tool writes:
    - `summary.json`: compact entry point with title, page count, and manifest path
    - `manifest.json`: detailed file map and extracted figure/table metadata
    - `paper_body.md` or `paper_body.txt`: main paper body without references
    - `abstract.*`: abstract only
    - `references.*`: references only
    - `sections/`: one file per detected section
    - `figures/`: extracted figure PNG files only
    - `tables/`: extracted table CSV files only

Figure and table titles, captions, page numbers, and body-text reference
snippets are stored in `manifest.json`. The file can be large, so don't read the full content directly.
    ''',
    formatter_class=argparse.RawTextHelpFormatter,
    prog=prog)
    parser.add_argument('input_path', type=Path, help='Path to input PDF file or directory containing PDFs')
    parser.add_argument('output_dir', type=Path, help='Directory to store parsed outputs')
    parser.add_argument('--timeout', type=float, default=500.0, help='Timeout in seconds for PDF parsing (default: 500.0)')
    
    args = parser.parse_args()
    
    try:
        # Validate input path exists
        if not args.input_path.exists():
            print(f"Error: Input path '{args.input_path}' does not exist")
            return
        
        # Create output directory if it doesn't exist
        args.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Run the parser
        results = run(
            input_path=args.input_path,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout
        )
        
        print(f"Successfully processed {len(results)} PDF(s)")
        print(f"Outputs saved to: {args.output_dir.resolve()}")
        
    except Exception as e:
        print(f"Error during PDF parsing: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()