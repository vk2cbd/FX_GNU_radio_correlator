#!/usr/bin/env python3
"""Recover a Stage 10 UVFITS file from an unfinished SQLite journal."""

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRC_DIR = ROOT / "grc"
if str(GRC_DIR) not in sys.path:
    sys.path.insert(0, str(GRC_DIR))

from fx_interferometer_v1_stage10_uvfits_writer import (  # noqa: E402
    finalize_journal,
    load_journal,
    pyuvdata_version,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", help="Path to the .stage10.sqlite journal")
    parser.add_argument("--uvfits", help="Optional recovered UVFITS output path")
    parser.add_argument("--diagnostics-csv", help="Optional recovered diagnostics CSV output path")
    args = parser.parse_args(argv)

    journal = Path(args.journal).expanduser().resolve()
    if not journal.exists():
        parser.error(f"journal not found: {journal}")

    config, outputs, records = load_journal(journal)
    print(f"Journal: {journal}")
    print(f"Observation: {config.observation_name}")
    print(f"Source: {config.source_name()}")
    print(f"Records: {len(records)}")
    print(f"pyuvdata: {pyuvdata_version() or 'not installed'}")
    if len(records) == 0:
        raise SystemExit("No records found; nothing to recover.")

    uvfits_path = Path(args.uvfits).expanduser().resolve() if args.uvfits else Path(outputs["uvfits"])
    diagnostics_path = (
        Path(args.diagnostics_csv).expanduser().resolve()
        if args.diagnostics_csv
        else Path(outputs["diagnostics_csv"])
    )
    uvfits_path, diagnostics_path, uv = finalize_journal(journal, uvfits_path, diagnostics_path)
    print(f"Recovered UVFITS: {uvfits_path}")
    print(f"Diagnostics CSV: {diagnostics_path}")
    print(
        "Summary: "
        f"Nblts={uv.Nblts}, Nfreqs={uv.Nfreqs}, Npols={uv.Npols}, "
        f"freq_hz={uv.freq_array[0]:.6f}, channel_width_hz={uv.channel_width[0]:.6f}"
    )


if __name__ == "__main__":
    main()
