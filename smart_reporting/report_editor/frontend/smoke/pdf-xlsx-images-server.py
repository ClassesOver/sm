"""Use existing real grant/CSRF/publication routes with the normal-image fixture."""
from __future__ import annotations
import argparse
import asyncio
from pathlib import Path
from runpy import run_path
import uvicorn

original=run_path(str(Path(__file__).with_name('pdf-delivery-batch-server.py')))
create_app=original['create_app']
fixture=Path(__file__).resolve().parents[3]/'reporting/pdf_engine/bridge/fixtures/xlsx-normal-images.pdf'
create_app.__globals__['source_pdf']=lambda:fixture.read_bytes()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--port',type=int,default=4327)
    args=parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory,args.port)),host='127.0.0.1',port=args.port,log_level='warning')
