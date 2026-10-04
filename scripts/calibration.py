"""H2 calibration check: is a "70%" prediction right about 70% of the time?

Run from the repo root: python scripts/calibration.py
Downloads UCI Online Retail II into data/ if missing (CC BY 4.0, not committed).
"""
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import backtest, calibration, clean, ece, load_uci, top_k_hit  # noqa: E402

DATA = ROOT / 'data'
XLSX = DATA / 'online_retail_II.xlsx'
CACHE = DATA / 'invoices.csv'
URL = 'https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip'

# Fixed before the first run. Not to be changed after seeing results.
MAX_ECE = 0.05
MAX_BIN_GAP, MIN_BIN_N = 0.10, 100


def invoices():
    if CACHE.exists():
        return pd.read_csv(CACHE, dtype={'invoice_id': str}, parse_dates=['date'])
    if not XLSX.exists():
        print('downloading', URL, flush=True)
        zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL).read())).extractall(DATA)
    inv = clean(load_uci(XLSX))
    inv.to_csv(CACHE, index=False)
    return inv


def bad_bins(t):
    return t[(t['n'] >= MIN_BIN_N) & (t['gap'].abs() > MAX_BIN_GAP)]


def main():
    inv = invoices()
    print(f"invoices {len(inv)}, customers {inv['customer_id'].nunique()}, last date {inv['date'].max().date()}\n")
    pd.set_option('display.float_format', '{:.3f}'.format)
    runs = backtest(inv)
    for r in runs:
        y, p, s = r['y'], r['p'], r['s_recency']
        t = calibration(y, p)
        print(f"origin {r['origin'].date()}: n={len(y)} base_rate={y.mean():.3f} mean_pred={p.mean():.3f} "
              f"AUC model={roc_auc_score(y, p):.3f} recency={roc_auc_score(y, s):.3f} "
              f"top20% model={top_k_hit(y, p):.3f} recency={top_k_hit(y, s):.3f} "
              f"Brier={brier_score_loss(y, p):.3f} ECE={ece(t):.3f} bad_bins={len(bad_bins(t))}")
        print(t.to_string(), '\n')
    y = np.concatenate([r['y'] for r in runs])
    p = np.concatenate([r['p'] for r in runs])
    t = calibration(y, p)
    print(f"POOLED: n={len(y)} base_rate={y.mean():.3f} mean_pred={p.mean():.3f} "
          f"Brier={brier_score_loss(y, p):.3f} ECE={ece(t):.3f}")
    print(t.to_string())
    seventy = t.loc[t.index.isin(['0.6-0.7', '0.7-0.8'])]
    n70 = seventy['n'].sum()
    print(f"\n'70%' band (0.6-0.8): n={n70} mean_pred={(seventy['n'] * seventy['pred']).sum() / n70:.3f} "
          f"observed={(seventy['n'] * seventy['obs']).sum() / n70:.3f}")
    bad = ece(t) > MAX_ECE or len(bad_bins(t)) > 0
    print(f"\nVERDICT (pooled ECE > {MAX_ECE} or any bin n>={MIN_BIN_N} off by > {MAX_BIN_GAP:.0%}): "
          f"{'BAD' if bad else 'OK'}")


if __name__ == '__main__':
    main()
