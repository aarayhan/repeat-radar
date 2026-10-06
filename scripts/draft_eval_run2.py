"""Draft evaluation run 2 (verifier v2) and the recomputation of run 1 with the same definitions.

    python scripts/draft_eval_run2.py

- Sample: 50 development customers from the contact list (2+ orders), seed 2026, excluding all 50 run 1 customers.
- Customer ids never reach docs/: they are replaced by the first 12 hex chars of SHA-256(salt + id). The salt
  (secrets.token_hex(32), new, made once) is in data/draft_id_salt.txt and the id-to-hash key in data/draft_id_key.csv,
  both gitignored.
- Log: docs/drafts_run2.jsonl, one line per LLM attempt: hashed id, facts (without the id), raw draft, attempt,
  temperature, verdict, reject reasons.
- Run 1 is recomputed from data/draft_eval.json (its saved drafts); nothing from run 1 is re-run.
"""
import hashlib
import json
import random
import secrets
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from app.audit import run_audit, score_now, tier_track_record  # noqa: E402
from app.drafts import _parse, draft_facts, is_specific, llm_draft, usual_products, verify  # noqa: E402
from app.engine import split_holdout  # noqa: E402
from app.llm import client  # noqa: E402
from draft_eval import product_lines  # noqa: E402

DATA, DOCS = ROOT / 'data', ROOT / 'docs'
SALT, KEY, LOG = DATA / 'draft_id_salt.txt', DATA / 'draft_id_key.csv', DOCS / 'drafts_run2.jsonl'
N, SEED = 50, 2026


def salt():
    if not SALT.exists():
        SALT.write_text(secrets.token_hex(32))
    return SALT.read_text().strip()


def hid(customer_id, s):
    return hashlib.sha256((s + str(customer_id)).encode()).hexdigest()[:12]


def redact(text, cid, h):
    return (text or '').replace(cid, h)


def verdict_of(problems, specific):
    return 'rejected' if problems else ('good' if specific else 'generic')


def summarize(rows):
    """rows: dicts with outcome ('first', 'repair', 'rejected'), final_text, facts, json_failures, seconds,
    reasons (first-attempt reasons of rejected drafts)."""
    c = Counter(r['outcome'] for r in rows)
    verified = [r for r in rows if r['outcome'] != 'rejected']
    specific = sum(is_specific(r['final_text'], r['facts']) for r in verified)
    reasons = Counter(p.split(':')[0] for r in rows if r['outcome'] == 'rejected' for p in r['reasons'])
    secs = [r['seconds'] for r in rows]
    return {'passed first try': c['first'], 'passed after repair': c['repair'], 'rejected': c['rejected'],
            'verified': len(verified), 'specific': specific, 'generic': len(verified) - specific,
            'good (verified and specific)': specific, 'JSON failures (replies)': sum(r['json_failures'] for r in rows),
            'seconds per draft (mean)': round(statistics.mean(secs), 1), 'rejection reasons': dict(reasons)}


def recompute_run1(catalogue):
    rows = []
    for r in json.loads((DATA / 'draft_eval.json').read_text(encoding='utf-8')):
        outcome, final, reasons = 'rejected', None, []
        for i, attempt in enumerate(r['attempts'][:2]):
            try:
                msg = _parse(attempt[0])
                problems = verify(msg, r['facts'], catalogue)
            except ValueError as e:
                msg, problems = None, [str(e)]
            if i == 0:
                reasons = problems
            if not problems:
                outcome, final = ('first' if i == 0 else 'repair'), msg
                break
        rows.append({'customer_id': r['customer_id'], 'outcome': outcome, 'final_text': final or '',
                     'facts': r['facts'], 'json_failures': r['json_failures'], 'seconds': r['seconds'],
                     'reasons': reasons})
    return rows


