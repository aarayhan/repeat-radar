"""Tier by message intent on the UCI development customers (holdout untouched).

    python scripts/tier_intent_crosstab.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.audit import run_audit, score_now  # noqa: E402
from app.drafts import INTENTS, intents  # noqa: E402
from app.engine import split_holdout  # noqa: E402

inv = pd.read_csv(ROOT / 'data' / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
dev, _ = split_holdout(inv)
a = run_audit(dev)
s = score_now(dev, a['ranker'])['scored']
s = s.assign(intent=intents(dev, s))
t = pd.crosstab(pd.Categorical(s['tier'], ['high', 'medium', 'low']), pd.Categorical(s['intent'], INTENTS),
                rownames=['tier'], colnames=['intent'], margins=True)
print(f"development customers scored: {len(s)} | ranker: {a['ranker']}")
print(t.to_string())
