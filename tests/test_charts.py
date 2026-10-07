"""Radar geometry and the generated takeaway sentences (presentation only)."""
import math

import pandas as pd

from app.charts import (R_CAP, R_LAPSED, day_label, holdout_chart, holdout_takeaway, radar_chart, radar_frame,
                        radar_takeaway, show_dates, window_bars, window_takeaway)

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
    w = pd.DataFrame({'origin': [T('2024-11-05'), T('2024-08-06'), T('2024-05-07')], 'n': [50, 35, 150],
                      'top20_model': [0.9, 0.857, 0.967], 'top20_recency': [0.8, 0.857, 0.967],
                      'base_rate': [0.5, 0.56, 0.67]})
    assert window_takeaway(w, 'recency') == ('The model and the simple rule tied in 2 of 3 windows, and the model '
                                             'did better in 1, so we use the simple rule.')
    w2 = w.assign(top20_recency=[0.7, 0.8, 0.9])
    assert window_takeaway(w2, 'model').startswith('The model beat the simple rule in all 3 windows, by 6 to 20')
    window_bars(w).to_dict()
    h = pd.DataFrame({'window': ['2011-10-14', '2011-04-15'], 'diff': [0.229, 0.062], 'ci_low': [0.157, -0.023],
                      'ci_high': [0.314, 0.164]})
    assert holdout_takeaway(h) == ('On customers the model never saw, its lead is clear in 14 Oct 2011. In 15 Apr 2011 '
                                   'the interval crosses zero, so that window is not conclusive.')
    holdout_chart(h).to_dict()


def _bar_rows(chart):
    """{(window index, method): data row} of the bar labels as drawn on the chart."""
    rows = [r for d in chart.to_dict()['datasets'].values() for r in d if 'label' in r]
    return {(round(r['mid']), r['method']): r for r in rows}


def _bar_labels(chart):
    return {key: r['label'] for key, r in _bar_rows(chart).items()}


def test_bar_labels_and_sentence_agree():
    o = [T('2024-11-05'), T('2024-08-06'), T('2024-05-07')]
    tied = pd.DataFrame({'origin': o, 'n': [209, 179, 151],                          # the Indonesian sample
                         'top20_model': [37 / 41, 30 / 35, 29 / 30], 'top20_recency': [33 / 41, 30 / 35, 29 / 30],
                         'base_rate': [0.5, 0.56, 0.67]})
    rows = _bar_rows(window_bars(tied))
    shown = {key: r['text'].split('\n') for key, r in rows.items()}       # two lines: the rate over the count
    assert [shown[i, 'Model'] for i in range(3)] == [['90%', '(37 of 41)'], ['86%', '(30 of 35)'],
                                                     ['97%', '(29 of 30)']]
    assert [shown[i, 'Simple rule'] for i in range(3)] == [['80%', '(33 of 41)'], ['86%', '(30 of 35)'],
                                                           ['97%', '(29 of 30)']]     # ties: the same label
    assert window_takeaway(tied, 'recency').startswith('The model and the simple rule tied in 2 of 3 windows')
    # 0.8571 vs 0.8566 both round to 86%: not a tie in the logic, so the labels must differ (one decimal)
    close = tied.assign(top20_model=[0.8571, 0.865, 0.9], top20_recency=[0.8566, 0.774, 0.8])
    labels = _bar_labels(window_bars(close))
    assert labels[0, 'Model'] != labels[0, 'Simple rule']
    gaps = [float(labels[i, 'Model'][:-1]) - float(labels[i, 'Simple rule'][:-1]) for i in range(3)]
    text = window_takeaway(close, 'model')
    assert f'by {round(min(gaps), 2):g} to {round(max(gaps), 2):g} points' in text, (labels, text)


def test_one_date_format_on_screen():
    assert day_label('2011-04-05') == '5 Apr 2011' and day_label(T('2011-04-15 10:00')) == '15 Apr 2011'
    assert show_dates('2024-08-06 (model 86%); invoice NT-101126 on 2024-12-26') == \
        '6 Aug 2024 (model 86%); invoice NT-101126 on 26 Dec 2024'


def test_top20_size_is_the_cut_the_audit_uses():
    import numpy as np
    from app.charts import top20_size
    from app.engine import top_k_hit
    for n in (7, 35, 151, 179, 209):
        y = np.zeros(n, dtype=int)
        y[0] = 1                                    # one positive, ranked first: the audit's hit rate is 1 / k
        assert round(1 / top_k_hit(y, -np.arange(n, dtype=float))) == top20_size(n)
