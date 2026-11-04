"""B-X02: index the archived export02 session without rerunning an FFT.

The reader keeps two separate data sets:

* ``spectral_samples``: saved raw words with a complete 1024-point complex
  spectrum. These are parsed through the frozen ``fft_session.load_frame``
  adapter, which validates hashes and frame metadata and restores the already
  measured PL FFT result.
* ``metric_timeline``: every row from ``frames.jsonl``, including frames for
  which no complete spectrum was retained.

The original acquisition mode is recorded as ``source_mode=LIVE``. Loading an
archived frame is marked ``load_mode=REPLAY`` and does not claim a new board
observation.
"""

import argparse
import hashlib
import io
import json
import math
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np

EXTENSION_ROOT = Path(__file__).resolve().parent
BASELINE_PYNQ = EXTENSION_ROOT / "baseline_readonly" / "host_tools" / "sw" / "pynq"
if str(BASELINE_PYNQ) not in sys.path:
    sys.path.insert(0, str(BASELINE_PYNQ))

import fft_session

STEP = "B-X02"
CREATED_DATE = "2026-10-31"
DEFAULT_SESSION = EXTENSION_ROOT / "inputs_readonly" / "spectrum_session_a79f9a7236b2_export02.zip"
DEFAULT_AUDIT = EXTENSION_ROOT / "inputs_readonly" / "export02_audit.json"
DEFAULT_OUTPUT_NAME = "B-X02"
EXPECTED_SESSION_SHA256 = "3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E"

N_FFT = 1024
FRAME_BYTES = 8192
WINDOW_SUM = {"hann": 511.50006103515625, "rect": 1024.0}

# The four representative runs requested by B-X02. Other runs remain in the
# source session and are deliberately not merged into these groups.
SELECTED_RUNS = [
    {
        "run_id": "spectrum_569e5f254203",
        "label": "long_hann_tone1k",
        "scenario": "tone1k",
        "window": "hann",
        "expected_tones_hz": [1000.0],
        "description": "620-second Hann single-tone long run",
    },
    {
        "run_id": "spectrum_f5953d8dcaa0",
        "label": "dual_rect",
        "scenario": "dual",
        "window": "rect",
        "expected_tones_hz": [1000.0, 3000.0],
        "description": "40-frame rectangular dual-tone run",
    },
    {
        "run_id": "spectrum_38749b56cab6",
        "label": "dual_hann",
        "scenario": "dual",
        "window": "hann",
        "expected_tones_hz": [1000.0, 3000.0],
        "description": "40-frame Hann dual-tone run",
    },
    {
        "run_id": "spectrum_15131a729d8b",
        "label": "analog_silence",
        "scenario": "silence",
        "window": "hann",
        "expected_tones_hz": [],
        "description": "40-frame analog-silence observation",
    },
]


class SessionDataError(ValueError):
    """Raised when an archive member, hash, or frame contract is inconsistent."""


def sha256_bytes(blob):
    return hashlib.sha256(blob).hexdigest().upper()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def _member(archive, name):
    try:
        return archive.read(name)
    except KeyError:
        raise SessionDataError("missing ZIP member: " + name)


