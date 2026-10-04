"""Audit on the user's own history: per-window metrics against the recency rule."""
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.engine import HORIZON, backtest, top_k_hit


def window_metrics(y, s_model, s_recency):
    return {'n': len(y), 'base_rate': y.mean(),
            'auc_model': roc_auc_score(y, s_model), 'auc_recency': roc_auc_score(y, s_recency),
            'top20_model': top_k_hit(y, s_model), 'top20_recency': top_k_hit(y, s_recency)}


def run_audit(inv, horizon=HORIZON):
    runs = backtest(inv, horizon)
    windows = pd.DataFrame([{'origin': r['origin'], **window_metrics(r['y'], r['p'], r['s_recency'])}
                            for r in runs])
    return {'windows': windows}
