"""Reproduce the single holdout run of 2026-10-05 with FROZEN code, only to save per-customer predictions.

    python scripts/holdout_reproduce.py --frozen <git worktree checked out at 04ebc87>

- Imports app/ and scripts/holdout_eval.py from the frozen worktree only (checked below), never from this branch.
- Never reads, writes, moves or bypasses data/holdout_used.txt.
- Prints the same report as the original run and compares it line by line with data/holdout_result.txt.
- Writes data/holdout_predictions.csv ONLY if every line matches exactly; otherwise writes nothing.
- Logs the reproduction to data/holdout_reproduction_log.txt.
"""
import argparse
import contextlib
import datetime
import hashlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frozen', required=True)
    frozen = Path(ap.parse_args().frozen).resolve()
    sys.path[:0] = [str(frozen), str(frozen / 'scripts')]
    import numpy as np
    import pandas as pd
    import sklearn
    from app import audit as frozen_audit, engine as frozen_engine
    import holdout_eval as frozen_eval
    for m in (frozen_audit, frozen_engine, frozen_eval):
        assert Path(m.__file__).resolve().is_relative_to(frozen), f'{m.__name__} not imported from frozen code'
    from app.audit import TIERS, window_metrics
    from app.engine import HORIZON, calibration, default_origins, ece, features, fit, predict, split_holdout
    from holdout_eval import apply_cutoffs, cutoffs
    print(f'frozen code: {frozen} | python {sys.version.split()[0]} | numpy {np.__version__} | '
          f'pandas {pd.__version__} | scikit-learn {sklearn.__version__}')

    inv = pd.read_csv(DATA / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
    dev, hold = split_holdout(inv)
    rows, tiers, preds = [], [], []
    for o in default_origins(inv):          # body of frozen holdout_report, without the marker, plus saving rows
        train = pd.concat([features(dev, o - pd.Timedelta(days=HORIZON * i)) for i in (1, 2, 3)])
        fitted = fit(train)
        f_dev, f_hold = features(dev, o), features(hold, o)
        p_dev, p_hold = predict(fitted, f_dev), predict(fitted, f_hold)
        y = f_hold['y'].values
        rows.append({'origin': o, **window_metrics(y, p_hold, -f_hold['recency'].values),
                     'ece': ece(calibration(y, p_hold))})
        for ranker, s_dev, s_hold in (('model', p_dev, p_hold),
                                      ('recency', -f_dev['recency'].values, -f_hold['recency'].values)):
            t = apply_cutoffs(s_hold, cutoffs(s_dev))
            for k in TIERS:
                tiers.append({'origin': o, 'ranker': ranker, 'tier': k, 'n': int((t == k).sum()),
                              'hits': int(y[t == k].sum())})
        preds.append(pd.DataFrame({'customer_id': f_hold.index, 'window': o.strftime('%Y-%m-%d'),
                                   'model_score': p_hold, 'recency_score': -f_hold['recency'].values, 'label': y}))

    out = io.StringIO()
    with contextlib.redirect_stdout(out):   # same print statements as the frozen holdout_report
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

    old = [line.rstrip('\r') for line in (DATA / 'holdout_result.txt').read_text(encoding='utf-8').splitlines()]
    new = out.getvalue().splitlines()
    width = max(map(len, old + new))
    print(f"\n{'ORIGINAL RUN (data/holdout_result.txt)':{width}s} | REPRODUCTION")
    for i in range(max(len(old), len(new))):
        a, b = (old[i] if i < len(old) else '<missing>'), (new[i] if i < len(new) else '<missing>')
        print(f"{a:{width}s} {'|' if a == b else 'X'} {b}")
    match = old == new
    log = DATA / 'holdout_reproduction_log.txt'
    stamp = datetime.datetime.now().isoformat(timespec='seconds')
    if not match:
        log.open('a').write(f'{stamp} reproduction with frozen code {frozen}: MISMATCH, predictions discarded\n')
        print('\nRESULT: MISMATCH. Predictions discarded, nothing written. Section C not done.')
        return
    path = DATA / 'holdout_predictions.csv'
    pd.concat(preds, ignore_index=True).to_csv(path, index=False)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    log.open('a').write(f'{stamp} reproduction with frozen code {frozen}: exact match; '
                        f'wrote {path.name} sha256 {sha}\n')
    print(f'\nRESULT: EXACT MATCH on all {len(old)} lines. Wrote {path.name} ({sum(map(len, preds))} rows), '
          f'sha256 {sha}')


if __name__ == '__main__':
    main()
