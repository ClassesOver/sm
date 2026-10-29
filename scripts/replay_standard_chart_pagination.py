"""Execute all registered chart pages and independently audit full coverage."""
import argparse
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
from matplotlib.figure import Figure

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
    materialize_chart_inputs,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_pagination import (
    expand_standard_pagination,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def replay(output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    records=[]
    for form in ('bar','barh'):
        for seed in (3,17,51):
            for scale in (1e-10,1,1e10):
                records.append(render_case(output,form,seed,scale))
        records.append(render_case(output,form,3,1,percent=True))
    result={'mode':'offline_pagination_full_registration_geometry_no_vision',
        'codeCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'workingTreeDirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
        'cases':len(records),'pages':sum(item['pages'] for item in records),'results':records}
    (output/'pagination.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'cases':result['cases'],'pages':result['pages'],'status':'all_geometry_identity_and_coverage_checked'}))


def verify_sources(output):
    output=Path(output).resolve()
    report=json.loads((output/'pagination.json').read_text())
    records=[]
    for record in report['results']:
        folder=output/record['id']
        plan=VisualizationPlanDraft.model_validate_json((folder/'plan.json').read_text())
        entries=tuple(json.loads((folder/'materialization.json').read_text()))
        inputs=ChartInputMaterialization(files=tuple(ChartInputFile(entry['path'],(folder/entry['path']).read_bytes()) for entry in entries),entries=entries)
        for file,entry in zip(inputs.files,entries):
            assert file.sha256==entry['sha256']
        result=standard_visualization_preflight(plan,inputs)
        assert result.source==(folder/'render.py').read_text(), record['id']
        records.append({'id':record['id'],'pages':len(plan.charts),'sourceSha256':hashlib.sha256(result.source.encode()).hexdigest()})
    proof={'codeCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'workingTreeDirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
        'bundles':len(records),'pages':sum(item['pages'] for item in records),'results':records}
    (output/'final-source-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps({'bundles':proof['bundles'],'pages':proof['pages'],'status':'exact_executed_source'}))


def render_case(output,form,seed,scale,percent=False):
    name=f'{form}-{seed}-{scale}'+('-percent' if percent else '')
    folder=output/name
    folder.mkdir(exist_ok=True)
    labels=[f'院区{i:02d}' for i in range(25)]
    actual=[(i-seed/10)*scale for i in range(25)]
    budget=[(i+1)*1.5*scale for i in range(25)]
    if seed==17:
        actual[11]=None
    if percent:
        actual=[i/100 for i in range(25)]
        budget=[(i+1)/100 for i in range(25)]
    metadata={'unit':'%','isPercent':False} if percent else {'unit':'元'}
    table={'columns':['label','actual','budget'],'rows':[[label,a,b] for label,a,b in zip(labels,actual,budget)],
        'columnMeta':{field:metadata for field in ('actual','budget')}}
    chart=ChartDraft(chartId='chart',sourcePath='chart.png',title='完整院区预算分页',altText='全部院区完整分页对照',
        citationIds=['citation'],metricCodes=['metric'],currentPeriod='2026-10',sourceDatasetId='dataset',aggregationGrain='category',
        visualForm=form,standardValueFields=['actual','budget'],standardPagination={'pageSize':10},
        standardAxes={'allowNulls':seed==17},standardDisplayUnit=None if percent else '万元',
        standardStyle={'labelRotation':0,'points':[{'series':'budget','label':labels[-1],'color':'#b55d68'}]},
        standardCanvas={'sizeMode':'fixed','width':14,'height':8,'dpi':100},
        dataBindings=[{'analysisId':'a','factPath':'facts.json','dataPath':'findings[0].rows','fields':table['columns'],'role':'完整院区汇总'}])
    plan=VisualizationPlanDraft(charts=(chart,))
    fact_bytes=json.dumps({'findings':[table]},ensure_ascii=False).encode()
    facts=[{'analysisId':'a','factFile':{'path':'facts.json','size':len(fact_bytes),'sha256':hashlib.sha256(fact_bytes).hexdigest()},
        'dataDescriptors':[{'dataPath':'findings[0].rows','fields':table['columns']}]}]
    documents={'facts.json':{'findings':[table]}}
    before=materialize_chart_inputs(plan,facts,documents,output_root='.')
    expanded=expand_standard_pagination(plan,before)
    assert len(expanded.charts)==3 and not expanded.warnings
    inputs=materialize_chart_inputs(expanded,facts,documents,output_root='.')
    preflight=standard_visualization_preflight(expanded,inputs)
    assert preflight.source, preflight.diagnostic
    (folder/'facts.json').write_bytes(fact_bytes)
    (folder/'original-plan.json').write_text(plan.model_dump_json(by_alias=True,indent=2))
    (folder/'plan.json').write_text(expanded.model_dump_json(by_alias=True,indent=2))
    (folder/'materialization.json').write_text(json.dumps(inputs.entries,ensure_ascii=False,indent=2))
    (folder/'render.py').write_text(preflight.source)
    for file in inputs.files:
        (folder/file.path).write_bytes(file.content)
        data=json.loads(file.content)
        assert data['rows']==table['rows'] and data['source']['sha256']==facts[0]['factFile']['sha256']
    seen=[]
    limits=[]
    pages=[]
    original_save=Figure.savefig
    def audit(fig,path,*args,**kwargs):
        page=expanded.charts[len(pages)]
        axis=fig.axes[0]
        expected=table['rows'][len(pages)*10:(len(pages)+1)*10]
        assert len(axis.containers)==2
        ticks=axis.get_yticklabels() if form=='barh' else axis.get_xticklabels()
        visible=[tick.get_text() for tick in ticks if tick.get_visible()]
        assert visible==[row[0] for row in expected]
        seen.extend(visible)
        for index, bars in enumerate(axis.containers):
            assert len(bars)==len(expected)
            for bar,row in zip(bars,expected):
                raw=row[index+1]
                value=bar.get_width() if form=='barh' else bar.get_height()
                wanted=None if raw is None else raw*(100 if percent else 1e-4)
                assert math.isnan(value) if wanted is None else math.isclose(value,wanted,rel_tol=1e-12,abs_tol=0)
                start=bar.get_x() if form=='barh' else bar.get_y()
                assert start==0
                color='#b55d68' if index==1 and row[0]==labels[-1] else ('#3066a3' if index==0 else '#dc884d')
                assert to_hex(bar.get_facecolor())==color
        domain=axis.get_xlim() if form=='barh' else axis.get_ylim()
        all_values=[row[n]*(100 if percent else 1e-4) for row in table['rows'] for n in (1,2) if row[n] is not None]+[0]
        assert domain[0]<=min(all_values) and domain[1]>=max(all_values)
        assert all(domain==other for other in limits)
        limits.append(domain)
        assert page.data_bindings==chart.data_bindings and page.standard_pagination is None
        assert f'第{len(pages)+1}/3页' in page.title
        result=original_save(fig,path,*args,**kwargs)
        pages.append({'chartId':page.chart_id,'path':str(path),'labels':visible,'domain':list(domain),
            'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()})
        return result
    current=Path.cwd()
    try:
        os.chdir(folder)
        Figure.savefig=audit
        exec(preflight.source,{})
    finally:
        Figure.savefig=original_save
        os.chdir(current)
        plt.close('all')
    assert seen==labels and len(pages)==3
    for file in inputs.files:
        assert (folder/file.path).read_bytes()==file.content
    audit_result={'status':'rendered_geometry_identity_coverage_checked','pages':pages,'fullCoverage':seen==labels,
        'fullFactSha256':facts[0]['factFile']['sha256'],'inputIdentities':[{'path':file.path,'sha256':file.sha256} for file in inputs.files],
        'frozenRows':len(table['rows']),'repeatedFullInputRows':[json.loads(file.content)['rowCount'] for file in inputs.files]}
    (folder/'audit.json').write_text(json.dumps(audit_result,ensure_ascii=False,indent=2))
    return {'id':name,'status':audit_result['status'],'pages':len(pages),'fullCoverage':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    (verify_sources if args.verify_only else replay)(args.output)
