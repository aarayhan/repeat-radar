"""Column mapping for any export: LLM proposal first, rule-based fallback, both checked in code
against the column names (validate_mapping) and against the values (check_values)."""
import json
import re

import pandas as pd

from app.llm import OPTIONAL, REQUIRED, map_columns, validate_mapping

# Normalized names (lowercase, letters and digits only), in priority order.
SYNONYMS = {
    'customer_id': ['customerid', 'customerno', 'customernumber', 'customer', 'custid', 'clientid', 'buyerid',
                    'kodepelanggan', 'idpelanggan', 'nopelanggan', 'pelanggan'],
    'invoice_id': ['invoice', 'invoiceno', 'invoiceid', 'invoicenumber', 'orderid', 'ordernumber', 'orderno', 'order',
                   'transactionid', 'nota', 'nonota', 'nomornota', 'faktur', 'nofaktur'],
    'date': ['invoicedate', 'orderdate', 'transactiondate', 'date', 'createdat', 'tanggal', 'tgl', 'tanggaltransaksi'],
    'quantity': ['quantity', 'qty', 'qtyordered', 'units', 'jumlah', 'jml', 'kuantitas'],
    'price': ['price', 'unitprice', 'priceeach', 'harga', 'hargasatuan'],
    'country': ['country', 'shipcountry', 'billingcountry', 'negara'],
    'product': ['description', 'productname', 'itemname', 'product', 'item', 'namabarang', 'namaproduk', 'produk',
                'stockcode', 'sku', 'productcode', 'itemcode', 'kodebarang'],  # names before codes
    'line_total': ['total', 'linetotal', 'subtotal', 'totalprice', 'lineamount', 'amount', 'totalharga',
                   'jumlahharga', 'nilai'],
}
MIN_SHARE = 0.9   # share of sampled rows that must look right
MIN_CUSTOMER_SHARE = 0.5  # guest orders without a customer id are common (about 1 in 4 lines in UCI)


def _norm(c):
    return re.sub(r'[^a-z0-9]', '', str(c).lower())


def rule_mapping(columns):
    """Exact match of normalized column names against SYNONYMS. Unmatched fields are None."""
    norm = {}
    for c in columns:
        norm.setdefault(_norm(c), c)
    out, used = {}, set()
    for field in REQUIRED + OPTIONAL:
        out[field] = next((norm[s] for s in SYNONYMS[field] if s in norm and norm[s] not in used), None)
        used.add(out[field])
    if out['line_total'] is None:
        del out['line_total']  # only reported when the export has one (the engine computes quantity x price)
    return out


def _date_share(col):
    if pd.api.types.is_datetime64_any_dtype(col):
        return col.notna().mean()
    if pd.api.types.is_numeric_dtype(col):
        return 0.0  # ids and amounts are not dates
    s = col.dropna().astype(str)
    s = s[~s.str.fullmatch(r'\s*\d+(\.\d+)?\s*')]
    return pd.to_datetime(s, errors='coerce', format='mixed').notna().sum() / max(len(col), 1)


def check_values(df, mapping, sample=500):
    """Do the mapped columns hold the right kind of values? Returns a list of problems (empty = ok)."""
    s = df.head(sample)
    problems = []
    if _date_share(s[mapping['date']]) < MIN_SHARE:
        problems.append(f"date -> {mapping['date']!r}: values do not look like dates")
    for f in ('quantity', 'price', 'line_total'):
        if mapping.get(f) and pd.to_numeric(s[mapping[f]], errors='coerce').notna().mean() < MIN_SHARE:
            problems.append(f'{f} -> {mapping[f]!r}: values are not numbers')
    if _norm(mapping['price']) in SYNONYMS['line_total']:
        problems.append(f"price -> {mapping['price']!r}: this is a line total, not a unit price")
    if s[mapping['invoice_id']].notna().mean() < MIN_SHARE:
        problems.append(f"invoice_id -> {mapping['invoice_id']!r}: too many empty values")
    if s[mapping['customer_id']].notna().mean() < MIN_CUSTOMER_SHARE:
        problems.append(f"customer_id -> {mapping['customer_id']!r}: too many empty values")
    return problems


def _checked(mapping, columns, df):
    try:
        validate_mapping(json.dumps(mapping), columns)
    except ValueError as e:
        return [str(e)]
    return check_values(df, mapping)


def propose_mapping(df, llm=None, model=None, n_sample_rows=3):
    """LLM first (if configured), rules as fallback. source is 'llm', 'rules', or None (user must map by hand).
    Only n_sample_rows rows are sent to the LLM provider."""
    columns = [str(c) for c in df.columns]
    df = df.set_axis(columns, axis=1)
    llm_error = None
    try:
        m, _ = map_columns(columns, df.head(n_sample_rows).astype(str).values.tolist(), llm=llm, model=model)
        problems = check_values(df, m)
        if not problems:
            return {'mapping': m, 'source': 'llm', 'problems': [], 'llm_error': None}
        llm_error = 'LLM mapping failed the value checks: ' + '; '.join(problems)
    except RuntimeError as e:  # LLMUnavailable, or failed twice
        llm_error = str(e)
    m = rule_mapping(columns)
    problems = _checked(m, columns, df)
    return {'mapping': m, 'source': None if problems else 'rules', 'problems': problems, 'llm_error': llm_error}
