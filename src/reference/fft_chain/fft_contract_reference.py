"""A v1.0 FFT golden data: official xfft 9.1 C model, not RTL/board output.

Windows x64, Python + NumPy. Use the model ZIP from the installed Vivado 2026.1.
The compare command checks numerical data only; protocol/status need RTL checks.
"""
import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import zipfile

import numpy as np

from fft_contract_assets import N, apply_window, pack_complex, q24_to_q15, signed16, unpack_complex

SHIFTS = (3, 2, 2, 2, 2)
GENERICS = dict(C_NFFT_MAX=10, C_ARCH=3, C_HAS_NFFT=0, C_USE_FLT_PT=0,
                C_INPUT_WIDTH=16, C_TWIDDLE_WIDTH=16, C_HAS_SCALING=1,
                C_HAS_BFP=0, C_HAS_ROUNDING=1, C_NSSR=1, C_SYSTOLICFFT_INV=0)


class Generics(ct.Structure):
    _fields_ = [(name, ct.c_int) for name in GENERICS]


class Inputs(ct.Structure):
    _fields_ = [('nfft', ct.c_int), ('xn_re', ct.POINTER(ct.c_double)),
                ('xn_re_size', ct.c_int), ('xn_im', ct.POINTER(ct.c_double)),
                ('xn_im_size', ct.c_int), ('scaling_sch', ct.POINTER(ct.c_int)),
                ('scaling_sch_size', ct.c_int), ('direction', ct.c_int)]


