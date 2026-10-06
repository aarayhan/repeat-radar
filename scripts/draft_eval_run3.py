"""Draft evaluation run 3: intent chosen by code, no durations in the message, non-product lines out of the facts.

    python scripts/draft_eval_run3.py

- Contact list: development customers only (holdout untouched), counted per intent.
- Sample: 50 customers with intent due, overdue or lapsed, seed 2027, excluding every customer from runs 1 and 2.
- Ids in docs/ are hashed with the same salt as run 2 (data/draft_id_salt.txt, gitignored); key in data/.
- Log: docs/drafts_run3.jsonl, one line per LLM attempt (hashed id, facts without the id, raw draft, attempt,
  temperature, verdict, reject reasons).
"""
import json
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from app.audit import run_audit, score_now, tier_track_record  # noqa: E402
from app.drafts import (NON_PRODUCT_CODES, _parse, draft_facts, intents, is_non_product, is_specific,  # noqa: E402
                        llm_draft, usual_products)
from app.engine import split_holdout  # noqa: E402
from app.llm import client  # noqa: E402
from draft_eval import product_lines  # noqa: E402
from draft_eval_run2 import KEY, hid, redact, salt  # noqa: E402

DATA, DOCS = ROOT / 'data', ROOT / 'docs'
LOG = DOCS / 'drafts_run3.jsonl'
N, SEED = 50, 2027
DRAFTABLE = ('due', 'overdue', 'lapsed')


def non_product_table():
    raw = pd.read_pickle(DATA / 'uci_raw.pkl')
    raw['StockCode'] = raw['StockCode'].astype(str).str.strip()
    flagged = raw[raw['StockCode'].map(is_non_product) | raw['Description'].fillna('').map(is_non_product)]
    t = flagged.groupby('StockCode').agg(lines=('StockCode', 'size'),
                                         description=('Description', lambda s: s.dropna().astype(str).str.strip()
                                                      .value_counts().index[0] if s.notna().any() else ''))
    print(f'non-product stock codes excluded from draft facts: {len(t)} '
          f'(listed codes {len(NON_PRODUCT_CODES)} + gift_0001_* vouchers)')
    print(t.sort_values('lines', ascending=False).to_string())


def main():
    s = salt()
    non_product_table()
    inv = pd.read_csv(DATA / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
    dev, _ = split_holdout(inv)
    lines = product_lines()
    lines = lines[lines['customer_id'].isin(set(dev['customer_id']))]
    catalogue = sorted(set(lines['product']))
    a = run_audit(dev)
    rec = tier_track_record(a, a['ranker'])
    now = score_now(dev, a['ranker'])['scored']
    now = now.assign(intent=intents(dev, now))
    print(f"\ncontact list (development customers, {len(now)}): intents {dict(Counter(now['intent']))}")

    earlier = {r['customer_id'] for f in ('draft_eval.json', 'draft_eval_run2.json')
               for r in json.loads((DATA / f).read_text(encoding='utf-8'))}
    pool = sorted(c for c, i in zip(now['customer_id'], now['intent'])
                  if i in DRAFTABLE and str(int(c)) not in earlier)
    picked = random.Random(SEED).sample(pool, N)
    llm = client()
    print(f'model {llm[1]} | {N} customers (due/overdue/lapsed), seed {SEED}, {len(earlier)} earlier customers '
          f'excluded | catalogue {len(catalogue)} products')

    key = pd.read_csv(KEY, dtype=str)
    known = dict(zip(key['customer_id'], key['id_hash']))
    rows, log_lines = [], []
    for i, c in enumerate(picked, 1):
        row = now[now['customer_id'] == c].iloc[0]
        f = draft_facts(dev[dev['customer_id'] == c], usual_products(lines[lines['customer_id'] == c]),
                        c, row['tier'], rec.loc[row['tier'], 'pooled'], row['recency'])
        assert f['intent'] == row['intent']
        for retry in range(3):          # retry the whole draft with backoff on API errors only
            r = llm_draft(f, llm, catalogue)
            if not any(p and p[0].startswith('API error') for _, p, _ in r['attempts']):
                break
            time.sleep(5 * 2 ** retry)
        cid = f['customer_id']
        h = known.setdefault(cid, hid(cid, s))
        public = {k: v for k, v in f.items() if k != 'customer_id'}
        for n, (raw, problems, temp) in enumerate(r['attempts'], 1):
            try:
                spec = not problems and is_specific(_parse(raw), f)
            except ValueError:
                spec = False
            log_lines.append({'id': h, 'facts': public, 'raw_draft': redact(raw, cid, h), 'attempt': n,
                              'temperature': temp, 'verdict': 'rejected' if problems else
                              ('good' if spec else 'generic'), 'reject_reasons': [redact(p, cid, h) for p in problems]})
        rows.append({'customer_id': cid, 'id': h, 'intent': f['intent'], 'facts': f, 'source': r['source'],
                     'text': redact(r['text'], cid, h), 'specific': r['specific'], 'seconds': r['seconds'],
                     'json_failures': r['json_failures'], 'attempts': r['attempts']})
        print(f"{i:2d}. {f['intent']:8s} {r['source']:13s} {r['seconds']:5.1f}s", flush=True)

    assert len(set(known.values())) == len(known), 'hash collision'
    pd.DataFrame({'customer_id': list(known), 'id_hash': list(known.values())}).to_csv(KEY, index=False)
    LOG.write_text(''.join(json.dumps(x) + '\n' for x in log_lines), encoding='utf-8')
    (DATA / 'draft_eval_run3.json').write_text(json.dumps(rows, indent=1, default=str), encoding='utf-8')

    print(f"\n{'intent':10s} {'n':>3s} {'verified':>9s} {'1st try':>8s} {'repaired':>9s} {'specific':>9s} "
          f"{'generic':>8s} {'good':>5s} {'rejected':>9s}  rejection reasons (first attempt)")
    for intent in DRAFTABLE + ('all',):
        g = [r for r in rows if intent in ('all', r['intent'])]
        ver = [r for r in g if r['source'] != 'template']
        spec = sum(r['specific'] for r in ver)
        rej = [r for r in g if r['source'] == 'template']
        reasons = Counter(p.split(':')[0] for r in rej for p in (r['attempts'][0][1] if r['attempts'] else []))
        print(f"{intent:10s} {len(g):3d} {len(ver):9d} {sum(r['source'] == 'llm' for r in g):8d} "
              f"{sum(r['source'] == 'llm_repaired' for r in g):9d} {spec:9d} {len(ver) - spec:8d} {spec:5d} "
              f"{len(rej):9d}  {dict(reasons)}")
    print(f"JSON failures: {sum(r['json_failures'] for r in rows)} | seconds per draft: "
          f"mean {statistics.mean(r['seconds'] for r in rows):.1f}")

    print('\n--- 20 random run 3 drafts to rate (seed 7): send as is / small edit / not sendable ---')
    for r in random.Random(7).sample(rows, 20):
        print(f"{r['id']} | {r['intent']} | source {r['source']} | products {r['facts']['usual_products']}\n   {r['text']}")


if __name__ == '__main__':
    main()
