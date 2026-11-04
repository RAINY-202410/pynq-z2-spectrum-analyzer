"""Audit and package real XSim captures for B-W05; never send the archive."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

import numpy as np
from fft_contract_reference import compare_words
from verify_fft_chain import BASE, GOLDEN, ROOT, SOURCES, hex_values


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest().upper()
def require(ok, message):
    if not ok: raise ValueError(message)
def save(path, data): path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def main():
    run = ROOT/'build/fft_chain_sim_20261024_02'
    preparation = json.loads((run/'preparation.json').read_text())
    require(all(sha(ROOT/n)==h for n,h in preparation['source_files_sha256'].items()), 'Tested source/reference changed')
    log = (run/'logs/simulate.log').read_text(encoding='utf-8', errors='replace')
    for token in ('SIGNED24_BOUNDARIES_PASS: 11', 'ABORT_RECOVERY_PASS: during_output=0',
                  'ABORT_RECOVERY_PASS: during_output=1', 'FAULT_LATCH_PASS:',
                  'CHAIN_CAPTURE_PASS: 14 actual frames', '$finish called'):
        require(token in log, 'Missing actual simulation marker: '+token)
    require(not re.search(r'(?im)^\s*(fatal|error):|GLOBAL_WATCHDOG', log), 'Simulation failure in log')
    rows = []
    for case, base in BASE.items():
        folder = run/case
        require(log.count('CHAIN_CASE_CAPTURE_PASS: '+case+'\n') == 1, 'Case marker count: '+case)
        state = json.loads((folder/'state.json').read_text())
        expected_status = 0x186 if case in ('bin16_rect','bin16_hann') else 0x106
        require(state['source']=='XSIM_RTL_FRAME_ENGINE' and state['case']==case, 'Capture identity')
        require(state['status']==expected_status and state['status_beats']==1, 'Status: '+case)
        require(all(state[k]==1024 for k in ('captured','fft_inputs','outputs','input_count','output_count')), 'Counts')
        require(state['stall_cycles'] > 0, 'Backpressure not exercised')
        actual = hex_values(folder/'actual_spectrum64.hex')
        require(np.array_equal(actual, np.load(folder/'actual_words_u64.npy',allow_pickle=False)), 'NPY capture mismatch')
        with np.load(GOLDEN/base/'reference.npz', allow_pickle=False) as ref:
            require(np.array_equal(hex_values(folder/'actual_s24.hex'), ref['input_s24'].astype(np.int64)&0xffffff), 'Raw input')
            require(np.array_equal(hex_values(folder/'actual_fft_input32.hex'), ref['fft_input_z'].view(np.uint16).astype(np.uint64)), 'Window/24-to-16')
            result = compare_words(actual, ref['expected_words'])
        require(result['numerical_pass'] and actual.nbytes==8192, 'Integer FFT/payload mismatch')
        rows.append(dict(case=case, numerical_pass=True, protocol_and_status_checked=True,
                         mismatching_components=0, max_component_error_integer_lsb=0,
                         payload_bytes=8192, expected_status=expected_status,
                         actual_words_sha256=sha(folder/'actual_words_u64.npy')))
    target = ROOT/'release/fft_chain_sim_v1/A_fft_chain_results_v1'
    target.mkdir(parents=True, exist_ok=False)
    def copy(source, rel):
        destination = target/rel; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source, destination)
    for path in run.rglob('*'):
        if path.is_file(): copy(path, Path('results')/path.relative_to(run))
    extra = ['sim/tb_fft_rect.sv','hw/ip/fft_contract_v02_bd.tcl','hw/ip/fft_contract_v1.json',
             'sw/reference/fft_contract_reference.py','sw/reference/fft_contract_assets.py',
             'sw/reference/package_fft_chain.py','docs/fft_contract.md']
    for rel in SOURCES + extra: copy(ROOT/rel, rel)
    for path in GOLDEN.rglob('*'):
        if path.is_file(): copy(path, Path('sim/vectors/fft_golden_v1')/path.relative_to(GOLDEN))
    copy(ROOT/'sim/vectors/fft_contract_v1/hann_coeff_u16.hex', 'sim/vectors/fft_contract_v1/hann_coeff_u16.hex')
    receipt = dict(status='SIM_VALIDATED', tool='Vivado 2026.1 / XSim / xfft9.1 Rev16',
                   part='xc7z020clg400-1', main_cases=12, recovery_frames=2,
                   integer_component_mismatches=0, results=rows,
                   protocol_regression='PASS', signed24_boundaries=11,
                   fault_scope='Engine input overflow, malformed input TLAST, injected FFT-event detector; not actual numerical FFT overflow',
                   lint='7 intentional ASSIGN-10 warnings; see canonical reports',
                   source_files_sha256=preparation['source_files_sha256'],
                   board_accepted=False, sent_to_B=False, B_acknowledged=False)
    save(target/'validation_receipt.json', receipt)
    (target/'README.md').write_text('''# A FFT v1 — B-W05 actual RTL results

Status: SIM_VALIDATED; board acceptance and B signoff pending. Not sent by Codex.
12 main cases + 2 recovery frames, actual hardware window and 64-bit packer.
All 1024 complex integers per frame match the frozen official C-model references exactly.
`results/*/actual_spectrum64.hex` and `actual_words_u64.npy` are captured RTL output.
`sim/vectors/fft_golden_v1` is the reference only. Do not relabel it as PL output.

Use `validation_receipt.json` for combined numeric/protocol acceptance. The older
`comparison.json` field `protocol_and_status_checked=false` belongs to the reused
numeric-only comparison function; it does not perform protocol acceptance itself.
The separate audit checks frame state/counts and terminal testbench markers.

Protocol assertions cover gaps, held outputs, TLAST/TKEEP, busy START/CLEAR,
latched WINDOW/next-frame behavior, AXI-Lite independent AW/W and held responses,
WSTRB/read-only/command priorities, ABORT/reset/reconfiguration and recovery.
Explicit FFT-event injection tests the detector, not numerical overflow behavior.
The ROSS run request timed out at 300 seconds; native XSim completed normally at
987620 ns. Completion logs, source hashes, captures and session status were checked.

Payload: 1024 little-endian uint64 words / 8192 bytes. Low32 signed-extended real16,
high32 signed-extended imag16. Native Q1.15; restore total FFT shift11 once.
No board bit/hwh is in this simulation-only archive.

Recheck from this archive: Python with NumPy, then
`python sw/reference/verify_fft_chain.py verify --out results`.
This reruns numeric/frame checks; use the supplied audit receipt for the full coverage scope.
The XSim project is regenerated by `hw/scripts/sim_fft_chain.tcl` from source and the
native FFT configuration export; it requires the matching Vivado installation.
''', encoding='utf-8')
    files = {str(p.relative_to(target)).replace('\\','/'):sha(p) for p in target.rglob('*') if p.is_file()}
    save(target/'package_manifest.json', dict(status='SIM_VALIDATED', files_sha256=files))
    archive = target.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(target.rglob('*')):
            if path.is_file(): z.write(path,path.relative_to(target.parent))
    with zipfile.ZipFile(archive) as z: require(z.testzip() is None,'Archive CRC')
    save(archive.parent/'package_receipt.json', dict(archive=str(archive), sha256=sha(archive), files=len(files)+1, sent_to_B=False))
    print('SIM_VALIDATED:', archive, 'SHA256='+sha(archive))


if __name__=='__main__': main()
