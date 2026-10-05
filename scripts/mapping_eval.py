"""Column mapping accuracy: LLM (5 runs, the app's temperature) vs rules (1 run) on UCI and the 2 variants,
compared field by field with scripts/mapping_truth.json. Run from the repo root:
    python scripts/mapping_eval.py
Needs data/uci_raw.pkl and data/variants/ (scripts/make_mapping_variants.py) and an LLM key in .env.
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.llm import OPTIONAL, REQUIRED, client, map_columns, validate_mapping  # noqa: E402
from app.mapping import check_values, rule_mapping  # noqa: E402

TRUTH = json.loads((ROOT / 'scripts' / 'mapping_truth.json').read_text(encoding='utf-8'))
RUNS = 5


def load(name):
    if name == 'uci':
        return pd.read_pickle(ROOT / 'data' / 'uci_raw.pkl')
    return pd.read_csv(ROOT / TRUTH[name]['file'])


def right(field, value, truth):
    t = truth[field]
    return value in t if isinstance(t, list) else value == t


def caught(m, columns, df):
    """Problems the app's checks find (names, values, invoice structure). Empty list = not caught."""
    try:
        validate_mapping(json.dumps(m), columns)
    except ValueError as e:
        return [str(e)]
    return check_values(df, m)


def llm_map(columns, rows, llm):
    for attempt in range(3):     # retry with backoff on API errors only
        try:
            return map_columns(columns, rows, llm=llm[0], model=llm[1])[0], None
        except RuntimeError as e:
            if 'API error' not in str(e) or attempt == 2:
                return None, str(e)[:200]
            time.sleep(5 * 2 ** attempt)


def verdict(m, truth, columns, df):
    if m is None:
        return 'no mapping (LLM failed)', []
    wrong = [f for f in REQUIRED if not right(f, m.get(f), truth)]
    if not wrong:
        return 'correct', []
    problems = caught(m, columns, df)
    return ('wrong, caught by checks' if problems else 'wrong, NOT caught'), wrong + problems[:2]


def main():
    llm = client()
    print(f'LLM {llm[1]}, temperature 0 (app setting), {RUNS} runs per file; rules once per file\n')
    agree_both_wrong = agree_total = 0
    for name, truth in ((k, v) for k, v in TRUTH.items() if not k.startswith('_')):
        df = load(name)
        columns = [str(c) for c in df.columns]
        df = df.set_axis(columns, axis=1)
        rows = df.head(3).astype(str).values.tolist()   # the same 3 rows the app sends
        rules = rule_mapping(columns)
        runs = [llm_map(columns, rows, llm) for _ in range(RUNS)]
        maps = [m for m, _ in runs]
        print(f'===== {name} ({len(df):,} rows, columns: {columns})')
        print(f"{'field':12s} {'truth':28s} {'rules':22s} LLM runs 1-5")
        for f in REQUIRED + OPTIONAL:
            t = truth[f]
            mark = lambda v: ('ok ' if right(f, v, truth) else 'XX ') + str(v)  # noqa: E731
            print(f"{f:12s} {str(t):28s} {mark(rules.get(f)):22s} "
                  + ' | '.join(mark(m.get(f)) if m else 'FAILED' for m in maps))
        v, why = verdict(rules, truth, columns, df)
        print(f'rules: {v} {why}')
        for i, (m, err) in enumerate(runs, 1):
            v, why = verdict(m, truth, columns, df)
            print(f'LLM run {i}: {v} {why or ""} {err or ""}')
            if m is not None:
                agree = all(m.get(f) is not None and m.get(f) == rules.get(f) for f in REQUIRED)
                agree_total += agree
                agree_both_wrong += agree and v != 'correct'
        same = all(m == maps[0] for m in maps) and maps[0] is not None
        print(f'all {RUNS} LLM runs identical: {same}' + (' -> 1 effective run' if same else ''))
        print()
    print(f'LLM runs where LLM and rules agreed on every required field: {agree_total}; '
          f'of those, both wrong: {agree_both_wrong}')


if __name__ == '__main__':
    main()
