"""Frozen-input preparation and independent checking of actual frame-engine captures."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
from fft_contract_reference import compare_words

ROOT=Path(__file__).resolve().parents[3]
GOLDEN=ROOT/'sim/rtl_fft/vectors/fft_golden_v1'
CASES=[name+'_'+window for name in ('zero','dc','impulse','bin16','bin16p35','bin16_bin70') for window in ('rect','hann')]
BASE={name:name for name in CASES}
BASE.update(bin16_rect_recovery='bin16_rect',impulse_hann_recovery='impulse_hann')
SOURCES=['sim/rtl_fft/tb_fft_chain.sv','build/scripts/sim_fft_chain.tcl','build/scripts/sim_fft_rect.tcl','src/reference/fft_chain/verify_fft_chain.py']
SOURCES += ['src/hw/rtl/fft/'+n for n in ('fft_window_axis.v','fft_complex_pack.v','fft_frame_engine.v','fft_ctrl_axi.v','hann_coeff_u16.mem')]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest().upper()
def save(path,data):path.write_text(json.dumps(data,indent=2),encoding='utf-8')
def require(value,message):
    if not value:raise ValueError(message)

def prepare(out):
    out.mkdir(parents=True,exist_ok=False)
    m=json.loads((GOLDEN/'reference_manifest.json').read_text())
    hashes={n:sha(ROOT/n) for n in SOURCES}
    require(sha(ROOT/'src/hw/rtl/fft/hann_coeff_u16.mem')=='795D500FC0B0C0C176B896BE7BA48CDCE473A092D517003C1EB5D7DF358658D3','Frozen coefficient differs')
    for case,base in BASE.items():
        folder=out/case;folder.mkdir()
        for name in ('input_q15.hex','reference.npz','expected_words_u64.npy'):
            require(sha(GOLDEN/base/name)==m['sha256'][base+'/'+name],'Reference changed')
            hashes[str((GOLDEN/base/name).relative_to(ROOT)).replace('\\','/')]=sha(GOLDEN/base/name)
        with np.load(GOLDEN/base/'reference.npz',allow_pickle=False) as r:
            (folder/'input_s24.hex').write_text(''.join(f'{int(x)&0xffffff:06x}\n' for x in r['input_s24']),encoding='ascii')
    cfg=json.loads((ROOT/'src/hw/ip/fft_contract_v1.json').read_text())
    (out/'expected_config.tcldict').write_text(''.join(k+' '+v+'\n' for k,v in cfg['static_properties_verified'].items()),encoding='ascii')
    # The reused project constructor only needs a preparation receipt, not rectangular fixtures.
    save(out/'preparation.json',dict(source_files_sha256=hashes,cases=BASE,status='CHAIN_INPUTS_PREPARED'))
    print('CHAIN_INPUTS_PREPARED: 12 main + 2 recovery')

def hex_values(path):return np.array([int(s,16) for s in path.read_text().splitlines()],dtype=np.uint64)

def verify(out):
    p=json.loads((out/'preparation.json').read_text())
    require(all(sha(ROOT/n)==h for n,h in p['source_files_sha256'].items()),'Source/reference hash changed')
    require((out/'CHAIN_CAPTURE_PASS.txt').exists(),'No terminal capture PASS')
    rows=[]
    for case,base in BASE.items():
        folder=out/case; state=json.loads((folder/'state.json').read_text())
        require(state['source']=='XSIM_RTL_FRAME_ENGINE' and state['case']==case,'Source identity')
        require(all(state[k]==1024 for k in ('captured','fft_inputs','outputs','input_count','output_count')),'Frame lengths')
        expected_status=0x186 if case in ('bin16_rect','bin16_hann') else 0x106
        require(state['status_beats']==1 and state['status']==expected_status,'Frame errors/config/done flags')
        actual=hex_values(folder/'actual_spectrum64.hex')
        accepted=hex_values(folder/'actual_s24.hex'); z=hex_values(folder/'actual_fft_input32.hex')
        with np.load(GOLDEN/base/'reference.npz',allow_pickle=False) as ref:
            require(np.array_equal(accepted,ref['input_s24'].astype(np.int64)&0xffffff),'Actual raw input differs')
            require(np.array_equal(z,ref['fft_input_z'].view(np.uint16).astype(np.uint64)),'RTL conversion/window differs')
            result=compare_words(actual,ref['expected_words'])
        require(result['numerical_pass'],case+': integer output mismatch')
        require(actual.nbytes==8192,'Payload length')
        np.save(folder/'actual_words_u64.npy',actual.astype('<u8'),allow_pickle=False)
        result.update(case=case,base=base,RTL_window_and_packer=True,status=state)
        save(folder/'comparison.json',result);rows.append(result)
    require(sum(r['status']['stall_cycles'] for r in rows)>0,'No exercised output backpressure')
    summary=dict(status='FFT_CHAIN_SIM_PASS',main_cases=12,recovery_frames=2,integer_component_mismatches=0,
                 preprocessing_mismatches=0,actual_RTL_window_packer_control=True,board_accepted=False,results=rows)
    save(out/'summary.json',summary)
    (out/'compare.csv').write_text('case,mismatches,payload_bytes,pass\n'+''.join(r['case']+',0,8192,true\n' for r in rows),encoding='ascii')
    print('FFT_CHAIN_SIM_PASS: 12 main + 2 recovery; raw/window/complex integers exact')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','verify'));p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    try:(prepare if a.action=='prepare' else verify)(a.out.resolve())
    except (ValueError,OSError,KeyError) as e:raise SystemExit(str(e))
