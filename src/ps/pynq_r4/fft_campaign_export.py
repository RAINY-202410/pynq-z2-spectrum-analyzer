"""Integrity checks and post-save export; never reruns a capture."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def notebook_source(notebook, cell_count):
    cells=notebook['cells']
    if len(cells)<cell_count:
        raise ValueError('Notebook is missing required cells')
    for cell in cells[cell_count:]:
        if ''.join(cell.get('source',[])).strip() or cell.get('outputs'):
            raise ValueError('Unexpected nonempty extra Notebook cell')
    canonical=[(c['cell_type'],''.join(c['source']),c.get('metadata',{}).get('tags',[])) for c in cells[:cell_count]]
    return hashlib.sha256(json.dumps(canonical,ensure_ascii=False).encode('utf-8')).hexdigest().upper()


def verify_package(base, notebook='FFT_stability.ipynb'):
    base=Path(base).resolve()
    manifest=json.loads((base/'package_manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['immutable_files_sha256'].items():
        path=(base/name).resolve()
        path.relative_to(base)
        if digest(path)!=expected:raise ValueError('Package file changed: '+name)
    nb=json.loads((base/notebook).read_text(encoding='utf-8'))
    if notebook_source(nb,manifest['notebook_cell_count'])!=manifest['notebook_source_sha256']:
        raise ValueError('Notebook source changed; saved execution outputs are allowed')
    return manifest


def export_results(output, notebook, allow_incomplete=False):
    output,notebook=Path(output).resolve(),Path(notebook).resolve()
    manifest=verify_package(notebook.parent,notebook.name)
    nb=json.loads(notebook.read_text(encoding='utf-8'))
    required=[];missing=[]
    for i,cell in enumerate(nb['cells'][:manifest['notebook_cell_count']]):
        if 'evidence_required' in cell.get('metadata',{}).get('tags',[]):
            if cell.get('execution_count') is None or not cell.get('outputs') or any(o.get('output_type')=='error' for o in cell.get('outputs',[])):
                missing.append(i)
            required.append(dict(cell=i,execution_count=cell['execution_count']))
    if (missing or not (output/'campaign_results.json').is_file()) and not allow_incomplete:
        raise RuntimeError('Save Notebook with Ctrl+S after completing the test cells; do not rerun captures merely to export. Missing cells '+str(missing))
    complete=not missing and (output/'campaign_results.json').is_file()
    index=1
    while (output/('executed_notebook_{:02d}.ipynb'.format(index))).exists():index+=1
    snapshot=output/('executed_notebook_{:02d}.ipynb'.format(index));shutil.copy2(notebook,snapshot)
    files={}
    for path in sorted(output.rglob('*')):
        if path.is_symlink():raise ValueError('Export directory must not contain symlinks')
        if path.is_file():files[str(path.relative_to(output)).replace('\\','/')]=digest(path)
    record=dict(source='PL_FFT',package_software_revision=manifest['software_revision'],
                executed_notebook=snapshot.name,notebook_sha256=digest(snapshot),required_cells=required,
                evidence_complete=complete,missing_cells=missing,
                export_cell_is_not_an_evidence_cell=True,files_sha256=files)
    record_path=output/('export_manifest_{:02d}.json'.format(index))
    record_path.write_text(json.dumps(record,indent=2),encoding='utf-8')
    suffix='_export' if complete else '_INCOMPLETE_export'
    archive=output.parent/(output.name+suffix+'{:02d}.zip'.format(index))
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(output.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(output.parent))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise RuntimeError('Export ZIP CRC failure')
    return archive