def main():
    s = salt()
    inv = pd.read_csv(DATA / 'invoices.csv', dtype={'invoice_id': str}, parse_dates=['date'])
    dev, _ = split_holdout(inv)
    lines = product_lines()
    lines = lines[lines['customer_id'].isin(set(dev['customer_id']))]
    catalogue = sorted(set(lines['product']))
    a = run_audit(dev)
    rec = tier_track_record(a, a['ranker'])
    now = score_now(dev, a['ranker'])['scored']
    run1_ids = {r['customer_id'] for r in json.loads((DATA / 'draft_eval.json').read_text(encoding='utf-8'))}
    pool = sorted(c for c in now['customer_id'] if str(int(c)) not in run1_ids)
    picked = random.Random(SEED).sample(pool, N)
    llm = client()
    print(f"model {llm[1]} | {N} development customers, seed {SEED}, none from run 1 ({len(run1_ids)} excluded) | "
          f"catalogue {len(catalogue)} products")

    rows, log_lines, key = [], [], {}
    for i, c in enumerate(picked, 1):
        row = now[now['customer_id'] == c].iloc[0]
        facts = draft_facts(dev[dev['customer_id'] == c], usual_products(lines[lines['customer_id'] == c]),
                            c, row['tier'], rec.loc[row['tier'], 'pooled'], row['recency'])
        for retry in range(3):          # retry the whole draft with backoff on API errors only
            r = llm_draft(facts, llm, catalogue)
            if not any(p and p[0].startswith('API error') for _, p, _ in r['attempts']):
                break
            time.sleep(5 * 2 ** retry)
        cid = facts['customer_id']
        h = key.setdefault(cid, hid(cid, s))
        public_facts = {k: v for k, v in facts.items() if k != 'customer_id'}
        for n, (raw, problems, temp) in enumerate(r['attempts'], 1):
            try:
                spec = not problems and is_specific(_parse(raw), facts)
            except ValueError:
                spec = False
            log_lines.append({'id': h, 'facts': public_facts, 'raw_draft': redact(raw, cid, h), 'attempt': n,
                              'temperature': temp, 'verdict': verdict_of(problems, spec),
                              'reject_reasons': [redact(p, cid, h) for p in problems]})
        outcome = {'llm': 'first', 'llm_repaired': 'repair', 'template': 'rejected'}[r['source']]
        rows.append({'customer_id': cid, 'id': h, 'outcome': outcome,
                     'final_text': r['text'] if outcome != 'rejected' else '', 'facts': facts,
                     'json_failures': r['json_failures'], 'seconds': r['seconds'],
                     'reasons': r['attempts'][0][1] if r['attempts'] else [], 'attempts': r['attempts']})
        print(f'{i:2d}. {outcome:8s} {r["seconds"]:5.1f}s', flush=True)

    assert len(set(key.values())) == len(key), 'hash collision among logged ids'
    pd.DataFrame({'customer_id': list(key), 'id_hash': list(key.values())}).to_csv(KEY, index=False)
    LOG.write_text(''.join(json.dumps(x) + '\n' for x in log_lines), encoding='utf-8')
    (DATA / 'draft_eval_run2.json').write_text(json.dumps(rows, indent=1, default=str), encoding='utf-8')

    run1 = recompute_run1(catalogue)
    s1, s2 = summarize(run1), summarize(rows)
    print(f"\n{'metric':32s} {'run 1 (RECOMPUTED from saved drafts)':>38s} {'run 2':>8s}")
    for k in s2:
        print(f'{k:32s} {str(s1[k]):>38s} {str(s2[k]):>8s}')
    good = s2['good (verified and specific)']
    print(f"\ntarget: at least 40 of 50 good after repair -> run 2 has {good}: {'MET' if good >= 40 else 'NOT MET'}")
    print(f'logged {len(log_lines)} attempts for {len(key)} customers, hashed ids unique: True')

    worst = sorted([r for r in rows if r['outcome'] == 'rejected'], key=lambda r: -len(r['attempts'][-1][1]))[:3]
    for k, r in enumerate(worst, 1):
        print(f"\n--- worst #{k} (id {r['id']}) ---")
        for n, (raw, problems, temp) in enumerate(r['attempts'], 1):
            print(f"attempt {n} (temperature {temp}): {redact(raw, r['customer_id'], r['id'])!r}")
            print(f"  verifier: {[redact(p, r['customer_id'], r['id']) for p in problems]}")

    goods = [r for r in rows if r['outcome'] != 'rejected' and is_specific(r['final_text'], r['facts'])]
    print('\n--- 10 random good drafts for hand-check (seed 7) ---')
    for r in random.Random(7).sample(goods, min(10, len(goods))):
        print(f"{r['id']} | days {r['facts']['days_since_last_order']} | products {r['facts']['usual_products']} | "
              f"last order {r['facts']['last_order']}\n   {redact(r['final_text'], r['customer_id'], r['id'])}")


if __name__ == '__main__':
    main()
