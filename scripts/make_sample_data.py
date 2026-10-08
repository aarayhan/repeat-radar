"""Synthetic sample exports for the demo (seed 42). Not real customers, not real businesses.

Run from the repo root: python scripts/make_sample_data.py
Writes app/sample_data/kasir_indonesia.csv, ecommerce.csv and messy_export.csv.

Buying pattern (not tuned to make any model win): each customer has their own order rate, starts at a
random time, and many stop buying at a random point. Some customers order only once.
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / 'app' / 'sample_data'
START, DAYS = pd.Timestamp('2023-01-01'), 731   # 24 months
N_CUSTOMERS = 300


def _orders(rng):
    """One row per order: customer index and day offset."""
    rows = []
    for c in range(N_CUSTOMERS):
        first = int(rng.integers(0, DAYS - 30))
        if rng.random() < 0.15:                               # one-time buyers
            rows.append((c, first))
            continue
        rate = rng.lognormal(mean=np.log(1 / 30), sigma=0.7)   # orders per day, about monthly on average
        stop = DAYS if rng.random() < 0.5 else int(rng.integers(first + 1, DAYS + 1))  # half stop buying
        day = first
        while day < stop:
            rows.append((c, day))
            day += 1 + int(rng.exponential(1 / rate))
    return rows


def _lines(rng, orders, products):
    """Order lines: 1-3 products per order, quantity 1-12."""
    out = []
    for o, (c, day) in enumerate(orders):
        for p in rng.choice(len(products), size=int(rng.integers(1, 4)), replace=False):
            out.append((o, c, day, int(rng.integers(1, 13)), products[p]))
    return out


def make(out_dir=OUT, seed=42):
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = _lines(rng, _orders(rng), [5000, 7500, 12000, 15000, 25000, 40000])   # rupiah
    k = pd.DataFrame(lines, columns=['o', 'c', 'day', 'qty', 'price'])
    pd.DataFrame({
        'Tgl': (START + pd.to_timedelta(k['day'], unit='D')).dt.strftime('%d/%m/%Y'),
        'No Nota': 'NT-' + (k['o'] + 100001).astype(str),
        'Pelanggan': 'Toko Fiktif ' + (k['c'] + 1).astype(str).str.zfill(3),
        'Qty': k['qty'], 'Harga': k['price'], 'Total': k['qty'] * k['price'],
    }).to_csv(out_dir / 'kasir_indonesia.csv', index=False)

    lines = _lines(rng, _orders(rng), [3.5, 4.99, 7.25, 12.0, 19.9])               # dollars
    e = pd.DataFrame(lines, columns=['o', 'c', 'day', 'qty', 'price'])
    pd.DataFrame({
        'order_date': (START + pd.to_timedelta(e['day'], unit='D')).dt.strftime('%Y-%m-%d'),
        'order_id': 'ORD-' + (e['o'] + 500001).astype(str),
        'customer_email': 'fake.customer' + (e['c'] + 1).astype(str).str.zfill(3) + '@example.com',
        'quantity': e['qty'], 'unit_price': e['price'],
    }).to_csv(out_dir / 'ecommerce.csv', index=False)

    # Messy export: Indonesian column names the built-in rules do not know, dates with a time. Kode Barang is a
    # product code column (a valid product mapping, like Barang), not a decoy; this sample has no decoy column.
    # Made last, so the two files above stay byte-identical.
    names = ['Gula 1kg', 'Minyak 2L', 'Beras 5kg', 'Kopi Bubuk', 'Teh Celup', 'Sabun Cuci']
    lines = _lines(rng, _orders(rng), list(range(len(names))))
    m = pd.DataFrame(lines, columns=['o', 'c', 'day', 'qty', 'p'])
    minutes = pd.to_timedelta(rng.integers(8 * 60, 21 * 60, size=m['o'].max() + 1)[m['o']], unit='min')
    pd.DataFrame({
        'No. Struk': 'STR/' + (m['o'] + 20001).astype(str),
        'Waktu Transaksi': (START + pd.to_timedelta(m['day'], unit='D') + minutes).dt.strftime('%d-%m-%Y %H:%M'),
        'Kode Barang': 'BRG' + (m['p'] + 101).astype(str),
        'Barang': [names[p] for p in m['p']],
        'Pembeli': 'Pembeli Fiktif ' + (m['c'] + 1).astype(str).str.zfill(3),
        'Banyaknya': m['qty'],
        'Harga/Pcs': [[14500, 32000, 68000, 9500, 7000, 4500][p] for p in m['p']],
    }).to_csv(out_dir / 'messy_export.csv', index=False)


if __name__ == '__main__':
    make()
    print('written to', OUT)
