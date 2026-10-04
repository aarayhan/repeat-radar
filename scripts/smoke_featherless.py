"""Smoke test: one real LLM call maps export columns to valid JSON.

Run from the repo root: python scripts/smoke_featherless.py
Provider from LLM_PROVIDER (default featherless) with its key in .env; optional LLM_MODEL. The key is never printed.
Sample rows are synthetic, not taken from the dataset.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.llm import client, map_columns  # noqa: E402

COLS = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country']
ROWS = [  # synthetic
    ['900001', 'X100', 'BLUE TEST MUG', 6, '2030-01-05 09:12', 2.5, 99001, 'Testland'],
    ['900001', 'X200', 'RED TEST BOWL', 2, '2030-01-05 09:12', 4.0, 99001, 'Testland'],
    ['900002', 'X100', 'BLUE TEST MUG', 12, '2030-01-06 14:40', 2.1, 99002, 'Otherland'],
]
EXPECTED = {'customer_id': 'Customer ID', 'invoice_id': 'Invoice', 'date': 'InvoiceDate',
            'quantity': 'Quantity', 'price': 'Price', 'country': 'Country'}


def main():
    try:
        llm, model = client()
        print('provider:', os.getenv('LLM_PROVIDER', 'featherless'), '| model:', model)
        mapping, attempts = map_columns(COLS, ROWS, llm=llm, model=model)
    except RuntimeError as e:
        print('FAIL:', e)
        sys.exit(1)
    for i, (raw, err) in enumerate(attempts, 1):
        print(f'attempt {i}: error={err}\nraw reply: {raw!r}')
    print('parsed (schema-valid):', mapping)
    wrong = {k: (mapping.get(k), v) for k, v in EXPECTED.items() if mapping.get(k) != v}
    product_ok = mapping.get('product') in ('Description', 'StockCode')
    print('expected fields correct:', not wrong, wrong or '')
    print('product mapped to Description/StockCode:', product_ok)
    print('RESULT:', 'PASS' if not wrong and product_ok else 'VALID JSON, WRONG MAPPING')
    sys.exit(0 if not wrong and product_ok else 2)


if __name__ == '__main__':
    main()
