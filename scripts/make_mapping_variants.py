"""Two export variants made from a UCI sample, to test column mapping. Data goes to data/variants/ (gitignored,
it is derived from UCI); the true mapping is in scripts/mapping_truth.json (committed before any LLM call).

    python scripts/make_mapping_variants.py

Sample: 300 customers (seed 42) with all their lines, plus 500 lines without a customer id, sorted by time.
Variant A uses Indonesian column names, variant B English ones; both use a different column order than UCI and
add decoy columns that look like ids (a unique line number, a warehouse code).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import load_uci  # noqa: E402

DATA = ROOT / 'data'
RAW = DATA / 'uci_raw.pkl'
OUT = DATA / 'variants'
SEED = 42


def uci_raw():
    if not RAW.exists():
        load_uci(DATA / 'online_retail_II.xlsx').to_pickle(RAW)
    return pd.read_pickle(RAW)


def main():
    raw = uci_raw()
    rng = np.random.default_rng(SEED)
    customers = rng.choice(np.sort(raw['Customer ID'].dropna().unique()), 300, replace=False)
    guests = raw[raw['Customer ID'].isna()].sample(500, random_state=SEED)
    s = pd.concat([raw[raw['Customer ID'].isin(customers)], guests]).sort_values('InvoiceDate', kind='stable')
    s = s.reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    warehouse = rng.integers(1, 5, len(s))

    pd.DataFrame({
        'No Urut': np.arange(1, len(s) + 1),
        'Tanggal Transaksi': s['InvoiceDate'].dt.strftime('%d/%m/%Y %H:%M'),
        'ID Pelanggan': s['Customer ID'].astype('Int64'),
        'Kode Barang': s['StockCode'],
        'Nama Barang': s['Description'],
        'Jumlah': s['Quantity'],
        'Harga Satuan': s['Price'],
        'No Faktur': s['Invoice'],
        'Negara': s['Country'],
        'Kode Gudang': ['GD-0' + str(w) for w in warehouse],
    }).to_csv(OUT / 'variant_a_indonesian.csv', index=False)

    pd.DataFrame({
        'Line ID': ['L' + str(1000000 + i) for i in range(len(s))],
        'Order No': s['Invoice'],
        'SKU': s['StockCode'],
        'Customer Account': s['Customer ID'].astype('Int64'),
        'Order Date': s['InvoiceDate'].dt.strftime('%Y-%m-%d %H:%M:%S'),
        'Product Name': s['Description'],
        'Unit Price': s['Price'],
        'Qty': s['Quantity'],
        'Country': s['Country'],
        'Warehouse Code': ['WH' + str(w) for w in warehouse],
    }).to_csv(OUT / 'variant_b_english.csv', index=False)
    print(f'{len(s)} lines, {s["Customer ID"].nunique()} customers, {s["Invoice"].nunique()} invoices -> {OUT}')


if __name__ == '__main__':
    main()
