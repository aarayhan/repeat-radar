"""Mapping on two synthetic export formats (plus UCI column names). No network: LLM is faked."""
import json

import pandas as pd
import pytest

import app.llm as llm_mod
from app.engine import clean
from app.llm import LLMUnavailable, client
from app.mapping import check_values, propose_mapping, rule_mapping
from test_llm import FakeLLM

UCI_COLS = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country']

# Format A: Indonesian point-of-sale export (synthetic)
FMT_A = pd.DataFrame([
    ('N001', '2030-01-05', 'P01', 'Gelas', 2, 15000, 'Bandung'),
    ('N001', '2030-01-05', 'P01', 'Piring', 1, 20000, 'Bandung'),
    ('N002', '2030-01-20', 'P02', 'Gelas', 3, 15000, 'Jakarta'),
    ('N003', '2030-02-02', 'P01', 'Gelas', -1, 15000, 'Bandung'),     # return
    ('N004', '2030-02-10', 'P02', 'Mangkok', 4, 12500, 'Jakarta'),
], columns=['No Nota', 'Tanggal', 'Kode Pelanggan', 'Nama Barang', 'Jml', 'Harga Satuan', 'Kota'])
MAP_A = {'customer_id': 'Kode Pelanggan', 'invoice_id': 'No Nota', 'date': 'Tanggal', 'quantity': 'Jml',
         'price': 'Harga Satuan', 'country': None, 'product': 'Nama Barang'}

# Format B: English e-commerce export (synthetic)
FMT_B = pd.DataFrame([
    ('#1001', '2030-03-01 10:00', 'C-7', 'SKU1', 'Blue Mug', 2, 4.5, 'UK'),
    ('#1001', '2030-03-01 10:00', 'C-7', 'SKU2', 'Red Bowl', 1, 6.0, 'UK'),
    ('#1002', '2030-03-04 12:30', 'C-8', 'SKU1', 'Blue Mug', 1, 0.0, 'FR'),   # zero price
    ('#1003', '2030-03-09 08:15', 'C-8', 'SKU3', 'Green Plate', 3, 5.0, 'FR'),
], columns=['Order Number', 'Order Date', 'Customer No', 'SKU', 'Item Name', 'Qty Ordered', 'Unit Price',
            'Ship Country'])
MAP_B = {'customer_id': 'Customer No', 'invoice_id': 'Order Number', 'date': 'Order Date', 'quantity': 'Qty Ordered',
         'price': 'Unit Price', 'country': 'Ship Country', 'product': 'Item Name'}


def _no_llm():
    return FakeLLM(LLMUnavailable('not configured'), LLMUnavailable('not configured'))


@pytest.mark.parametrize('columns, expected', [
    (UCI_COLS, {'customer_id': 'Customer ID', 'invoice_id': 'Invoice', 'date': 'InvoiceDate',
                'quantity': 'Quantity', 'price': 'Price', 'country': 'Country', 'product': 'Description'}),
    (list(FMT_A.columns), MAP_A),
    (list(FMT_B.columns), MAP_B),
])
def test_rules_map_three_formats(columns, expected):
    assert rule_mapping(columns) == expected


@pytest.mark.parametrize('df, mapping, invoices', [
    (FMT_A, MAP_A, [('N001', 'P01', '2030-01-05', 50000.0), ('N002', 'P02', '2030-01-20', 45000.0),
                    ('N004', 'P02', '2030-02-10', 50000.0)]),
    (FMT_B, MAP_B, [('#1001', 'C-7', '2030-03-01', 15.0), ('#1003', 'C-8', '2030-03-09', 15.0)]),
])
def test_both_formats_end_to_end(df, mapping, invoices):
    r = propose_mapping(df, llm=_no_llm(), model='x')
    assert r['source'] == 'rules' and r['mapping'] == mapping and r['problems'] == []
    inv = clean(df, r['mapping']).sort_values('invoice_id')
    got = [(i, c, str(d.date()), a) for i, c, d, a in inv[['invoice_id', 'customer_id', 'date', 'amount']].values]
    assert got == invoices


def test_llm_answer_used_when_valid():
    r = propose_mapping(FMT_B, llm=FakeLLM(json.dumps(MAP_B)), model='x')
    assert r['source'] == 'llm' and r['mapping'] == MAP_B


