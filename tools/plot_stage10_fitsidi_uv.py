#!/usr/bin/env python3
import argparse

import numpy as np
from astropy.io import fits


C_M_S = 299792458.0


def read_uv_lambda(path):
    u_vals = []
    v_vals = []
    with fits.open(path, checksum=False, memmap=False) as hdul:
        ref_freq = float(hdul["FREQUENCY"].header["REF_FREQ"])
        wavelength = C_M_S / ref_freq
        for hdu in hdul:
            if hdu.name != "UV_DATA" or hdu.data is None:
                continue
            u_project = -np.asarray(hdu.data["UU"], dtype=np.float64) * C_M_S
            v_project = -np.asarray(hdu.data["VV"], dtype=np.float64) * C_M_S
            u_vals.extend(u_project / wavelength)
            v_vals.extend(v_project / wavelength)
    return np.asarray(u_vals), np.asarray(v_vals)


def main():
    parser = argparse.ArgumentParser(description="Plot Stage 10 FITS-IDI U/V coverage.")
    parser.add_argument("path")
    parser.add_argument("--output", help="Optional PNG output path. If omitted, show an interactive plot.")
    args = parser.parse_args()
    u_lam, v_lam = read_uv_lambda(args.path)
    if len(u_lam) == 0:
        raise SystemExit("No UV_DATA rows found.")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot(u_lam, v_lam, ".", label="B01")
    ax.plot(-u_lam, -v_lam, ".", alpha=0.35, label="conjugate display only")
    ax.set_xlabel("U (wavelengths)")
    ax.set_ylabel("V (wavelengths)")
    ax.set_title("Stage 10 FITS-IDI U/V Coverage")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    if args.output:
        fig.savefig(args.output, dpi=150)
    else:
        plt.show()


if __name__ == "__main__":
    main()
