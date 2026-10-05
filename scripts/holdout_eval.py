"""Locked holdout on UCI. Run from the repo root after scripts/calibration.py has cached data/invoices.csv.

    python scripts/holdout_eval.py --dev       # all-customer table vs development-only (80%) table, any number of times
    python scripts/holdout_eval.py --holdout   # ONCE: fit on development customers, measure the 20% holdout

The holdout run writes data/holdout_used.txt and refuses to run again, so it cannot be peeked at and re-tuned.
"""
import argparse
import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.audit import HIGH, MEDIUM, TIERS, run_audit, tier_track_record, window_metrics  # noqa: E402
from app.engine import (HORIZON, backtest, calibration, default_origins, ece, features, fit,  # noqa: E402
                        predict, split_holdout)

DATA = ROOT / 'data'
MARKER = DATA / 'holdout_used.txt'
pd.set_option('display.float_format', '{:.3f}'.format)
pd.set_option('display.width', 200)


def windows_table(inv):
    a = run_audit(inv)
    w = a['windows'].copy()
    w['ece'] = [ece(calibration(r['y'], r['p'])) for r in backtest(inv)]
    return a, w


def dev_report(inv):
    dev, hold = split_holdout(inv)
    print(f"customers: all {inv['customer_id'].nunique()} | development {dev['customer_id'].nunique()} | "
          f"holdout {hold['customer_id'].nunique()} (holdout not used here)")
    for name, data in (('ALL CUSTOMERS (old table B)', inv), ('DEVELOPMENT ONLY (80%)', dev)):
        a, w = windows_table(data)
        print(f'\n== {name} | status {a["status"]} | ranker {a["ranker"]} ({a["ranker_reason"]})')
        print(w.to_string(index=False))
        print(tier_track_record(a, a['ranker']).to_string())


def cutoffs(scores):
    """Score thresholds for high / medium from the development ranking (top 20% / top 50%)."""
    s = np.sort(np.asarray(scores))[::-1]
    hi = max(1, int(len(s) * HIGH))
    return s[hi - 1], s[max(hi, int(len(s) * MEDIUM)) - 1]


def apply_cutoffs(scores, cut):
    s = np.asarray(scores)
    return np.where(s >= cut[0], 'high', np.where(s >= cut[1], 'medium', 'low'))


def holdout_report(inv):
    if MARKER.exists():
        sys.exit(f'Refusing: the holdout was already used ({MARKER.read_text().strip()}). It is run once.')
    dev, hold = split_holdout(inv)
    origins = default_origins(inv)  # the same 3 origins as table B
    rows, tiers = [], []
    for o in origins:
        train = pd.concat([features(dev, o - pd.Timedelta(days=HORIZON * i)) for i in (1, 2, 3)])
        fitted = fit(train)                                  # development customers only
        f_dev, f_hold = features(dev, o), features(hold, o)
        p_dev, p_hold = predict(fitted, f_dev), predict(fitted, f_hold)
        y = f_hold['y'].values
        rows.append({'origin': o, **window_metrics(y, p_hold, -f_hold['recency'].values),
                     'ece': ece(calibration(y, p_hold))})
        for ranker, s_dev, s_hold in (('model', p_dev, p_hold),
                                      ('recency', -f_dev['recency'].values, -f_hold['recency'].values)):
            t = apply_cutoffs(s_hold, cutoffs(s_dev))       # cutoffs from development scores only
            for k in TIERS:
                tiers.append({'origin': o, 'ranker': ranker, 'tier': k, 'n': int((t == k).sum()),
                              'hits': int(y[t == k].sum())})
    MARKER.write_text(f'holdout run at {datetime.datetime.now().isoformat(timespec="seconds")}\n')
    w = pd.DataFrame(rows)
    print(f"== HOLDOUT (20%, {hold['customer_id'].nunique()} customers): model fitted on development customers only")
    print(w.to_string(index=False))
    t = pd.DataFrame(tiers)
    for ranker in ('model', 'recency'):
        sub = t[t['ranker'] == ranker].assign(rate=lambda d: d['hits'] / d['n'])
        g = sub.groupby('tier')
        rec = pd.DataFrame({'n': g['n'].sum(), 'min': g['rate'].min(), 'max': g['rate'].max(),
                            'pooled': g['hits'].sum() / g['n'].sum()}).loc[list(TIERS)]
        print(f'\ntiers on holdout, ranker={ranker} (cutoffs from development scores):')
        print(rec.to_string())
    model_wins = bool((w['top20_model'] > w['top20_recency']).all())
    print(f"\nrule 3 on holdout: model beats recency on top-20% hit in every window: {model_wins}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dev', action='store_true')
    g.add_argument('--holdout', action='store_true')
    args = ap.parse_args()
    inv = pd.read_csv(DATA / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
    dev_report(inv) if args.dev else holdout_report(inv)


if __name__ == '__main__':
    main()
