"""Audit on the user's own history: per-window metrics against the recency rule, rank tiers
whose hit rates are measured on past test windows (probabilities drift, see brain/03_EVIDENCE.md),
and the three refusal rules (< 2 orders, insufficient history, model loses to recency)."""
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.engine import HORIZON, backtest, default_origins, features, fit, predict, top_k_hit

TIERS = ('high', 'medium', 'low')
HIGH, MEDIUM = 0.2, 0.5  # high = top 20% (same cut as the audited top-20% hit rate), medium = 20-50%
MIN_WINDOWS = 2
MIN_TEST_CUSTOMERS = 50  # ponytail: fixed floor; AUC on fewer customers is mostly noise


def window_ok(inv, origin, horizon=HORIZON):
    """Can this backtest window be formed from the file? Returns (ok, reason)."""
    start, day = inv['date'].min(), pd.Timedelta(days=horizon)
    if origin - 3 * day < start + day:
        return False, f'{origin.date()}: needs orders from {(origin - 4 * day).date()}, file starts {start.date()}'
    te = features(inv, origin, horizon)
    if len(te) < MIN_TEST_CUSTOMERS:
        return False, f'{origin.date()}: {len(te)} customers with 2+ orders, need {MIN_TEST_CUSTOMERS}'
    for o in [origin] + [origin - day * i for i in (1, 2, 3)]:
        if features(inv, o, horizon)['y'].nunique() < 2:
            return False, f'{o.date()}: everyone or no one reordered, nothing to learn or test'
    return True, ''


def choose_ranker(windows):
    """Rule 3: use the model only if it beats the recency rule on top-20% hit rate in every window (ties lose)."""
    lost = windows[windows['top20_model'] <= windows['top20_recency']]
    if lost.empty:
        return 'model', f'model beat the recency rule on top-20% hit rate in all {len(windows)} test windows'
    return 'recency', 'model did not beat the recency rule in: ' + ', '.join(
        f"{r.origin.date()} (model {r.top20_model:.0%} vs recency {r.top20_recency:.0%})" for r in lost.itertuples())


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
    origins = default_origins(inv, horizon)
    checks = [(o, *window_ok(inv, o, horizon)) for o in origins]
    usable = [o for o, ok, _ in checks if ok]
    skipped = [why for _, ok, why in checks if not ok]
    if len(usable) < MIN_WINDOWS:  # rule 2
        span = (inv['date'].max() - inv['date'].min()).days
        need = (inv['date'].max() - origins[MIN_WINDOWS - 1]).days + 4 * horizon
        return {'status': 'insufficient_data', 'skipped': skipped,
                'reason': f'only {len(usable)} of {len(origins)} backtest windows can be formed, need {MIN_WINDOWS}. '
                          f'The file covers {span} days; {MIN_WINDOWS} windows need at least {need} days. '
                          + '; '.join(skipped)}
    runs = backtest(inv, horizon, usable)
    windows = pd.DataFrame([{'origin': r['origin'], **window_metrics(r['y'], r['p'], r['s_recency'])}
                            for r in runs])
    tiers = pd.DataFrame([row for r in runs for ranker, s in (('model', r['p']), ('recency', r['s_recency']))
                          for row in _tier_rows(r['origin'], ranker, r['y'], s)])
    tiers['hit_rate'] = tiers['hits'] / tiers['n']
    ranker, why = choose_ranker(windows)  # rule 3
    return {'status': 'ok', 'windows': windows, 'tiers': tiers, 'skipped': skipped,
            'ranker': ranker, 'ranker_reason': why}


def tier_track_record(audit, ranker):
    """Per tier, across past test windows: min / max / pooled share who ordered within the horizon."""
    t = audit['tiers'][audit['tiers']['ranker'] == ranker]
    g = t.groupby('tier')
    rec = pd.DataFrame({'windows': g.size(), 'min': g['hit_rate'].min(), 'max': g['hit_rate'].max(),
                        'pooled': g['hits'].sum() / g['n'].sum()}).loc[list(TIERS)]
    b = audit['windows']['base_rate']
    rec.attrs['base_rate'] = (b.min(), b.max())
    return rec


def compare_tiers(model_rec, recency_rec):
    """One sentence from the pooled tier hit rates (tier_track_record of each ranker). Compared at whole percents."""
    pct = lambda x: int(round(x * 100))  # noqa: E731
    parts = []
    for t in ('high', 'medium'):
        m, r = pct(model_rec.loc[t, 'pooled']), pct(recency_rec.loc[t, 'pooled'])
        if m > r:
            parts.append(f'in the {t} tier the model found more customers who ordered again ({m}% vs {r}% for the recency rule)')
        elif r > m:
            parts.append(f'in the {t} tier the recency rule found more ({r}% vs {m}% for the model)')
        else:
            parts.append(f'in the {t} tier both found {m}%')
    m, r = pct(model_rec.loc['low', 'pooled']), pct(recency_rec.loc['low', 'pooled'])
    if m < r:
        parts.append(f'the model left fewer buyers in its low tier ({m}% vs {r}%)')
    elif r < m:
        parts.append(f'the recency rule left fewer buyers in its low tier ({r}% vs {m}%)')
    else:
        parts.append(f'both left {m}% buyers in the low tier')
    return 'Pooled over the test windows: ' + '; '.join(parts) + '.'


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
    counts = inv[inv['date'] < origin].groupby('customer_id').size()
    ones = counts[counts < 2]  # rule 1
    not_scored = pd.DataFrame({'customer_id': ones.index, 'n_orders': ones.values,
                               'reason': 'only 1 order in the file; need at least 2'})
    return {'ranker': ranker, 'scored': scored.sort_values('rank').reset_index(drop=True), 'not_scored': not_scored}


def recommend(inv, horizon=HORIZON):
    """Audit first. Score only if the audit can be trusted, with the ranker it chose."""
    a = run_audit(inv, horizon)
    if a['status'] != 'ok':
        return {'audit': a}
    return {'audit': a, 'track_record': tier_track_record(a, a['ranker']), **score_now(inv, a['ranker'], horizon)}
