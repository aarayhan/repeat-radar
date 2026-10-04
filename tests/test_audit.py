import numpy as np
import pytest

from app.audit import run_audit, window_metrics
from app.engine import features


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
