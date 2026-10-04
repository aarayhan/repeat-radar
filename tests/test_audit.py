import numpy as np
import pytest

from app.audit import run_audit, score_now, tier_of, tier_track_record, window_metrics
from app.engine import features, top_k_hit


def test_tier_cuts():
    t = tier_of(np.arange(10))
    assert [(t == k).sum() for k in ('high', 'medium', 'low')] == [2, 3, 5]
    assert set(t[[8, 9]]) == {'high'} and set(t[:5]) == {'low'}


def test_high_tier_is_the_audited_top20():
    rng = np.random.default_rng(1)
    y, s = rng.integers(0, 2, 333), rng.integers(0, 20, 333)  # ties on purpose
    assert y[tier_of(s) == 'high'].mean() == top_k_hit(y, s)


def test_tier_record_and_current_list(make_inv):
    inv = make_inv()
    a = run_audit(inv)
    w, t = a['windows'], a['tiers']
    for ranker in ('model', 'recency'):
        high = t[(t['ranker'] == ranker) & (t['tier'] == 'high')]['hit_rate'].values
        assert np.allclose(high, w[f'top20_{ranker}'].values)
        rec = tier_track_record(a, ranker)
        assert list(rec.index) == ['high', 'medium', 'low'] and (rec['windows'] == 3).all()
        assert ((rec['min'] <= rec['pooled']) & (rec['pooled'] <= rec['max'])).all()
    now = score_now(inv)['scored']
    assert set(now['tier']) == {'high', 'medium', 'low'}
    assert list(now['rank']) == list(range(1, len(now) + 1))
    assert not {'p', 'prob', 'score', 'probability'} & set(now.columns)  # no probability shown
    rec_now = score_now(inv, ranker='recency')['scored']
    assert rec_now[rec_now['tier'] == 'high']['recency'].max() <= rec_now[rec_now['tier'] == 'low']['recency'].min()


def test_window_metrics_by_hand():
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    s_model = np.arange(10, 0, -1)          # perfect ranking
    s_rec = np.arange(1, 11)                # worst ranking
    m = window_metrics(y, s_model, s_rec)
    assert m['n'] == 10 and m['base_rate'] == 0.2
    assert (m['auc_model'], m['auc_recency']) == (1.0, 0.0)
    assert (m['top20_model'], m['top20_recency']) == (1.0, 0.0)


def test_audit_on_synthetic_history(make_inv):
    inv = make_inv()
    w = run_audit(inv)['windows']
    assert len(w) == 3
    for col in ['base_rate', 'auc_model', 'auc_recency', 'top20_model', 'top20_recency']:
        assert w[col].between(0, 1).all()
    for _, row in w.iterrows():
        f = features(inv, row['origin'])
        assert row['n'] == len(f)
        assert row['base_rate'] == pytest.approx(f['y'].mean())
