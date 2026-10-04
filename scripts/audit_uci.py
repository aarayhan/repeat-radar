"""H3 audit on UCI Online Retail II. Run from the repo root after scripts/calibration.py has cached data/invoices.csv."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.audit import recommend, tier_track_record  # noqa: E402

inv = pd.read_csv(ROOT / 'data' / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
pd.set_option('display.float_format', '{:.3f}'.format)
pd.set_option('display.width', 200)
r = recommend(inv)
a = r['audit']
print('status:', a['status'], '| skipped windows:', a['skipped'] or 'none')
print(a['windows'].to_string(index=False))
print(f"\nranker: {a['ranker']} ({a['ranker_reason']})")
for ranker in ('model', 'recency'):
    rec = tier_track_record(a, ranker)
    print(f"\ntier track record, ranker={ranker} (base rate {rec.attrs['base_rate'][0]:.3f}-{rec.attrs['base_rate'][1]:.3f}):")
    print(rec.to_string())
print(f"\ncurrent list ({r['ranker']}): {len(r['scored'])} scored,", r['scored']['tier'].value_counts().to_dict())
print(f"not scored: {len(r['not_scored'])} ({r['not_scored']['reason'].iloc[0]})")
