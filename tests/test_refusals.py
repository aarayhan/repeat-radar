import pandas as pd

from app.audit import choose_ranker, recommend, run_audit, window_ok

T = pd.Timestamp


def test_rule1_single_order_customer_not_scored(make_inv):
    inv = make_inv()
    solo = pd.DataFrame({'customer_id': [9999], 'invoice_id': ['solo'], 'date': [T('2031-06-01')], 'amount': [10.0]})
    r = recommend(pd.concat([inv, solo], ignore_index=True))
    assert 9999 not in set(r['scored']['customer_id'])
    row = r['not_scored'].set_index('customer_id').loc[9999]
    assert row['n_orders'] == 1 and 'need at least 2' in row['reason']
    assert set(r['scored']['customer_id']).isdisjoint(r['not_scored']['customer_id'])


def test_rule2_short_history_is_refused(make_inv):
    r = recommend(make_inv(days=300))
    a = r['audit']
    assert a['status'] == 'insufficient_data'
    assert 'at least 371 days' in a['reason'] and 'covers' in a['reason']
    assert 'scored' not in r  # nothing gets scored


def test_rule2_too_few_customers(make_inv):
    inv = make_inv(n_customers=30)
    ok, why = window_ok(inv, inv['date'].max() - pd.Timedelta(days=56))
    assert not ok and 'need 50' in why
    assert run_audit(inv)['status'] == 'insufficient_data'


def _windows(model, recency):
    return pd.DataFrame({'origin': [T('2031-01-01'), T('2031-04-01'), T('2031-07-01')][:len(model)],
                         'top20_model': model, 'top20_recency': recency})


def test_rule3_model_must_win_every_window():
    assert choose_ranker(_windows([0.8, 0.7, 0.7], [0.6, 0.6, 0.6]))[0] == 'model'
    ranker, why = choose_ranker(_windows([0.8, 0.5, 0.7], [0.6, 0.6, 0.6]))
    assert ranker == 'recency' and '2031-04-01' in why and '2031-01-01' not in why
    assert choose_ranker(_windows([0.8, 0.6], [0.6, 0.6]))[0] == 'recency'  # tie loses


def test_ok_audit_carries_ranker(make_inv):
    r = recommend(make_inv())
    assert r['audit']['status'] == 'ok' and r['ranker'] == r['audit']['ranker']
    assert list(r['track_record'].index) == ['high', 'medium', 'low']
