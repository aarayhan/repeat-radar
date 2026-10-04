"""Audit on the user's own history: per-window metrics against the recency rule, and rank tiers
whose hit rates are measured on past test windows (probabilities drift, see brain/03_EVIDENCE.md)."""
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.engine import HORIZON, backtest, features, fit, predict, top_k_hit

TIERS = ('high', 'medium', 'low')
HIGH, MEDIUM = 0.2, 0.5  # high = top 20% (same cut as the audited top-20% hit rate), medium = 20-50%


def window_metrics(y, s_model, s_recency):
    return {'n': len(y), 'base_rate': y.mean(),
            'auc_model': roc_auc_score(y, s_model), 'auc_recency': roc_auc_score(y, s_recency),
            'top20_model': top_k_hit(y, s_model), 'top20_recency': top_k_hit(y, s_recency)}


def tier_of(scores):
    """Tier by rank. Same ordering as top_k_hit, so the high tier is exactly the audited top 20%."""
    s = np.asarray(scores)
    n = len(s)
    rank = np.empty(n, dtype=int)
    rank[np.argsort(-s)] = np.arange(n)
    hi = max(1, int(n * HIGH))
    mid = max(hi, int(n * MEDIUM))
    return np.where(rank < hi, 'high', np.where(rank < mid, 'medium', 'low'))


def _tier_rows(origin, ranker, y, s):
    t = tier_of(s)
    return [{'origin': origin, 'ranker': ranker, 'tier': k, 'n': int((t == k).sum()), 'hits': int(y[t == k].sum())}
            for k in TIERS]


def run_audit(inv, horizon=HORIZON):
    runs = backtest(inv, horizon)
    windows = pd.DataFrame([{'origin': r['origin'], **window_metrics(r['y'], r['p'], r['s_recency'])}
                            for r in runs])
    tiers = pd.DataFrame([row for r in runs for ranker, s in (('model', r['p']), ('recency', r['s_recency']))
                          for row in _tier_rows(r['origin'], ranker, r['y'], s)])
    tiers['hit_rate'] = tiers['hits'] / tiers['n']
    return {'windows': windows, 'tiers': tiers}


def tier_track_record(audit, ranker):
    """Per tier, across past test windows: min / max / pooled share who ordered within the horizon."""
    t = audit['tiers'][audit['tiers']['ranker'] == ranker]
    g = t.groupby('tier')
    rec = pd.DataFrame({'windows': g.size(), 'min': g['hit_rate'].min(), 'max': g['hit_rate'].max(),
                        'pooled': g['hits'].sum() / g['n'].sum()}).loc[list(TIERS)]
    b = audit['windows']['base_rate']
    rec.attrs['base_rate'] = (b.min(), b.max())
    return rec


def score_now(inv, ranker='model', horizon=HORIZON):
    """Current contact list at the day after the last order. Trained on origin - h*{1,2,3}, as in the backtest.
    Shows rank and tier only, no probability."""
    origin = inv['date'].max() + pd.Timedelta(days=1)
    f = features(inv, origin, horizon)
    if ranker == 'model':
        train = pd.concat([features(inv, origin - pd.Timedelta(days=horizon * i), horizon) for i in (1, 2, 3)])
        s = predict(fit(train), f)
    else:
        s = -f['recency'].values
    scored = pd.DataFrame({'customer_id': f.index, 'n_orders': f['n'].values, 'last_order': f['last'].values,
                           'recency': f['recency'].values, 'tier': tier_of(s)})
    scored['rank'] = scored.index.map(dict(zip(np.argsort(-s), range(1, len(s) + 1))))
    return {'ranker': ranker, 'scored': scored.sort_values('rank').reset_index(drop=True)}
