"""Radar geometry and the generated takeaway sentences (presentation only)."""
import math

import pandas as pd

from app.charts import (R_CAP, R_LAPSED, holdout_chart, holdout_takeaway, radar_chart, radar_frame, radar_takeaway,
                        window_bars, window_takeaway)

T = pd.Timestamp


def _scored():
    return pd.DataFrame({
        'customer_id': ['a', 'b', 'c', 'd', 'e'],
        'tier': ['high', 'medium', 'low', 'high', 'low'],
        'recency': [10, 30, 200, 400, 50],
        'gap': [20.0, 20.0, 20.0, 30.0, None],
        'intent': ['not_due', 'due', 'overdue', 'lapsed', 'overdue'],
        'last_order': [T('2024-12-01')] * 5})


def test_radar_radius_and_sector():
    f = radar_frame(_scored()).set_index('customer')
    r = (f['x'] ** 2 + f['y'] ** 2) ** 0.5
    assert math.isclose(r['a'], 0.5) and math.isclose(r['b'], 1.5)       # days / usual gap
    assert math.isclose(r['c'], R_CAP)                                     # 10x the gap is capped at 3
    assert R_LAPSED[0] <= r['d'] <= R_LAPSED[1]                            # lapsed: outer band regardless of ratio
    assert math.isclose(r['e'], R_CAP)                                     # unknown gap sits at the cap
    angle = {c: math.degrees(math.atan2(f.loc[c, 'x'], f.loc[c, 'y'])) % 360 for c in f.index}
    assert 0 < angle['a'] < 120 and 120 < angle['b'] < 240 and 240 < angle['c'] < 360   # tier sectors
    assert radar_frame(_scored()).equals(radar_frame(_scored()))           # deterministic placement
    assert set(f['group']) == {'Not due yet', 'Due now', 'Slipping', 'Lapsed'}
    radar_chart(radar_frame(_scored())).to_dict()


def test_takeaways_follow_the_numbers():
    assert radar_takeaway({'due': 26, 'overdue': 124, 'lapsed': 15, 'not_due': 63}, 4).startswith(
        '26 customers are due now and 124 are slipping')
    w = pd.DataFrame({'origin': [T('2024-11-05'), T('2024-08-06'), T('2024-05-07')],
                      'top20_model': [0.9, 0.857, 0.967], 'top20_recency': [0.8, 0.857, 0.967],
                      'base_rate': [0.5, 0.56, 0.67]})
    assert window_takeaway(w, 'recency') == ('The model and the simple rule tied in 2 of 3 windows, and the model '
                                             'did better in 1, so we use the simple rule.')
    w2 = w.assign(top20_recency=[0.7, 0.8, 0.9])
    assert window_takeaway(w2, 'model').startswith('The model beat the simple rule in all 3 windows, by 6 to 20')
    window_bars(w).to_dict()
    h = pd.DataFrame({'window': ['2011-10-14', '2011-04-15'], 'diff': [0.229, 0.062], 'ci_low': [0.157, -0.023],
                      'ci_high': [0.314, 0.164]})
    assert holdout_takeaway(h) == ('On customers the model never saw, its lead is clear in Oct 2011. In Apr 2011 '
                                   'the interval crosses zero, so that window is not conclusive.')
    holdout_chart(h).to_dict()
