"""Reuse real grant/conversion/signing routes for text-link fidelity."""
import argparse
import asyncio
from pathlib import Path
from runpy import run_path

import uvicorn

create_app = run_path(str(Path(__file__).with_name('pdf-delivery-batch-server.py')))['create_app']
create_app.__globals__['source_pdf'] = run_path(str(Path(__file__).with_name('pdf-pptx-text-links-source.py')))['source_pdf']

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4344)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
