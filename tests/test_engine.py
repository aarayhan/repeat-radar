import numpy as np
import pandas as pd
import pytest

from app.engine import FEATURES, calibration, clean, ece, features, top_k_hit

T = pd.Timestamp


def test_clean_drops_bad_lines_and_sums_invoices():
    raw = pd.DataFrame([
        # Invoice, Quantity, Price, Customer ID, InvoiceDate
        ('1', 2, 5.0, 1.0, T('2021-01-01 10:00')),
        ('1', 1, 3.0, 1.0, T('2021-01-01 11:00')),
        ('C2', 1, 5.0, 1.0, T('2021-01-02')),     # cancellation
        ('3', -1, 5.0, 1.0, T('2021-01-03')),     # return
        ('4', 1, 0.0, 1.0, T('2021-01-04')),      # zero price
        ('5', 1, 5.0, np.nan, T('2021-01-05')),   # no customer
        (6, 1, 7.0, 1.0, T('2021-02-01 09:30')),  # numeric invoice id
    ], columns=['Invoice', 'Quantity', 'Price', 'Customer ID', 'InvoiceDate'])
    inv = clean(raw).sort_values('date').reset_index(drop=True)
    assert list(inv.columns) == ['customer_id', 'invoice_id', 'date', 'amount']
    assert inv['invoice_id'].tolist() == ['1', '6']
    assert inv['amount'].tolist() == [13.0, 7.0]
    assert inv['date'].tolist() == [T('2021-01-01'), T('2021-02-01')]


def _inv(rows):
    return pd.DataFrame(rows, columns=['customer_id', 'invoice_id', 'date', 'amount']).assign(
        date=lambda d: pd.to_datetime(d['date']))


BASE = [
    ('A', 'a1', '2021-01-01', 10.0), ('A', 'a2', '2021-03-01', 20.0),
    ('A', 'a3', '2021-05-20', 5.0),                                    # inside horizon
    ('B', 'b1', '2021-01-10', 8.0),                                    # only 1 prior order
    ('C', 'c1', '2020-06-01', 4.0), ('C', 'c2', '2020-07-01', 4.0),
    ('C', 'c3', '2021-05-27', 4.0),                                    # exactly origin + 56: outside
]
ORIGIN = T('2021-04-01')


def test_features_values_and_label():
    f = features(_inv(BASE), ORIGIN)
    assert sorted(f.index) == ['A', 'C']  # B has < 2 prior orders
    a, c = f.loc['A'], f.loc['C']
    assert (a['n'], a['recency'], a['tenure'], a['n90'], a['y']) == (2, 31, 90, 2, 1)
    assert a['lograv'] == pytest.approx(np.log1p(15.0))
    assert a['logn'] == pytest.approx(np.log1p(2))
    assert (c['n90'], c['y']) == (0, 0)


def test_invoice_on_origin_is_future_not_past():
    f = features(_inv(BASE + [('C', 'c4', '2021-04-01', 1.0)]), ORIGIN)
    assert f.loc['C', 'n'] == 2 and f.loc['C', 'y'] == 1


def test_no_leakage_from_future_invoices():
    later = [('A', 'x1', '2021-04-02', 999.0), ('C', 'x2', '2022-01-01', 999.0),
             ('B', 'x3', '2021-06-01', 999.0)]
    f0 = features(_inv(BASE), ORIGIN)
    f1 = features(_inv(BASE + later), ORIGIN)
    pd.testing.assert_frame_equal(f0[FEATURES], f1[FEATURES])


def test_top_k_hit():
    y = np.array([1, 0, 1, 0, 0, 1, 0, 0, 0, 0])
    s = np.array([9, 8, 7, 6, 5, 4, 3, 2, 1, 0])
    assert top_k_hit(y, s) == 0.5               # top 2 -> [1, 0]
    assert top_k_hit(y, s, frac=0.3) == pytest.approx(2 / 3)


def test_calibration_and_ece():
    t = calibration(np.array([0, 0, 1, 0, 1]), np.array([0.05, 0.05, 0.75, 0.75, 1.0]))
    assert t.index.tolist() == ['0.0-0.1', '0.7-0.8', '0.9-1.0']  # p=1.0 lands in last bin
    assert t.loc['0.7-0.8', 'n'] == 2
    assert t.loc['0.7-0.8', 'obs'] == 0.5
    assert t.loc['0.7-0.8', 'gap'] == pytest.approx(-0.25)
    assert ece(t) == pytest.approx((2 * 0.05 + 2 * 0.25 + 1 * 0.0) / 5)
