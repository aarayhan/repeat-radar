"""Paired bootstrap intervals for the holdout top-20% hit-rate difference (model minus recency rule).

Uses only data/holdout_predictions.csv (saved by scripts/holdout_reproduce.py); no re-fit, no re-run.
Per window: 1000 resamples of holdout customers with replacement, seed 42. In each resample the top-20% cut
is recomputed for the model and for recency, then the difference of their hit rates.
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import top_k_hit  # noqa: E402

PREDS = ROOT / 'data' / 'holdout_predictions.csv'
SHA = 'c6f733af5d13fb87e933290813560db1934191e5b41b9418a32029d9cb0e325c'   # docs/H2_REPORT.md section 7
B, SEED = 1000, 42


def main():
    print(f'{B} paired resamples per window, seed {SEED}')
    print(f"{'window':10s} {'n':>4s} {'top20 n':>7s} {'model':>6s} {'recency':>7s} {'diff':>6s} {'2.5%':>7s} {'97.5%':>7s}  verdict")
    for r in intervals():
        print(f"{r['window']:10s} {r['n']:4d} {r['top20_n']:7d} {r['top20_model']:6.3f} {r['top20_recency']:7.3f} "
              f"{r['diff']:6.3f} {r['ci_low']:7.3f} {r['ci_high']:7.3f}  {r['verdict']}")


def intervals():
    """One dict per window: n, top-20% size, hit rates, difference and its 95% bootstrap interval, verdict."""
    assert hashlib.sha256(PREDS.read_bytes()).hexdigest() == SHA, 'predictions file changed'
    p = pd.read_csv(PREDS)
    rng = np.random.default_rng(SEED)
    out = []
    for window, g in p.groupby('window', sort=False):
        y, sm, sr = g['label'].values, g['model_score'].values, g['recency_score'].values
        n, k = len(y), max(1, int(len(y) * 0.2))
        hm, hr = top_k_hit(y, sm), top_k_hit(y, sr)
        diffs = np.empty(B)
        for b in range(B):
            i = rng.integers(0, n, n)
            diffs[b] = top_k_hit(y[i], sm[i]) - top_k_hit(y[i], sr[i])
        lo, hi = np.percentile(diffs, [2.5, 97.5])
        verdict = 'not conclusive (interval includes 0)' if lo <= 0 <= hi else 'model better (interval above 0)' \
            if lo > 0 else 'recency better (interval below 0)'
        out.append({'window': window, 'n': n, 'top20_n': k, 'top20_model': float(hm), 'top20_recency': float(hr),
                    'diff': float(hm - hr), 'ci_low': float(lo), 'ci_high': float(hi), 'verdict': verdict})
    return out


if __name__ == '__main__':
    main()