class Outputs(ct.Structure):
    _fields_ = [('xk_re', ct.POINTER(ct.c_double)), ('xk_re_size', ct.c_int),
                ('xk_im', ct.POINTER(ct.c_double)), ('xk_im_size', ct.c_int),
                ('blk_exp', ct.c_int), ('overflow', ct.c_int)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class FFTModel:
    def __init__(self, model_zip, work):
        work.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(model_zip) as bundle:
            names = [name for name in bundle.namelist()
                     if name.endswith('.dll') or name == 'xfft_v9_1_bitacc_cmodel.h']
            for name in names:
                if Path(name).name != name:
                    raise ValueError('Unexpected model ZIP layout')
                (work / name).write_bytes(bundle.read(name))
        self.provenance = {'installed_zip': str(model_zip.resolve()),
                           'zip_sha256': sha(model_zip),
                           'files': {name: sha(work / name) for name in names}}
        self.dll_directory = os.add_dll_directory(str(work.resolve()))
        dll = ct.CDLL(str((work / 'libIp_xfft_v9_1_bitacc_cmodel.dll').resolve()))
        prefix = 'xilinx_ip_xfft_v9_1_'
        self.create = getattr(dll, prefix + 'create_state')
        self.create.argtypes, self.create.restype = [Generics], ct.c_void_p
        self.simulate = getattr(dll, prefix + 'bitacc_simulate')
        self.simulate.argtypes = [ct.c_void_p, Inputs, ct.POINTER(Outputs)]
        self.simulate.restype = ct.c_int
        self.destroy = getattr(dll, prefix + 'destroy_state')
        self.destroy.argtypes, self.destroy.restype = [ct.c_void_p], None
        self.dll = dll

    def run(self, z):
        z = signed16(z)
        if z.shape != (N,):
            raise ValueError('Expected 1024 signed16 samples')
        array = ct.c_double * N
        real, imag = array(*(z.astype(np.float64) / 32768)), array()
        result_re, result_im = array(), array()
        schedule = (ct.c_int * len(SHIFTS))(*SHIFTS)
        inputs = Inputs(10, real, N, imag, N, schedule, len(SHIFTS), 1)
        outputs = Outputs(result_re, N, result_im, N, 0, 0)
        state = self.create(Generics(**GENERICS))
        if not state:
            raise RuntimeError('C model could not create state')
        try:
            code = self.simulate(state, inputs, ct.byref(outputs))
            if code or outputs.xk_re_size != N or outputs.xk_im_size != N:
                raise RuntimeError(f'C model failed: {code}, sizes {outputs.xk_re_size}/{outputs.xk_im_size}')
            if outputs.overflow:
                raise RuntimeError('C model overflow: this frame is invalid')
            components = np.column_stack((result_re, result_im)) * 32768
            # Scaled fixed-point output must already lie exactly on the Q1.15 grid.
            if not np.all(np.isfinite(components)) or not np.array_equal(components, np.rint(components)):
                raise RuntimeError('C model output is not exact Q1.15')
            return signed16(components.astype(np.int64))
        finally:
            self.destroy(state)


def compare_words(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    for data in (actual, expected):
        if data.shape != (N,) or data.dtype.kind != 'u' or data.dtype.itemsize != 8:
            raise ValueError('Expected 1024 uint64 complex words')
    ar, ai = unpack_complex(actual)
    er, ei = unpack_complex(expected)
    difference = np.column_stack((ar - er, ai - ei)).astype(np.int64)
    return {'numerical_pass': not np.any(difference),
            'mismatching_components': int(np.count_nonzero(difference)),
            'max_component_error_integer_lsb': int(np.abs(difference).max()),
            'protocol_and_status_checked': False}


def generate(model_zip, work, output, coefficients):
    output.mkdir(parents=True, exist_ok=False)
    coeff = np.load(coefficients, allow_pickle=False)
    if sha(coefficients) != 'BACC802AC2A4DFC905EE7551C1DC404268BA42A435D3ADCE2C9D5F3D8D6B5B23':
        raise ValueError('Use the frozen v1 Hann coefficient NPY')
    model = FFTModel(model_zip, work)
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    zero = np.zeros(N, dtype=np.int16)
    check('zero_exact', not np.any(model.run(zero)))
    for value in (8192, -8192):
        result = model.run(np.full(N, value, dtype=np.int16))
        expected = np.zeros((N, 2), dtype=np.int16)
        expected[0, 0] = value // 2  # N / 2**11 = 1/2, independently known DC gain.
        check(f'dc_{value}_exact', np.array_equal(result, expected))
    impulse = zero.copy()
    impulse[0] = 16384
    result = model.run(impulse)
    check('impulse_origin_scale_exact', np.all(result[:, 0] == 8) and not np.any(result[:, 1]))

    n = np.arange(N)
    vectors = {'zero': np.zeros(N), 'dc': np.full(N, 0.25),
               'impulse': np.where(n == 512, 0.5, 0.0),
               'bin16': 0.5 * np.sin(2 * np.pi * 16 * n / N),
               'bin16p35': 0.5 * np.sin(2 * np.pi * 16.35 * n / N),
               'bin16_bin70': 0.25 * np.sin(2 * np.pi * 16 * n / N)
                              + 0.125 * np.sin(2 * np.pi * 70 * n / N)}
    cases = []
    for name, vector in vectors.items():
        q15 = signed16(np.rint(vector * 32768).astype(np.int64))
        raw24 = q15.astype(np.int32) * 256
        check(name + '_signed24_roundtrip', np.array_equal(q24_to_q15(raw24), q15))
        for window in ('rect', 'hann'):
            case = output / (name + '_' + window)
            case.mkdir()
            z = apply_window(q15, coeff if window == 'hann' else None)
            components = model.run(z)
            words = pack_complex(components[:, 0], components[:, 1])
            decoded = np.column_stack(unpack_complex(words))
            check(case.name + '_packing', np.array_equal(decoded, components))
            reference = np.fft.fft(z.astype(np.float64) / 32768)
            reconstructed = (components[:, 0].astype(np.float64)
                             + 1j * components[:, 1]) / 32768 * 2**sum(SHIFTS)
            error = reconstructed - reference
            if name == 'bin16' and window == 'rect':
                peak = int(np.argmax(np.abs(reconstructed[:N // 2 + 1])))
                check('bin16_natural_forward_sign', peak == 16 and components[16, 1] < 0)
                check('fresh_state_repeatability', np.array_equal(components, model.run(z)))
            np.savez(case / 'reference.npz', input_s24=raw24, input_q15=q15, fft_input_z=z,
                     expected_real=components[:, 0], expected_imag=components[:, 1],
                     expected_words=words, diagnostic_float_fft=reference)
            np.save(case / 'expected_words_u64.npy', words, allow_pickle=False)
            (case / 'input_q15.hex').write_text(''.join(f'{int(v) & 65535:04x}\n' for v in q15), encoding='ascii')
            cases.append({'case': case.name, 'model_overflow': False,
                          'max_complex_error_unscaled_fft_diagnostic': float(np.abs(error).max()),
                          'complex_rmse_unscaled_fft_diagnostic': float(np.sqrt(np.mean(np.abs(error)**2))),
                          'relative_l2_diagnostic': float(np.linalg.norm(error) / np.linalg.norm(reference))
                          if np.any(reference) else None})
    corrupt = words.copy()
    corrupt[0] = np.uint64(int(corrupt[0]) ^ 1)
    check('comparator_rejects_one_lsb_corruption', not compare_words(corrupt, words)['numerical_pass'])
    files = {str(p.relative_to(output)).replace('\\', '/'): sha(p)
             for p in sorted(output.rglob('*')) if p.is_file()}
    manifest = {'contract': 'v1.0', 'authority': 'A', 'source': 'OFFICIAL_C_MODEL_NOT_RTL',
                'generics': GENERICS, 'group_shifts_first_to_last': SHIFTS,
                'config_word': '0x0557', 'direction': 1, 'order': 'natural',
                'coefficient_sha256': sha(coefficients), 'model': model.provenance,
                'generator_sha256': sha(Path(__file__)), 'numpy_version': np.__version__,
                'input_definition': 'n=0..1023; q15=rint_ties_even(x*32768); raw24=q15*256; impulse at n=512',
                'acceptance': 'zero integer-component mismatches; no overflow; protocol checked separately',
                'float_metrics': 'diagnostic only, not acceptance thresholds',
                'checks_passed': len(checks), 'checks': checks, 'cases': cases, 'sha256': files,
                'rtl_simulated': False, 'board_accepted': False, 'B_confirmed': False}
    (output / 'reference_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'C_MODEL_REFERENCE_PASS', 'cases': len(cases),
                      'checks_passed': len(checks), 'output': str(output.resolve())}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    gen = commands.add_parser('generate')
    for flag in ('model-zip', 'work', 'out', 'coefficients'):
        gen.add_argument('--' + flag, type=Path, required=True)
    compare = commands.add_parser('compare')
    compare.add_argument('--actual', type=Path, required=True)
    compare.add_argument('--expected', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'generate':
        generate(args.model_zip, args.work, args.out, args.coefficients)
    else:
        result = compare_words(np.load(args.actual, allow_pickle=False), np.load(args.expected, allow_pickle=False))
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['numerical_pass'] else 1)
