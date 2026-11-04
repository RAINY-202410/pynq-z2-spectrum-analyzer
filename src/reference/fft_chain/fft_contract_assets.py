"""Generate and check A-side candidate window and wire-format fixtures.

These fixtures do not constitute RTL FFT validation or A/B contract approval.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

N = 1024


def q24_to_q15(samples):
    data = np.asarray(samples)
    if not np.issubdtype(data.dtype, np.integer):
        raise ValueError('24-bit input must contain integers')
    if np.any(data < -(1 << 23)) or np.any(data > (1 << 23) - 1):
        raise ValueError('Input outside signed 24-bit range')
    return (data.astype(np.int64) >> 8).astype(np.int16)


def signed16(values):
    data = np.asarray(values)
    if not np.issubdtype(data.dtype, np.integer):
        raise ValueError('FFT components must contain integers')
    if np.any(data < -32768) or np.any(data > 32767):
        raise ValueError('Component outside signed 16-bit range')
    return data.astype(np.int16)


def apply_window(q15, coefficients=None):
    data = signed16(q15)
    if data.shape != (N,):
        raise ValueError('Expected 1024 samples')
    if coefficients is None:
        return data.copy()
    coeff = np.asarray(coefficients)
    if coeff.shape != (N,) or not np.issubdtype(coeff.dtype, np.integer):
        raise ValueError('Expected 1024 integer coefficients')
    if np.any(coeff < 0) or np.any(coeff > 32768):
        raise ValueError('Coefficient outside unsigned /32768 range')
    product = data.astype(np.int64) * coeff.astype(np.int64)
    return (product >> 15).astype(np.int16)


def pack_complex(real, imag):
    real, imag = signed16(real), signed16(imag)
    if real.shape != imag.shape:
        raise ValueError('Component shapes differ')
    low = real.astype(np.int32).view(np.uint32).astype(np.uint64)
    high = imag.astype(np.int32).view(np.uint32).astype(np.uint64)
    return (low | (high << np.uint64(32))).astype('<u8')


def unpack_complex(words):
    data = np.asarray(words, dtype=np.uint64)
    real = (data & np.uint64(0xFFFFFFFF)).astype(np.uint32).view(np.int32)
    imag = (data >> np.uint64(32)).astype(np.uint32).view(np.int32)
    signed16(real)
    signed16(imag)
    return real, imag


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    window = np.hanning(N)
    coeff = np.rint(window * 32768).astype(np.uint16)
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    raw = np.array([-8388608, -8388353, -257, -256, -255, -1, 0, 1, 255, 256, 8388607], dtype=np.int64)
    expected = np.array([-32768, -32768, -2, -1, -1, -1, 0, 0, 0, 1, 32767], dtype=np.int16)
    check('signed24_boundary_shift', np.array_equal(q24_to_q15(raw), expected))
    representable = np.arange(-32768, 32768, dtype=np.int64)
    check('all_q15_exact_q24_roundtrip', np.array_equal(q24_to_q15(representable * 256), representable))
    for invalid in (np.array([8388608]), np.array([0.5])):
        try:
            q24_to_q15(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid signed24 input accepted')
    checks.append('invalid_signed24_inputs_rejected')
    check('coefficient_count_and_type', coeff.shape == (N,) and coeff.dtype == np.uint16)
    check('coefficient_range', coeff.min() == 0 and coeff.max() <= 32768)
    check('coefficient_endpoints', coeff[0] == 0 and coeff[-1] == 0)
    check('coefficient_symmetry', np.array_equal(coeff, coeff[::-1]))
    formula = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / (N - 1))
    check('hann_denominator_1023', np.allclose(window, formula, rtol=0, atol=5e-16))
    q15 = np.resize(expected, N)
    check('rectangular_exact_bypass', np.array_equal(apply_window(q15), q15))
    check('exact_unit_coefficient', np.array_equal(apply_window(q15, np.full(N, 32768, dtype=np.uint16)), q15))
    check('zero_coefficient', not np.any(apply_window(q15, np.zeros(N, dtype=np.uint16))))
    z = apply_window(q15, coeff)
    exact = q15.astype(np.float64) * coeff.astype(np.float64) / 32768
    check('hann_floor_error_under_one_lsb', np.all(z <= exact) and np.all(exact < z.astype(np.float64) + 1))
    real = np.resize(np.array([-32768, -1, 0, 1, 32767, 1234, -1234], dtype=np.int16), N)
    imag = np.resize(np.array([32767, 2, 0, -1, -32768, -1234, 1234], dtype=np.int16), N)
    words = pack_complex(real, imag)
    decoded_real, decoded_imag = unpack_complex(words)
    check('complex_pack_roundtrip', np.array_equal(decoded_real, real) and np.array_equal(decoded_imag, imag))
    check('negative_real_positive_imag_example', int(words[1]) == 0x00000002FFFFFFFF)
    check('payload_8192_bytes', words.nbytes == 8192)
    check('little_endian_first_word', words.tobytes()[:8] == int(words[0]).to_bytes(8, 'little'))
    try:
        unpack_complex(np.array([0x0000000000008000], dtype=np.uint64))
    except ValueError:
        checks.append('invalid_sign_extension_rejected')
    else:
        raise AssertionError('Invalid sign extension accepted')

    np.save(output / 'hann_coeff_u16.npy', coeff, allow_pickle=False)
    (output / 'hann_coeff_u16.hex').write_text(''.join(f'{int(v):04x}\n' for v in coeff), encoding='ascii')
    np.save(output / 'interface_words_u64.npy', words, allow_pickle=False)
    np.savetxt(output / 'interface_expected.csv', np.column_stack((np.arange(N), real, imag)), fmt='%d', delimiter=',', header='index,real,imag', comments='')
    readback = np.array([int(line, 16) for line in (output / 'hann_coeff_u16.hex').read_text(encoding='ascii').splitlines()], dtype=np.uint16)
    check('coefficient_hex_npy_roundtrip', np.array_equal(readback, np.load(output / 'hann_coeff_u16.npy', allow_pickle=False)))
    files = ['hann_coeff_u16.npy', 'hann_coeff_u16.hex', 'interface_words_u64.npy', 'interface_expected.csv']
    manifest = {
        'status': 'A_PREPARED_PENDING_B_CONFIRMATION', 'N': N,
        'window': 'symmetric Hann, denominator N-1=1023',
        'coefficient_format': 'uint16 / 32768; numpy.rint ties to even',
        'numpy_version': np.__version__, 'coefficient_sum': int(coeff.astype(np.int64).sum()),
        'window_sum': float(coeff.astype(np.int64).sum() / 32768),
        'rectangular_window_sum': N, 'coefficient_min': int(coeff.min()), 'coefficient_max': int(coeff.max()),
        'input_conversion': 'signed24 arithmetic right shift by 8',
        'window_conversion': 'signed int64 product arithmetic right shift by 15',
        'output_layout': 'low32=sign_extended_real16, high32=sign_extended_imag16, little-endian',
        'fixture_source': 'digital layout examples, not actual FFT output',
        'sha256': {name: hashlib.sha256((output / name).read_bytes()).hexdigest().upper() for name in files},
        'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper(),
        'checks_passed': len(checks), 'checks': checks,
        'rtl_verified': False, 'B_confirmed': False,
    }
    (output / 'window_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'checks_passed': len(checks), 'coefficient_sum': manifest['coefficient_sum'], 'window_sum': manifest['window_sum'], 'directory': str(output.resolve())}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    generate(parser.parse_args().out)
