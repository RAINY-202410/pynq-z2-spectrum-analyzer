"""Check the complete board software bundle, including nested browser/replay assets."""
import hashlib
import json
from pathlib import Path

from fft_campaign_export import notebook_source


def verify_software(base, allow_source_tree=False):
    base = Path(base).resolve()
    manifest_path = base / 'software_manifest.json'
    if not manifest_path.is_file():
        if allow_source_tree:
            return dict(verified=False, context='SOURCE_TREE_DEVELOPMENT')
        raise ValueError('software_manifest.json missing; extract the complete board ZIP into a fresh folder')
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    missing, changed = [], []
    for name, expected in data['files_sha256'].items():
        path = (base / name).resolve()
        path.relative_to(base)
        if not path.is_file():
            missing.append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest().upper() != expected:
            changed.append(name)
    if missing or changed:
        raise ValueError('Incomplete/changed software package. Missing: {}; changed: {}. Extract the entire board ZIP, including subfolders.'.format(missing, changed))
    nb = json.loads((base / data['notebook']).read_text(encoding='utf-8'))
    if notebook_source(nb, data['notebook_cell_count']) != data['notebook_source_sha256']:
        raise ValueError('Launcher Notebook source differs from the software bundle')
    return dict(verified=True, software_revision=data['software_revision'],
                build_revision=data.get('build_revision', data['software_revision']),
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper(),
                verified_files=len(data['files_sha256']))
