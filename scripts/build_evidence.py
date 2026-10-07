"""Build app/evidence_uci.json (the app's read-only 'Results on real shop data' page) from results already made.

    python scripts/build_evidence.py

Needs the local UCI cache and saved outputs in data/ (gitignored). Writes aggregates only: no rows, no customer ids.
- 3-window backtest and calibration: recomputed from data/invoices.csv with the same code as table B.
- Holdout: from data/holdout_predictions.csv (sha256 checked; saved by the frozen reproduction), with the bootstrap
  intervals of scripts/holdout_bootstrap.py. No re-fit, no re-run.
- Mapping test: parsed from data/mapping_eval_output.txt. Draft runs: from data/draft_eval*.json and run 2's output.
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from sklearn.metrics import brier_score_loss

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from app.audit import run_audit, tier_track_record, window_metrics  # noqa: E402
from app.engine import backtest, calibration, ece  # noqa: E402
from holdout_bootstrap import PREDS, intervals  # noqa: E402

DATA = ROOT / 'data'
OUT = ROOT / 'app' / 'evidence_uci.json'
r3 = lambda x: round(float(x), 3)  # noqa: E731


def backtest_all():
    inv = pd.read_csv(DATA / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
    a = run_audit(inv)
    runs = {r['origin']: r for r in backtest(inv)}
    rows = []
    for w in a['windows'].itertuples():
        r = runs[w.origin]
        rows.append({'window': w.origin.strftime('%Y-%m-%d'), 'customers': int(w.n), 'base_rate': r3(w.base_rate),
                     'auc_model': r3(w.auc_model), 'auc_recency': r3(w.auc_recency),
                     'top20_model': r3(w.top20_model), 'top20_recency': r3(w.top20_recency),
                     'ece': r3(ece(calibration(r['y'], r['p']))), 'brier': r3(brier_score_loss(r['y'], r['p']))})
    tiers = {k: [{'tier': t, 'pooled': r3(x['pooled']), 'min': r3(x['min']), 'max': r3(x['max'])}
                 for t, x in tier_track_record(a, k).iterrows()] for k in ('model', 'recency')}
    return rows, tiers, int(inv['customer_id'].nunique()), len(inv)


def holdout():
    p = pd.read_csv(PREDS)
    ci = {r['window']: r for r in intervals()}          # checks the file's sha256
    rows = []
    for window, g in p.groupby('window', sort=False):
        y, sm, sr = g['label'].values, g['model_score'].values, g['recency_score'].values
        m = window_metrics(y, sm, sr)
        c = ci[window]
        rows.append({'window': window, 'customers': int(m['n']), 'base_rate': r3(m['base_rate']),
                     'auc_model': r3(m['auc_model']), 'auc_recency': r3(m['auc_recency']),
                     'top20_model': r3(m['top20_model']), 'top20_recency': r3(m['top20_recency']),
                     'ece': r3(ece(calibration(y, sm))), 'top20_customers': c['top20_n'], 'diff': r3(c['diff']),
                     'ci_low': r3(c['ci_low']), 'ci_high': r3(c['ci_high']), 'verdict': c['verdict']})
    return rows


def mapping():
    text = (DATA / 'mapping_eval_output.txt').read_text(encoding='utf-8')
    rows = []
    for block in text.split('===== ')[1:]:
        name = block.split(' ', 1)[0]
        rules = re.search(r'^rules: (.*)$', block, re.M)[1]
        llm = re.findall(r'^LLM run \d+: (\w+)', block, re.M)
        identical = 'identical: True' in block
        rows.append({'file': name, 'rules': rules.split(' [')[0],
                     'llm': f"{llm.count('correct')} of {len(llm)} runs correct"
                            + (' (all identical, 1 effective run)' if identical else '')})
    return rows


def drafts():
    run1 = json.loads((DATA / 'draft_eval.json').read_text(encoding='utf-8'))
    s1 = Counter(r['source'] for r in run1)
    out2 = (DATA / 'draft_eval_run2_output.txt').read_text(encoding='utf-8')
    val = lambda label: int(re.search(rf'^{re.escape(label)}\s+\S+\s+(\d+)\s*$', out2, re.M)[1])  # noqa: E731
    rows = [{'run': 'Run 1 (2026-10-05)', 'verifier': 'v1: single banned words', 'customers': len(run1),
             'first_try': s1['llm'], 'after_repair': s1['llm_repaired'], 'rejected': s1['template'],
             'good': None, 'note': 'all 22 rejections were false alarms ("feel free", the verb "offer")'},
            {'run': 'Run 2 (2026-10-06)', 'verifier': 'v2: phrases, exact day counts', 'customers': 50,
             'first_try': val('passed first try'), 'after_repair': val('passed after repair'),
             'rejected': val('rejected'), 'good': val('good (verified and specific)'),
             'note': 'drafts still contained day counts; hand-check found tone problems'}]
    run3 = json.loads((DATA / 'draft_eval_run3.json').read_text(encoding='utf-8'))
    for intent in ('due', 'overdue', 'lapsed'):
        g = [r for r in run3 if r['intent'] == intent]
        rows.append({'run': f'Run 3 (2026-10-06), {intent}', 'verifier': 'v3: intent by code, no durations',
                     'customers': len(g), 'first_try': sum(r['source'] == 'llm' for r in g),
                     'after_repair': sum(r['source'] == 'llm_repaired' for r in g),
                     'rejected': sum(r['source'] == 'template' for r in g),
                     'good': sum(r['source'] != 'template' and r['specific'] for r in g),
                     'note': 'correct, not judged for tone; owner rating pending'})
    return rows


def main():
    rows, tiers, n_customers, n_invoices = backtest_all()
    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    evidence = {
        'dataset': {'name': 'Online Retail II', 'source': 'UCI Machine Learning Repository',
                    'url': 'https://archive.ics.uci.edu/dataset/502/online+retail+ii', 'license': 'CC BY 4.0',
                    'description': 'UK online gift-ware wholesaler, Dec 2009 to Dec 2011. Raw data is not included.',
                    'customers': n_customers, 'invoices_after_cleaning': n_invoices},
        'built_from_commit': commit,
        'backtest_all_customers': rows,
        'tiers_all_customers': tiers,
        'holdout': holdout(),
        'mapping': mapping(),
        'drafts': drafts(),
        'reproduce': ['Download the UCI file into data/ (see data/README.md)',
                      'python scripts/calibration.py        # cleans UCI into data/invoices.csv; calibration',
                      'python scripts/audit_uci.py          # 3-window backtest and tiers',
                      'python scripts/holdout_bootstrap.py  # holdout intervals (needs the saved predictions)',
                      'python scripts/build_evidence.py     # rebuilds this page'],
    }
    OUT.write_text(json.dumps(evidence, indent=1), encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)')
    print(json.dumps({k: evidence[k] for k in ('backtest_all_customers', 'holdout')}, indent=1))


if __name__ == '__main__':
    main()
