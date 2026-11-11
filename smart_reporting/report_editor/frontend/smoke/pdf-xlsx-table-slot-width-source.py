"""Reuse the exact prior currency source for a same-source slot-width comparison."""
from pathlib import Path
from runpy import run_path

def source_pdf():
    return run_path(str(Path(__file__).with_name('pdf-xlsx-currency-precision-source.py')))['source_pdf']()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(source_pdf())