def test_invented_column_falls_back_to_rules():
    bad = json.dumps({**MAP_B, 'price': 'Price'})  # no such column
    r = propose_mapping(FMT_B, llm=FakeLLM(bad, bad), model='x')
    assert r['source'] == 'rules' and r['mapping'] == MAP_B
    assert 'failed twice' in r['llm_error'] and 'not a column' in r['llm_error']


def test_value_check_catches_plausible_but_wrong_llm_answer():
    swapped = json.dumps({**MAP_A, 'date': 'Kode Pelanggan', 'customer_id': 'Tanggal'})  # names valid, values wrong
    r = propose_mapping(FMT_A, llm=FakeLLM(swapped), model='x')
    assert r['source'] == 'rules' and r['mapping'] == MAP_A
    assert 'value checks' in r['llm_error'] and 'do not look like dates' in r['llm_error']


def test_value_checks():
    assert check_values(FMT_A, MAP_A) == []
    assert any('not numbers' in p for p in check_values(FMT_A, {**MAP_A, 'price': 'Nama Barang'}))
    assert any('dates' in p for p in check_values(FMT_B, {**MAP_B, 'date': 'Unit Price'}))
    assert any('dates' in p for p in check_values(FMT_A, {**MAP_A, 'date': 'Jml'}))


def test_no_llm_configured_uses_rules(monkeypatch):
    monkeypatch.setattr(llm_mod, 'load_dotenv', lambda *a, **k: None)
    monkeypatch.delenv('FEATHERLESS_API_KEY', raising=False)
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    r = propose_mapping(FMT_A)
    assert r['source'] == 'rules' and 'FEATHERLESS_API_KEY is not set' in r['llm_error']


def test_unmappable_export_is_refused():
    df = pd.DataFrame({'a': [1], 'b': ['x'], 'c': [2.0]})
    r = propose_mapping(df, llm=_no_llm(), model='x')
    assert r['source'] is None and 'missing required' in r['problems'][0]