def _json_member(archive, name):
    try:
        return json.loads(_member(archive, name).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SessionDataError("invalid JSON member: " + name) from exc


def _join(root, name):
    root = str(root)
    return name if root in ("", ".") else root.rstrip("/") + "/" + name.lstrip("/")


def _display_path(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(EXTENSION_ROOT).as_posix()
    except ValueError:
        return str(path)


def _open_zip(blob, label):
    try:
        return zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise SessionDataError("invalid ZIP: " + label) from exc


def _session_root(archive):
    names = [n for n in archive.namelist()
             if n == "session_manifest.json" or n.endswith("/session_manifest.json")]
    if len(names) != 1:
        raise SessionDataError("expected exactly one session_manifest.json")
    return PurePosixPath(names[0]).parent


def _expected_session_hash(session_path):
    session_path = Path(session_path).resolve()
    if session_path == DEFAULT_SESSION.resolve() and DEFAULT_AUDIT.is_file():
        audit = json.loads(DEFAULT_AUDIT.read_text(encoding="utf-8"))
        value = audit.get("archive_sha256")
        if value:
            return value.upper()
    return EXPECTED_SESSION_SHA256 if session_path == DEFAULT_SESSION.resolve() else None


def _find_run_archive(session_archive, root, session_manifest, run_id):
    prefix = "runs/" + run_id + "_export"
    matches = [name for name in session_manifest.get("files_sha256", {})
               if name.startswith(prefix) and name.endswith(".zip")]
    if len(matches) != 1:
        raise SessionDataError("expected one run archive for {}; got {}".format(run_id, matches))
    relative = matches[0]
    member = _join(root, relative)
    blob = _member(session_archive, member)
    actual = sha256_bytes(blob)
    expected = session_manifest["files_sha256"][relative].upper()
    if actual != expected:
        raise SessionDataError("run archive hash mismatch: {} expected {} got {}".format(
            member, expected, actual))
    return relative, member, blob, actual


def _inspect_run(run_blob, run_id, run_spec, session_relative, session_member,
                 run_sha256, session_path, session_sha256):
    with _open_zip(run_blob, session_member) as run_archive:
        names = [name for name in run_archive.namelist() if not name.endswith("/")]
        manifests = [name for name in names
                     if name.startswith(run_id + "/export_manifest_") and name.endswith(".json")]
        if len(manifests) != 1:
            raise SessionDataError("expected one export manifest in " + session_member)
        manifest_member = manifests[0]
        run_root = PurePosixPath(manifest_member).parent
        if str(run_root) != run_id:
            raise SessionDataError("run manifest root mismatch: " + str(run_root))

        export_manifest = _json_member(run_archive, manifest_member)
        listed = {name: value.upper() for name, value in
                  export_manifest.get("files_sha256", {}).items()}
        for relative, expected in listed.items():
            member = _join(run_root, relative)
            if member not in names:
                raise SessionDataError("missing run member listed in export manifest: " + member)
            actual = sha256_bytes(_member(run_archive, member))
            if actual != expected:
                raise SessionDataError("run member hash mismatch: {} expected {} got {}".format(
                    member, expected, actual))

        extras = []
        for name in names:
            if not name.startswith(str(run_root) + "/"):
                continue
            relative = name[len(str(run_root)) + 1:]
            if relative in listed:
                continue
            if relative.startswith("export_manifest_") and relative.endswith(".json"):
                continue
            extras.append(relative)
        if extras:
            raise SessionDataError("unlisted run members: " + ", ".join(sorted(extras)))

        summary_member = _join(run_root, "summary.json")
        frames_member = _join(run_root, "frames.jsonl")
        settings_member = _join(run_root, "settings.json")
        summary = _json_member(run_archive, summary_member)
        settings = _json_member(run_archive, settings_member)
        settings_data = settings.get("settings", {})
        frames_blob = _member(run_archive, frames_member)
        frames_text = frames_blob.decode("utf-8")
        frames_sha256 = sha256_bytes(frames_blob)

        if summary.get("source") != "PL_FFT" or summary.get("mode") != "LIVE":
            raise SessionDataError("unexpected run source/mode: " + run_id)
        if summary.get("context") != "BOARD_LIVE":
            raise SessionDataError("run is not BOARD_LIVE: " + run_id)
        if settings_data.get("window") != run_spec["window"]:
            raise SessionDataError("window mismatch in " + run_id)
        if list(settings_data.get("expected_tones_hz", [])) != run_spec["expected_tones_hz"]:
            raise SessionDataError("expected-tone mismatch in " + run_id)
        fs_hz = float(summary["source_info"]["fs_hz"])
        if not math.isfinite(fs_hz) or fs_hz <= 0:
            raise SessionDataError("invalid fs for " + run_id)
        if summary.get("board_accepted") is not False:
            raise SessionDataError("B-X02 expects board_accepted=false in " + run_id)

        rows = []
        previous_elapsed = None
        previous_sequence = None
        sequence_gaps = []
        for line_number, raw in enumerate(frames_text.splitlines(), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except ValueError as exc:
                raise SessionDataError("invalid frames.jsonl row {} in {}".format(
                    line_number, run_id)) from exc
            frame_id = row.get("frame_id")
            if type(frame_id) is not int or frame_id != len(rows) + 1:
                raise SessionDataError("unexpected frame_id {} in {} at line {}".format(
                    frame_id, run_id, line_number))
            elapsed = float(row["elapsed_s"])
            if not math.isfinite(elapsed) or (previous_elapsed is not None and elapsed < previous_elapsed):
                raise SessionDataError("nonmonotonic/NaN elapsed_s in " + run_id)
            capture = row.get("capture")
            if not isinstance(capture, dict) or not isinstance(capture.get("after"), dict):
                raise SessionDataError("missing capture.after in " + run_id)
            if capture.get("source") != "PL_FFT" or capture.get("window") != run_spec["window"]:
                raise SessionDataError("frame source/window mismatch in " + run_id)
            if capture.get("N") != N_FFT or float(capture.get("fs_hz", "nan")) != fs_hz:
                raise SessionDataError("frame N/fs mismatch in " + run_id)
            sequence = capture["after"].get("frame_sequence")
            if type(sequence) is not int:
                raise SessionDataError("missing hardware sequence in " + run_id)
            if previous_sequence is not None and sequence != ((previous_sequence + 1) & 0xFFFFFFFF):
                sequence_gaps.append({
                    "after_frame_id": rows[-1]["frame_id"],
                    "before_frame_id": frame_id,
                    "after_sequence": previous_sequence,
                    "before_sequence": sequence,
                })
            metrics = row.get("metrics")
            if not isinstance(metrics, dict):
                raise SessionDataError("missing per-frame metrics in " + run_id)
            rows.append({
                "line_number": line_number,
                "raw": raw,
                "row": row,
                "frame_id": frame_id,
                "sequence": sequence,
                "elapsed_s": elapsed,
            })
            previous_elapsed = elapsed
            previous_sequence = sequence

        if len(rows) != summary.get("frames"):
            raise SessionDataError("frames.jsonl count {} != summary {} for {}".format(
                len(rows), summary.get("frames"), run_id))

        saved = sorted(summary.get("saved_samples", []), key=lambda item: item["frame_id"])
        actual_words = sorted(
            name[len(str(run_root)) + 1:-len("_words.npy")]
            for name in names
            if name.startswith(str(run_root) + "/frame_") and name.endswith("_words.npy")
        )
        summary_stems = sorted(item["stem"] for item in saved)
        if actual_words != summary_stems:
            raise SessionDataError("saved sample files differ from summary in " + run_id)

        frame_by_id = {item["frame_id"]: item for item in rows}
        metric_records = []
        for item in rows:
            row = item["row"]
            metrics = row.get("metrics", {})
            peaks = metrics.get("peaks") or []
            top = peaks[0] if peaks else {}
            after = row["capture"].get("after", {})
            metric_record = {
                "record_type": "metric",
                "run_id": run_id,
                "run_label": run_spec["label"],
                "scenario": run_spec["scenario"],
                "frame_id": item["frame_id"],
                "source_mode": "LIVE",
                "mode": "LIVE",
                "index_mode": "OFFLINE_INDEX",
                "context": "BOARD_LIVE",
                "sequence": item["sequence"],
                "elapsed_s": item["elapsed_s"],
                "window": run_spec["window"],
                "fs_hz": fs_hz,
                "N": N_FFT,
                "source_member": frames_member,
                "source_sha256": frames_sha256,
                "line_number": item["line_number"],
                "line_sha256": sha256_bytes(item["raw"].encode("utf-8")),
                "capture_success": row["capture"].get("success"),
                "capture_error": row["capture"].get("error"),
                "capture_after": {
                    "dmasr": after.get("dmasr"),
                    "pl_status": after.get("pl_status"),
                    "input_count": after.get("input_count"),
                    "output_count": after.get("output_count"),
                    "length": after.get("length"),
                    "window_requested": after.get("window_requested"),
                    "frame_sequence": after.get("frame_sequence"),
                    "i2s_live": after.get("i2s_live"),
                },
                "metrics": metrics,
                "peak_bin": top.get("bin"),
                "peak_hz": top.get("frequency_hz"),
                "estimated_peak_hz": top.get("estimated_frequency_hz"),
                "peak_dbfs": top.get("dbfs"),
                "tone_checks_passed": metrics.get("tone_checks_passed"),
                "nonzero_bins": metrics.get("nonzero_bins"),
                "max_nondc_dbfs": metrics.get("max_nondc_dbfs"),
                "amplitude_calibrated": metrics.get("amplitude_calibrated", False),
                "bin_width_hz": metrics.get("bin_width_hz", fs_hz / N_FFT),
            }
            metric_records.append(metric_record)

        samples = []
        saved_fft_matches = 0
        for saved_item in saved:
            frame_id = saved_item["frame_id"]
            if frame_id not in frame_by_id:
                raise SessionDataError("saved frame missing from frames.jsonl: {}".format(frame_id))
            frame_meta = frame_by_id[frame_id]
            sequence = frame_meta["sequence"]
            if sequence != saved_item["sequence"]:
                raise SessionDataError("saved sequence mismatch for {} frame {}".format(run_id, frame_id))

            stem = saved_item["stem"]
            words_member = _join(run_root, stem + "_words.npy")
            state_member = _join(run_root, stem + "_state.json")
            fft_member = _join(run_root, stem + "_fft.npy")
            words_blob = _member(run_archive, words_member)
            state_blob = _member(run_archive, state_member)
            words_sha = sha256_bytes(words_blob)
            state_sha = sha256_bytes(state_blob)
            if words_sha != saved_item["words_sha256"].upper():
                raise SessionDataError("saved words hash mismatch for {} frame {}".format(
                    run_id, frame_id))
            state = json.loads(state_blob.decode("utf-8"))
            if state.get("words_sha256", "").upper() != words_sha:
                raise SessionDataError("state words hash mismatch for {} frame {}".format(
                    run_id, frame_id))
            if state.get("source") != "PL_FFT" or state.get("success") is not True:
                raise SessionDataError("saved state is not a successful PL frame: {} frame {}".format(
                    run_id, frame_id))
            if state.get("N") != N_FFT or state.get("window") != run_spec["window"]:
                raise SessionDataError("saved state N/window mismatch: {} frame {}".format(
                    run_id, frame_id))
            if float(state.get("fs_hz", "nan")) != fs_hz:
                raise SessionDataError("saved state fs mismatch: {} frame {}".format(
                    run_id, frame_id))
            if state.get("window_sum") != WINDOW_SUM[run_spec["window"]] or state.get("scale_shift") != 11:
                raise SessionDataError("saved state scale/window_sum mismatch: {} frame {}".format(
                    run_id, frame_id))
            if state.get("after", {}).get("frame_sequence") != sequence:
                raise SessionDataError("saved state sequence mismatch: {} frame {}".format(
                    run_id, frame_id))

            # Reuse the frozen adapter exactly. It checks the words hash again,
            # validates the frame metadata, and restores the PL result.
            with tempfile.TemporaryDirectory(prefix="b_plus_v1_bx02_") as temp_dir:
                words_path = Path(temp_dir) / (stem + "_words.npy")
                state_path = Path(temp_dir) / (stem + "_state.json")
                words_path.write_bytes(words_blob)
                state_path.write_bytes(state_blob)
                parsed = fft_session.load_frame(words_path, state_path)

            if parsed.get("source") != "PL_FFT" or parsed.get("mode") != "REPLAY":
                raise SessionDataError("parser did not return a PL_FFT replay frame")
            if parsed.get("sequence") != sequence or parsed.get("N") != N_FFT:
                raise SessionDataError("parsed frame identity mismatch: {} frame {}".format(
                    run_id, frame_id))
            if parsed.get("window_name") != run_spec["window"] or parsed.get("fs_hz") != fs_hz:
                raise SessionDataError("parsed frame window/fs mismatch: {} frame {}".format(
                    run_id, frame_id))
            if np.asarray(parsed["amplitude"]).shape != (N_FFT // 2 + 1,):
                raise SessionDataError("parsed one-sided spectrum has wrong length")

            fft_sha = None
            saved_fft_matches_parser = None
            if fft_member in names:
                fft_blob = _member(run_archive, fft_member)
                fft_sha = sha256_bytes(fft_blob)
                saved_fft = np.load(io.BytesIO(fft_blob), allow_pickle=False)
                saved_fft_matches_parser = bool(np.array_equal(parsed["X"], saved_fft))
                if not saved_fft_matches_parser:
                    raise SessionDataError("saved FFT differs from parsed hardware words: {} frame {}".format(
                        run_id, frame_id))
                saved_fft_matches += 1

            amplitude = np.asarray(parsed["amplitude"], dtype=float)
            peak_bin = int(np.argmax(amplitude[1:]) + 1)
            peak_hz = float(parsed["frequency_hz"][peak_bin])
            peak_dbfs = float(20.0 * np.log10(max(amplitude[peak_bin], 1e-12)))
            metric_record = metric_records[frame_id - 1]
            sample = {
                "record_type": "spectral_sample",
                "run_id": run_id,
                "run_label": run_spec["label"],
                "scenario": run_spec["scenario"],
                "frame_id": frame_id,
                "stem": stem,
                "source_mode": "LIVE",
                "mode": "LIVE",
                "load_mode": "REPLAY",
                "index_mode": "OFFLINE_INDEX",
                "context": "BOARD_LIVE",
                "sequence": sequence,
                "elapsed_s": frame_meta["elapsed_s"],
                "capture_elapsed_s": float(parsed["elapsed_s"]),
                "window": run_spec["window"],
                "fs_hz": fs_hz,
                "N": N_FFT,
                "expected_tones_hz": run_spec["expected_tones_hz"],
                "source_archive": _display_path(session_path),
                "source_archive_sha256": session_sha256,
                "run_archive_member": session_member,
                "run_archive_sha256": run_sha256,
                "session_manifest_run_key": session_relative,
                "words_member": words_member,
                "words_sha256": words_sha,
                "state_member": state_member,
                "state_sha256": state_sha,
                "fft_member": fft_member if fft_sha else None,
                "fft_sha256": fft_sha,
                "metric_line_number": metric_record["line_number"],
                "metric_line_sha256": metric_record["line_sha256"],
                "saved_fft_matches_parser": saved_fft_matches_parser,
                "parsed_peak_bin": peak_bin,
                "parsed_peak_hz": peak_hz,
                "parsed_peak_dbfs": peak_dbfs,
                "tone_checks_passed": metric_record["tone_checks_passed"],
                "nonzero_bins": metric_record["nonzero_bins"],
                "complete_spectrum": True,
                "complex_spectrum_points": N_FFT,
                "one_sided_points": N_FFT // 2 + 1,
                "reexecutes_fft": False,
            }
            samples.append(sample)

        run_summary = {
            "run_id": run_id,
            "label": run_spec["label"],
            "description": run_spec["description"],
            "scenario": run_spec["scenario"],
            "window": run_spec["window"],
            "expected_tones_hz": run_spec["expected_tones_hz"],
            "source_mode": "LIVE",
            "mode": "LIVE",
            "context": "BOARD_LIVE",
            "fs_hz": fs_hz,
            "N": N_FFT,
            "frame_bytes": FRAME_BYTES,
            "scale_shift": 11,
            "window_sum": WINDOW_SUM[run_spec["window"]],
            "run_archive_member": session_member,
            "session_manifest_run_key": session_relative,
            "run_archive_sha256": run_sha256,
            "frames": len(rows),
            "metric_rows": len(rows),
            "saved_samples": len(saved),
            "saved_sample_frame_ids": [item["frame_id"] for item in saved],
            "first_frame_id": rows[0]["frame_id"] if rows else None,
            "last_frame_id": rows[-1]["frame_id"] if rows else None,
            "first_sequence": rows[0]["sequence"] if rows else None,
            "last_sequence": rows[-1]["sequence"] if rows else None,
            "first_elapsed_s": rows[0]["elapsed_s"] if rows else None,
            "last_elapsed_s": rows[-1]["elapsed_s"] if rows else None,
            "summary_elapsed_s": summary.get("elapsed_s"),
            "summary_frame_rate_hz": summary.get("snapshot_frame_rate_hz"),
            "summary_reason": summary.get("reason"),
            "stop_verified": summary.get("stop", {}).get("stop_verified"),
            "continuous_audio": summary.get("continuous_audio"),
            "board_accepted": summary.get("board_accepted"),
            "frames_sha256": frames_sha256,
            "sequence_gaps": sequence_gaps,
            "sequence_contiguous": not sequence_gaps,
            "saved_fft_matches_parser": saved_fft_matches,
        }
        return run_summary, metric_records, samples


def build_index(session_zip=DEFAULT_SESSION, verify_spectra=True, expected_sha256=None):
    """Build the B-X02 index in memory.

    Returns ``(index, metric_records)``. No output is written by this function.
    """
    session_path = Path(session_zip)
    if not session_path.is_file():
        raise SessionDataError("session archive not found: " + str(session_path))
    session_blob = session_path.read_bytes()
    session_sha = sha256_bytes(session_blob)
    expected = (expected_sha256 or _expected_session_hash(session_path))
    if expected and session_sha != expected.upper():
        raise SessionDataError("session archive hash mismatch: expected {} got {}".format(
            expected.upper(), session_sha))

    with _open_zip(session_blob, str(session_path)) as session_archive:
        root = _session_root(session_archive)
        manifest_member = _join(root, "session_manifest.json")
        session_manifest = _json_member(session_archive, manifest_member)
        if session_manifest.get("mode") != "LIVE" or session_manifest.get("context") != "BOARD_LIVE":
            raise SessionDataError("session is not a BOARD_LIVE export")
        if session_manifest.get("board_accepted") is not False:
            raise SessionDataError("B-X02 expects board_accepted=false")

        all_runs = list(session_manifest.get("runs", []))
        selected_ids = [item["run_id"] for item in SELECTED_RUNS]
        missing_runs = [run_id for run_id in selected_ids if run_id not in all_runs]
        if missing_runs:
            raise SessionDataError("selected runs absent from session manifest: " + ", ".join(missing_runs))

        run_summaries = []
        metric_records = []
        spectral_samples = []
        saved_fft_total = 0
        warnings = []
        for run_spec in SELECTED_RUNS:
            session_relative, session_member, run_blob, run_sha = _find_run_archive(
                session_archive, root, session_manifest, run_spec["run_id"])
            run_summary, run_metrics, run_samples = _inspect_run(
                run_blob, run_spec["run_id"], run_spec, session_relative, session_member,
                run_sha, str(session_path), session_sha)
            run_summaries.append(run_summary)
            metric_records.extend(run_metrics)
            spectral_samples.extend(run_samples)
            saved_fft_total += run_summary["saved_fft_matches_parser"]
            for gap in run_summary["sequence_gaps"]:
                warnings.append({
                    "run_id": run_summary["run_id"],
                    "kind": "hardware_sequence_gap",
                    "detail": gap,
                })

    if verify_spectra and len(spectral_samples) != sum(item["saved_samples"] for item in run_summaries):
        raise SessionDataError("spectral sample total does not match run summaries")
    if len(metric_records) != sum(item["metric_rows"] for item in run_summaries):
        raise SessionDataError("metric timeline total does not match run summaries")

    index = {
        "schema_version": 1,
        "extension": "b_plus_v1",
        "step": STEP,
        "created": CREATED_DATE,
        "timezone": "Asia/Shanghai",
        "source_session": {
            "path": _display_path(session_path),
            "bytes": len(session_blob),
            "sha256": session_sha,
            "expected_sha256": expected.upper() if expected else None,
            "context": "BOARD_LIVE",
            "mode": "LIVE",
            "instance_id": session_manifest.get("instance_id"),
            "source_runs_total": len(all_runs),
            "selected_runs": selected_ids,
        },
        "parser": {
            "module": "baseline_readonly/host_tools/sw/pynq/fft_session.py",
            "function": "fft_session.load_frame",
            "n_fft": N_FFT,
            "frame_bytes": FRAME_BYTES,
            "complex_points": N_FFT,
            "one_sided_points": N_FFT // 2 + 1,
            "scale_shift": 11,
            "window_sum": WINDOW_SUM,
            "reexecutes_fft": False,
            "uses_saved_pl_complex_result": True,
        },
        "selection": {
            "labels": [item["label"] for item in SELECTED_RUNS],
            "rule": "four representative runs requested by B-X02; never merge across runs/windows",
            "all_session_runs": all_runs,
        },
        "runs": run_summaries,
        "spectral_samples": spectral_samples,
        "metric_timeline": {
            "path": "metric_timeline.jsonl",
            "record_count": len(metric_records),
            "sha256": None,
            "description": "one record per frames.jsonl row; full per-frame metrics",
        },
        "verification": {
            "session_sha256_verified": True,
            "selected_runs": len(run_summaries),
            "run_archive_hashes_verified": len(run_summaries),
            "run_export_manifests_verified": len(run_summaries),
            "metric_rows": len(metric_records),
            "spectral_samples": len(spectral_samples),
            "saved_fft_matches_parser": saved_fft_total,
            "frame_count_matches_summary": all(item["frames"] == item["metric_rows"] for item in run_summaries),
            "saved_sample_count_matches_summary": all(
                item["saved_samples"] == len(item["saved_sample_frame_ids"]) for item in run_summaries),
            "warnings": warnings,
            "parser_reused": True,
            "no_cpu_fft_reexecution": True,
        },
        "boundaries": [
            "长测的 3100 条指标不是 3100 份完整频谱；只保留了 14 份长测频谱。",
            "其余 5 个 run（含两个早期 1 帧失败记录）保留在源会话中；本索引只选择四个代表性 run，不删除失败记录。",
            "选中的四个 run 分开保存；不做跨 run、跨窗或不同频率网格的统计合并。",
            "重复或内容恰巧相同的帧不去重；不同 frame_id 仍是不同观测。",
            "原始采集为 LIVE；归档加载标记 REPLAY，不能当作新的板端采集。",
            "幅值未做物理标定；board_accepted 仍为 false。",
        ],
    }
    return index, metric_records


def load_spectral_sample(sample, session_zip=None):
    """Load one indexed spectral sample through the frozen adapter."""
    if not isinstance(sample, dict) or sample.get("record_type") != "spectral_sample":
        raise SessionDataError("expected a spectral_sample record")
    session_path = Path(session_zip) if session_zip else EXTENSION_ROOT / sample["source_archive"]
    if not session_path.is_file():
        raise SessionDataError("session archive not found: " + str(session_path))
    session_blob = session_path.read_bytes()
    if sha256_bytes(session_blob) != sample["source_archive_sha256"].upper():
        raise SessionDataError("session archive hash mismatch")
    with _open_zip(session_blob, str(session_path)) as session_archive:
        run_blob = _member(session_archive, sample["run_archive_member"])
        if sha256_bytes(run_blob) != sample["run_archive_sha256"].upper():
            raise SessionDataError("run archive hash mismatch")
    with _open_zip(run_blob, sample["run_archive_member"]) as run_archive:
        words_blob = _member(run_archive, sample["words_member"])
        state_blob = _member(run_archive, sample["state_member"])
    if sha256_bytes(words_blob) != sample["words_sha256"].upper():
        raise SessionDataError("words member hash mismatch")
    if sha256_bytes(state_blob) != sample["state_sha256"].upper():
        raise SessionDataError("state member hash mismatch")
    with tempfile.TemporaryDirectory(prefix="b_plus_v1_bx02_") as temp_dir:
        words_path = Path(temp_dir) / (sample["stem"] + "_words.npy")
        state_path = Path(temp_dir) / (sample["stem"] + "_state.json")
        words_path.write_bytes(words_blob)
        state_path.write_bytes(state_blob)
        frame = fft_session.load_frame(words_path, state_path)
    if frame.get("sequence") != sample["sequence"]:
        raise SessionDataError("loaded sample sequence mismatch")
    return frame


def load_metric_timeline(path):
    """Load a metric_timeline.jsonl file into a list of records."""
    records = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if raw.strip():
                try:
                    records.append(json.loads(raw))
                except ValueError as exc:
                    raise SessionDataError("invalid metric timeline line {}".format(line_number)) from exc
    return records


def render_inventory(index):
    lines = []
    source = index["source_session"]
    lines.append("# B-X02 数据清单")
    lines.append("")
    lines.append("生成日期：{}（Asia/Shanghai）。扩展：`{}`。".format(index["created"], index["extension"]))
    lines.append("")
    lines.append("## 来源")
    lines.append("")
    lines.append("- 会话：`{}`".format(source["path"]))
    lines.append("- 会话 SHA256：`{}`".format(source["sha256"]))
    lines.append("- 原始模式/上下文：`{}/{}`".format(source["mode"], source["context"]))
    lines.append("- 实例：`{}`".format(source["instance_id"]))
    lines.append("- 原始 run 总数：{}；本轮选择：{}".format(
        source["source_runs_total"], ", ".join(source["selected_runs"])))
    lines.append("- 解析器：`{}`，复用已保存 PL 复数结果，不重新做 FFT。".format(
        index["parser"]["function"]))
    lines.append("")
    lines.append("## 选中的 run")
    lines.append("")
    lines.append("| 标签 | run_id | 场景 | 窗 | 目标频率/Hz | 指标行 | 完整频谱留样 | 时长/s | 序号范围 |")
    lines.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |")
    for run in index["runs"]:
        tones = ", ".join(str(item) for item in run["expected_tones_hz"]) or "无"
        lines.append("| {} | `{}` | {} | {} | {} | {} | {} | {:.3f} | {}..{} |".format(
            run["label"], run["run_id"], run["scenario"], run["window"], tones,
            run["metric_rows"], run["saved_samples"], float(run["summary_elapsed_s"]),
            run["first_sequence"], run["last_sequence"]))
    lines.append("")
    lines.append("总计：{} 条逐帧指标，{} 份完整频谱留样。".format(
        index["verification"]["metric_rows"], index["verification"]["spectral_samples"]))
    lines.append("")
    lines.append("## 留样 frame_id")
    lines.append("")
    for run in index["runs"]:
        lines.append("- `{}`：{}".format(
            run["label"], ", ".join(str(item) for item in run["saved_sample_frame_ids"])))
    lines.append("")
    lines.append("## 两个数据集合")
    lines.append("")
    lines.append("- `spectral_samples`：`sample_index.json` 内，共 {} 条；每条含 words/state/fft 成员、SHA256、原 frame_id、原 sequence、原 elapsed_s 和加载边界。".format(
        index["verification"]["spectral_samples"]))
    lines.append("- `metric_timeline`：`metric_timeline.jsonl`，共 {} 条；每条对应 `frames.jsonl` 的一行，保留逐帧 `metrics`。".format(
        index["verification"]["metric_rows"]))
    lines.append("")
    lines.append("## 验证结果")
    lines.append("")
    verification = index["verification"]
    lines.append("- 会话 SHA256、4 个 run 归档、4 个 run export manifest 均通过。")
    lines.append("- `frames.jsonl` 行数与 summary 一致；保存留样数与 summary 一致。")
    lines.append("- 已通过 `fft_session.load_frame` 解析 {} 份完整频谱；保存的 `_fft.npy` 与解析结果一致 {} 份。".format(
        verification["spectral_samples"], verification["saved_fft_matches_parser"]))
    lines.append("- 序号连续性：{}。".format(
        "全部选中 run 连续" if not verification["warnings"] else "存在缺口，见 `sample_index.json`"))
    lines.append("")
    lines.append("## 数据边界")
    lines.append("")
    for item in index["boundaries"]:
        lines.append("- " + item)
    lines.append("")
    lines.append("## 下一步")
    lines.append("")
    lines.append("B-X03 可按 run 和 `saved_sample_frame_ids` 顺序播放留样；没有完整频谱的 frame 应显示“该区间未留存完整频谱”，不能从指标行插造频谱。")
    lines.append("")
    return "\n".join(lines)


def write_index(session_zip=DEFAULT_SESSION, out_dir=None, verify_spectra=True, expected_sha256=None):
    """Build and write the B-X02 index files."""
    index, metric_records = build_index(session_zip, verify_spectra, expected_sha256)
    if out_dir is None:
        import export_results
        out_dir = export_results.prepare_report_dir(DEFAULT_OUTPUT_NAME)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metric_blob = "".join(
        json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        for record in metric_records
    ).encode("utf-8")
    metric_path = out_dir / "metric_timeline.jsonl"
    metric_path.write_bytes(metric_blob)
    index["metric_timeline"]["sha256"] = sha256_bytes(metric_blob)

    sample_blob = (json.dumps(index, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    sample_path = out_dir / "sample_index.json"
    sample_path.write_bytes(sample_blob)

    inventory_blob = render_inventory(index).encode("utf-8")
    inventory_path = out_dir / "data_inventory.md"
    inventory_path.write_bytes(inventory_blob)

    outputs = {}
    for path, blob in ((sample_path, sample_blob), (metric_path, metric_blob), (inventory_path, inventory_blob)):
        outputs[path.name] = {"bytes": len(blob), "sha256": sha256_bytes(blob)}
    manifest = {
        "schema_version": 1,
        "step": STEP,
        "extension": "b_plus_v1",
        "created": CREATED_DATE,
        "source_session": index["source_session"],
        "outputs": outputs,
    }
    (out_dir / "index_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=str(DEFAULT_SESSION),
                        help="session ZIP; default is the read-only export02 copy")
    parser.add_argument("--out", default=DEFAULT_OUTPUT_NAME,
                        help="output directory name relative to reports/")
    parser.add_argument("--no-spectrum-check", action="store_true",
                        help="skip parsing saved spectra (index metadata only)")
    args = parser.parse_args(argv)
    import export_results
    out_dir = export_results.prepare_report_dir(args.out)
    index = write_index(args.session, out_dir, verify_spectra=not args.no_spectrum_check)
    summary = {
        "step": STEP,
        "ok": True,
        "outputs": str(out_dir),
        "runs": len(index["runs"]),
        "metric_rows": index["verification"]["metric_rows"],
        "spectral_samples": index["verification"]["spectral_samples"],
        "saved_fft_matches_parser": index["verification"]["saved_fft_matches_parser"],
        "warnings": len(index["verification"]["warnings"]),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
