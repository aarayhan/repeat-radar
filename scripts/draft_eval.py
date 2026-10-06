"""Evaluate verified LLM drafts on 50 UCI development customers (seed 42). Holdout customers are never used.

Run from the repo root (needs data/invoices.csv, data/online_retail_II.xlsx and an LLM key in .env):
    python scripts/draft_eval.py
Full drafts (with customer ids) go to data/draft_eval.json, which is gitignored. Printed examples use #1, #2, #3.
"""
import json
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.audit import run_audit, score_now, tier_track_record  # noqa: E402
from app.drafts import draft_facts, llm_draft, usual_products  # noqa: E402
from app.engine import load_uci, split_holdout  # noqa: E402
from app.llm import client  # noqa: E402

DATA = ROOT / 'data'
LINES = DATA / 'uci_lines.pkl'
N, SEED = 50, 42


def product_lines():
    """UCI order lines with product names (cached in data/, gitignored)."""
    if not LINES.exists():
        raw = load_uci(DATA / 'online_retail_II.xlsx')
        raw = raw[(raw['Quantity'] > 0) & (raw['Price'] > 0) & raw['Customer ID'].notna()]
        pd.DataFrame({'customer_id': raw['Customer ID'], 'invoice_id': raw['Invoice'].astype(str),
                      'product': raw['Description'].astype(str).str.strip()}).to_pickle(LINES)
    return pd.read_pickle(LINES)


def kind(problem):
    return problem.split(':')[0]


def main():
    inv = pd.read_csv(DATA / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
    dev, _ = split_holdout(inv)
    lines = product_lines()
    lines = lines[lines['customer_id'].isin(set(dev['customer_id']))]   # development customers only
    catalogue = sorted(set(lines['product']))
    a = run_audit(dev)
    rec = tier_track_record(a, a['ranker'])
    now = score_now(dev, a['ranker'])['scored']
    picked = random.Random(SEED).sample(sorted(now['customer_id']), N)
    llm = client()
    print(f"model {llm[1]} | ranker {a['ranker']} | {N} development customers, seed {SEED} | "
          f"catalogue {len(catalogue)} products")

    results = []
    for i, c in enumerate(picked, 1):
        row = now[now['customer_id'] == c].iloc[0]
        facts = draft_facts(dev[dev['customer_id'] == c], usual_products(lines[lines['customer_id'] == c]),
                            c, row['tier'], rec.loc[row['tier'], 'pooled'], row['recency'])
        r = llm_draft(facts, llm, catalogue)
        results.append({'customer_id': facts['customer_id'], 'facts': facts, **r})
        print(f"{i:2d}. {r['source']:13s} {r['seconds']:5.1f}s", flush=True)
    (DATA / 'draft_eval.json').write_text(json.dumps(results, indent=1, default=str), encoding='utf-8')

    src = Counter(r['source'] for r in results)
    api = sum(any(p and 'API error' in p[0] for _, p in r['attempts']) for r in results)
    secs = [r['seconds'] for r in results]
    print(f"\npassed first try: {src['llm']} of {N} | passed after repair: {src['llm_repaired']} of {N} | "
          f"rejected (template shown): {src['template'] - api} of {N} | API errors (template shown): {api}")
    print(f"JSON failures: {sum(r['json_failures'] for r in results)} replies in "
          f"{sum(r['json_failures'] > 0 for r in results)} drafts | LLM calls: {sum(len(r['attempts']) for r in results)}")
    print(f"seconds per draft: mean {statistics.mean(secs):.1f}, median {statistics.median(secs):.1f}, "
          f"max {max(secs):.1f}")
    first = Counter(kind(p) for r in results for p in (r['attempts'][0][1] if r['attempts'] else []))
    print('verifier reasons on first attempts:', dict(first))

    worst = sorted([r for r in results if r['source'] == 'template' and r['attempts']],
                   key=lambda r: -len(r['attempts'][-1][1]))[:3]
    for k, r in enumerate(worst, 1):
        print(f'\n--- worst #{k} (customer id redacted as #{k}) ---')
        for j, (raw, problems) in enumerate(r['attempts'], 1):
            print(f"attempt {j}: {re.sub(re.escape(r['customer_id']), f'#{k}', raw or '')!r}")
            print(f'  verifier: {problems}')


if __name__ == '__main__':
    main()