def test_provider_switch(monkeypatch):
    monkeypatch.setattr(llm_mod, 'load_dotenv', lambda *a, **k: None)
    for k in ('LLM_PROVIDER', 'LLM_MODEL', 'FEATHERLESS_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(LLMUnavailable, match='FEATHERLESS_API_KEY'):
        client()
    monkeypatch.setenv('LLM_PROVIDER', 'nope')
    with pytest.raises(LLMUnavailable, match='unknown LLM_PROVIDER'):
        client()
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    with pytest.raises(LLMUnavailable, match='LLM_MODEL'):
        client()
    monkeypatch.setenv('LLM_MODEL', 'qwen2.5:7b')
    c, model = client()  # no key needed, no network call made
    assert model == 'qwen2.5:7b' and str(c.base_url).startswith('http://localhost:11434')
    monkeypatch.setenv('LLM_PROVIDER', 'openai')
    with pytest.raises(LLMUnavailable, match='OPENAI_API_KEY'):
        client()


# Ambiguous short column names (synthetic). "Total" is the line value, never the unit price.
AMBIG = pd.DataFrame([
    ('2030-04-01', 'N10', 'P01', 2, 5000, 10000),
    ('2030-04-01', 'N10', 'P01', 1, 7000, 7000),
    ('2030-04-03', 'N11', 'P02', 3, 5000, 15000),
    ('2030-04-09', 'N12', 'P01', 1, 5000, 5000),     # a second invoice, so customers < invoices (check 3)
], columns=['Tgl', 'No Nota', 'Pelanggan', 'Qty', 'Harga', 'Total'])
MAP_AMBIG = {'customer_id': 'Pelanggan', 'invoice_id': 'No Nota', 'date': 'Tgl', 'quantity': 'Qty',
             'price': 'Harga', 'country': None, 'product': None, 'line_total': 'Total'}


def test_rules_ambiguous_names():
    assert rule_mapping(list(AMBIG.columns)) == MAP_AMBIG
    r = propose_mapping(AMBIG, llm=_no_llm(), model='x')
    assert r['source'] == 'rules' and r['mapping'] == MAP_AMBIG and r['problems'] == []


def test_total_is_never_the_price_even_without_a_price_column():
    no_price = AMBIG.drop(columns='Harga')
    m = rule_mapping(list(no_price.columns))
    assert m['price'] is None and m['line_total'] == 'Total'
    r = propose_mapping(no_price, llm=_no_llm(), model='x')
    assert r['source'] is None and "missing required keys: ['price']" in r['problems'][0]  # total-only: not supported


def test_llm_mapping_total_to_price_is_rejected():
    wrong = json.dumps({**MAP_AMBIG, 'price': 'Total', 'line_total': None})
    r = propose_mapping(AMBIG, llm=FakeLLM(wrong), model='x')
    assert 'line total, not a unit price' in r['llm_error']
    assert r['source'] == 'rules' and r['mapping']['price'] == 'Harga'
    ok = propose_mapping(AMBIG, llm=FakeLLM(json.dumps(MAP_AMBIG)), model='x')
    assert ok['source'] == 'llm' and ok['mapping'] == MAP_AMBIG


# Invoice consistency checks (any mapping, LLM or rules)
UCI_LIKE = pd.DataFrame([
    ('536365', '85123A', 'WHITE HANGING HEART', 6, '2010-12-01 08:26', 2.55, 17850, 'United Kingdom'),
    ('536365', '71053', 'WHITE METAL LANTERN', 6, '2010-12-01 08:26', 3.39, 17850, 'United Kingdom'),
    ('536366', '85123A', 'WHITE HANGING HEART', 6, '2010-12-01 08:28', 2.55, 17851, 'United Kingdom'),
    ('536367', '71053', 'WHITE METAL LANTERN', 2, '2010-12-02 09:00', 3.39, 17850, 'France'),
    ('536368', '22752', 'SET 7 BABUSHKA', 1, '2010-12-03 10:00', 7.65, 17852, 'France'),
], columns=['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country'])
UCI_MAP = {'customer_id': 'Customer ID', 'invoice_id': 'Invoice', 'date': 'InvoiceDate', 'quantity': 'Quantity',
           'price': 'Price', 'country': 'Country', 'product': 'Description'}


def test_structure_checks_pass_on_true_mapping():
    from app.mapping import check_structure
    assert check_structure(UCI_LIKE, UCI_MAP) == []


def test_invoice_mapped_to_stockcode_is_caught():
    from app.mapping import check_structure
    p = check_structure(UCI_LIKE, {**UCI_MAP, 'invoice_id': 'StockCode', 'product': 'Description'})
    assert any(x.startswith('check 1 failed') for x in p) and any(x.startswith('check 2 failed') for x in p)
    assert any('check' in x for x in check_values(UCI_LIKE, {**UCI_MAP, 'invoice_id': 'StockCode'}))


def test_each_structure_check_names_itself():
    from app.mapping import check_structure
    two_days = UCI_LIKE.assign(InvoiceDate=['2010-12-01 08:26', '2010-12-02 08:26'] + list(UCI_LIKE['InvoiceDate'][2:]))
    assert [x[:7] for x in check_structure(two_days, UCI_MAP)] == ['check 2']
    one_inv_each = UCI_LIKE.assign(Invoice=['1', '1', '2', '3', '4'], **{'Customer ID': [1, 1, 2, 3, 4]})
    assert [x[:7] for x in check_structure(one_inv_each, UCI_MAP)] == ['check 3']
    swapped = {**UCI_MAP, 'customer_id': 'Invoice', 'invoice_id': 'Customer ID'}
    assert 'check 3' in ' '.join(check_structure(UCI_LIKE, swapped))


def test_disagreement_needs_a_choice():
    swapped = json.dumps({**MAP_B, 'quantity': 'Unit Price', 'price': 'Qty Ordered'})   # passes value checks
    r = propose_mapping(FMT_B, llm=FakeLLM(swapped), model='x')
    assert r['needs_choice'] and r['llm']['quantity'] == 'Unit Price' and r['rules'] == MAP_B
    agree = propose_mapping(FMT_B, llm=FakeLLM(json.dumps(MAP_B)), model='x')
    assert not agree['needs_choice']
    no_llm = propose_mapping(FMT_B, llm=_no_llm(), model='x')
    assert not no_llm['needs_choice'] and no_llm['llm'] is None


def test_one_side_empty_needs_a_choice():
    cols_b = FMT_B.rename(columns={'Customer No': 'Account Holder'})          # rules cannot map it
    llm_answer = json.dumps({**MAP_B, 'customer_id': 'Account Holder'})
    r = propose_mapping(cols_b, llm=FakeLLM(llm_answer), model='x')
    assert r['rules']['customer_id'] is None and r['needs_choice']
