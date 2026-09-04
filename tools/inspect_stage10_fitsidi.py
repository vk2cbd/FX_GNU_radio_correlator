#!/usr/bin/env python3
import argparse
import os

import numpy as np
from astropy.io import fits

from stage10_fitsidi_writer import validate_fitsidi_file


C_M_S = 299792458.0


def inspect(path):
    with fits.open(path, checksum=False) as hdul:
        for hdu in hdul:
            hdu.verify("exception")
        print(f"File: {path}")
        print("HDUs:")
        for idx, hdu in enumerate(hdul):
            rows = 0 if hdu.data is None else len(hdu.data)
            print(f"  {idx}: {hdu.name} rows={rows}")
        uv_hdus = [hdu for hdu in hdul if hdu.name == "UV_DATA"]
        total = sum(len(hdu.data) for hdu in uv_hdus if hdu.data is not None)
        print(f"UV_DATA chunks: {len(uv_hdus)}")
        print(f"Visibility rows: {total}")
        if uv_hdus and total:
            first = uv_hdus[0].data[0]
            last = uv_hdus[-1].data[-1]
            first_jd = float(first["DATE"] + first["TIME"])
            last_jd = float(last["DATE"] + last["TIME"])
            print(f"First JD: {first_jd:.12f}")
            print(f"Last JD: {last_jd:.12f}")
            print(
                "First FITS UU/VV/WW seconds: "
                f"{float(first['UU']):.12e}, {float(first['VV']):.12e}, {float(first['WW']):.12e}"
            )
            print(
                "Last FITS UU/VV/WW seconds: "
                f"{float(last['UU']):.12e}, {float(last['VV']):.12e}, {float(last['WW']):.12e}"
            )
            print(
                "First project u/v/w metres: "
                f"{-float(first['UU']) * C_M_S:.6f}, {-float(first['VV']) * C_M_S:.6f}, {-float(first['WW']) * C_M_S:.6f}"
            )
            print(
                "Last project u/v/w metres: "
                f"{-float(last['UU']) * C_M_S:.6f}, {-float(last['VV']) * C_M_S:.6f}, {-float(last['WW']) * C_M_S:.6f}"
            )
            first_flux = np.asarray(first["FLUX"], dtype=np.float32).reshape(-1)
            last_flux = np.asarray(last["FLUX"], dtype=np.float32).reshape(-1)
            print(f"First visibility: {first_flux[0]:.9g} + j{first_flux[1]:.9g}, weight={first_flux[2]:.3g}")
            print(f"Last visibility: {last_flux[0]:.9g} + j{last_flux[1]:.9g}, weight={last_flux[2]:.3g}")
        if "FREQUENCY" in hdul:
            freq = hdul["FREQUENCY"]
            print(f"REF_FREQ: {freq.header['REF_FREQ']:.9g} Hz")
            print(f"CHAN_BW: {freq.header['CHAN_BW']:.9g} Hz")


def finalize(path):
    if not path.endswith(".partial.fitsidi"):
        raise ValueError("--finalize expects a *.partial.fitsidi file")
    inspect(path)
    validate_fitsidi_file(path)
    final_path = path.replace(".partial.fitsidi", ".fitsidi")
    if os.path.exists(final_path):
        raise FileExistsError(final_path)
    os.replace(path, final_path)
    print(f"Finalized: {final_path}")


def main():
    parser = argparse.ArgumentParser(description="Inspect Stage 10 FITS-IDI files.")
    parser.add_argument("path")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        finalize(args.path)
    else:
        inspect(args.path)


if __name__ == "__main__":
    main()
