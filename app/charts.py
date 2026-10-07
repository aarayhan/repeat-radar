"""Charts (Altair) and the one-sentence takeaways under them. Presentation only: every number comes from app/ code;
this module only arranges and words it."""
import hashlib
import math
import re

import altair as alt
import pandas as pd

INK, GRID, MUTED = '#14213D', '#C3CCD6', '#5C6B7A'
COLORS = {'due': '#0E9F8E', 'overdue': '#D99A00', 'lapsed': '#B54A3C', 'not_due': '#9AA5B1'}
GROUP_LABEL = {'due': 'Due now', 'overdue': 'Slipping', 'lapsed': 'Lapsed', 'not_due': 'Not due yet'}
METHOD_COLORS = {'Model': INK, 'Simple rule': '#8D99AE'}
SECTORS = ('high', 'medium', 'low')          # 120 degrees each, clockwise from the top
R_CAP = 3.0                                    # days / usual gap is capped at 3 on the radar
R_LAPSED = (3.15, 3.55)                        # lapsed customers (over 365 days) sit in this outer band
R_EDGE = 4.05
FONT = 'Archivo'
ISO_DATE = re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)')


def _unit(value, salt):
    """Deterministic number in [0, 1) from a customer id."""
    return int(hashlib.sha256(f'{salt}:{value}'.encode()).hexdigest()[:8], 16) / 0x100000000


def _xy(r, degrees):
    a = math.radians(degrees)
    return r * math.sin(a), r * math.cos(a)


def radar_frame(scored):
    """One row per customer: x, y on the radar plus the tooltip fields.
    scored needs customer_id, tier, recency, gap (usual gap in days, may be empty), intent, last_order."""
    rows = []
    for c in scored.itertuples():
        gap = None if pd.isna(c.gap) else int(c.gap)
        if c.intent == 'lapsed':
            r = R_LAPSED[0] + (R_LAPSED[1] - R_LAPSED[0]) * _unit(c.customer_id, 'band')
        else:
            r = R_CAP if not gap else min(c.recency / gap, R_CAP)
        deg = 120 * (SECTORS.index(c.tier) + 0.08 + 0.84 * _unit(c.customer_id, 'angle'))
        x, y = _xy(r, deg)
        rows.append({'x': x, 'y': y, 'customer': str(c.customer_id), 'tier': c.tier.capitalize(),
                     'last_order': day_label(c.last_order),
                     'usual_gap': f'{gap} days' if gap is not None else 'unknown',
                     'group': GROUP_LABEL[c.intent],
                     'reason': f'Last order {int(c.recency)} days ago; usual gap '
                               f"{f'{gap} days' if gap is not None else 'unknown'}"})
    return pd.DataFrame(rows)


def _guides():
    rings = pd.DataFrame([{'ring': name, 'i': i, 'x': _xy(r, d)[0], 'y': _xy(r, d)[1]}
                          for r, name in ((0.8, 'a'), (1.5, 'b'), (R_CAP + 0.075, 'c'))
                          for i, d in enumerate(range(0, 361, 3))])
    spokes = pd.DataFrame([{'spoke': s, 'i': i, 'x': _xy(r, s)[0], 'y': _xy(r, s)[1]}
                           for s in (0, 120, 240) for i, r in enumerate((0.0, R_EDGE - 0.25))])
    ring_text = pd.DataFrame([{'x': _xy(r, 2)[0] + 0.06, 'y': _xy(r, 2)[1], 'text': t} for r, t in   # on the empty spoke
                              ((0.8, 'x0.8'), (1.5, 'x1.5'), (R_CAP + 0.075, 'over a year'))])
    sector_text = pd.DataFrame([{'x': _xy(R_EDGE - 0.05, d)[0], 'y': _xy(R_EDGE - 0.05, d)[1], 'text': t}
                                for d, t in ((60, 'High tier'), (180, 'Medium tier'), (300, 'Low tier'))])
    return rings, spokes, ring_text, sector_text


def radar_chart(frame, height=560, selectable=True):
    """Radar as wide as its container: distance = days since last order / usual gap (capped at 3, lapsed in the
    outer band), sector = tier, color = next step. The scale domains follow the chart's width and height, so the
    rings stay round at any width. Click selection named 'pick' on the customer field."""
    lim = R_EDGE + 0.15
    wide, tall = f'{lim} * max(1, width / height)', f'{lim} * max(1, height / width)'
    x = alt.X('x:Q', scale=alt.Scale(domain={'expr': f'[-{wide}, {wide}]'}), axis=None)
    y = alt.Y('y:Q', scale=alt.Scale(domain={'expr': f'[-{tall}, {tall}]'}), axis=None)
    rings, spokes, ring_text, sector_text = _guides()
    groups = list(GROUP_LABEL.values())
    layers = [
        alt.Chart(rings).mark_line(color=GRID, strokeDash=[4, 3], strokeWidth=1).encode(x, y, detail='ring:N',
                                                                                          order='i:Q'),
        alt.Chart(spokes).mark_line(color=GRID, strokeWidth=1).encode(x, y, detail='spoke:N', order='i:Q'),
        alt.Chart(ring_text).mark_text(align='left', fontSize=10, color=MUTED).encode(x, y, text='text:N'),
        alt.Chart(sector_text).mark_text(fontSize=14, fontWeight=700, color=INK).encode(x, y, text='text:N'),
    ]
    points = alt.Chart(frame).mark_circle(size=95, opacity=0.9, stroke='white', strokeWidth=0.7).encode(
        x, y,
        color=alt.Color('group:N', scale=alt.Scale(domain=groups, range=[COLORS[k] for k in GROUP_LABEL]),
                        legend=None),     # the legend is drawn under the chart by the app
        tooltip=[alt.Tooltip('customer:N', title='Customer'), alt.Tooltip('tier:N', title='Tier'),
                 alt.Tooltip('last_order:N', title='Last order'), alt.Tooltip('usual_gap:N', title='Usual gap'),
                 alt.Tooltip('reason:N', title='Reason'), alt.Tooltip('group:N', title='Next step')])
    if selectable:
        points = points.add_params(alt.selection_point(name='pick', fields=['customer'], on='click'))
    return (alt.layer(*layers, points).properties(width='container', height=height)
            .configure_view(stroke=None).configure(font=FONT, background='transparent'))


def radar_takeaway(counts, due_high):
    """counts: intent -> number of customers. due_high: due customers in the high tier."""
    due, slip, lapsed, wait = (counts.get(k, 0) for k in ('due', 'overdue', 'lapsed', 'not_due'))
    return (f'{due} customers are due now and {slip} are slipping; {lapsed} have not ordered for over a year, and '
            f'{wait} are not due yet. {due_high} of the {due} due customers are in the high tier.')


def day_label(d):
    """The one date format on screen: 15 Apr 2011."""
    d = pd.Timestamp(d)
    return f'{d.day} {d:%b %Y}'


def show_dates(text):
    """Display only: ISO dates inside a text (audit reasons, explanations) in the on-screen format."""
    return ISO_DATE.sub(lambda m: day_label(m.group(0)), text)


window_label = day_label


def shown_percents(m, r):
    """(model, simple rule, decimals): the two hit rates in percent, rounded the way the bars show them. Whole
    percents, unless rounding would make different values look equal (or equal values look different)."""
    for d in (0, 1, 2):
        a, b = round(m * 100, d), round(r * 100, d)
        if (a == b) == (m == r):
            break
    return a, b, d


def window_bars(windows, height=260):
    """Grouped bars per test window: top-20% hit rate of the model and of the simple rule; base rate as a dashed
    line across the group. Drawn on a numeric x axis (window index) so the dashed line can span the group.
    windows needs origin, top20_model, top20_recency, base_rate."""
    w = windows.reset_index(drop=True)
    labels = [window_label(o) for o in w['origin']]
    rows = []
    for i, r in w.iterrows():
        a, b, d = shown_percents(r['top20_model'], r['top20_recency'])
        rows.append({'method': 'Model', 'value': r['top20_model'], 'label': f'{a:.{d}f}%', 'x': i - 0.41,
                     'x2': i - 0.02, 'mid': i - 0.215})
        rows.append({'method': 'Simple rule', 'value': r['top20_recency'], 'label': f'{b:.{d}f}%', 'x': i + 0.02,
                     'x2': i + 0.41, 'mid': i + 0.215})
    long = pd.DataFrame(rows)
    base = pd.DataFrame({'x': [i - 0.47 for i in range(len(w))], 'x2': [i + 0.47 for i in range(len(w))],
                         'base_rate': w['base_rate'], 'window': labels})
    axis = alt.Axis(values=list(range(len(w))), labelExpr=f"{labels}[datum.value]", title=None, grid=False,
                    labelFontSize=12, ticks=False, domain=False)
    xs = alt.Scale(domain=[-0.6, len(w) - 0.4])
    yv = alt.Y('value:Q', title='Share of the top 20% who ordered again', scale=alt.Scale(domain=[0, 1]),
               axis=alt.Axis(format='%', tickCount=5))
    color = alt.Color('method:N', scale=alt.Scale(domain=list(METHOD_COLORS), range=list(METHOD_COLORS.values())),
                      legend=alt.Legend(title=None, orient='top'))
    bars = alt.Chart(long).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        alt.X('x:Q', scale=xs, axis=axis), x2='x2:Q', y=yv, color=color,
        tooltip=[alt.Tooltip('method:N', title='Ranking'), alt.Tooltip('label:N', title='Top 20%')])
    text = alt.Chart(long).mark_text(dy=-7, fontSize=11, color=INK).encode(   # labels rounded in Python, as in
        alt.X('mid:Q', scale=xs), yv, text='label:N')                          # window_takeaway
    rule = alt.Chart(base).mark_rule(color=INK, strokeWidth=2, strokeDash=[6, 4]).encode(
        alt.X('x:Q', scale=xs), x2='x2:Q', y='base_rate:Q',
        tooltip=[alt.Tooltip('window:N', title='Window'), alt.Tooltip('base_rate:Q', title='Base rate', format='.0%')])
    return alt.layer(bars, rule, text).properties(height=height).configure(font=FONT, background='transparent')


def window_takeaway(windows, ranker):
    """The sentence under the window bars, from the real numbers, with the same rounding as the bar labels."""
    m, r = windows['top20_model'], windows['top20_recency']
    n, wins, ties, losses = len(windows), int((m > r).sum()), int((m == r).sum()), int((m < r).sum())
    if ranker == 'model':
        gap = [round(a - b, d) for a, b, d in map(shown_percents, m, r)]
        return (f'The model beat the simple rule in all {n} windows, by {min(gap):g} to {max(gap):g} points among '
                'the top 20% of customers, so we use the model.')
    parts = []
    if ties:
        parts.append(f'tied in {ties} of {n} windows')
    if losses:
        parts.append(f'the simple rule did better in {losses}')
    if wins:
        parts.append(f'the model did better in {wins}')
    return f"The model and the simple rule {', and '.join(parts)}, so we use the simple rule."


def holdout_chart(holdout, height=230):
    """One point per holdout window: model minus simple rule (points) with the 95% interval, and a zero line."""
    h = holdout.assign(window=holdout['window'].map(window_label), diff=holdout['diff'] * 100,
                       low=holdout['ci_low'] * 100, high=holdout['ci_high'] * 100,
                       result=['Not conclusive' if lo <= 0 <= hi else 'Model better'
                               for lo, hi in zip(holdout['ci_low'], holdout['ci_high'])])
    order = list(h['window'])
    y = alt.Y('window:N', sort=order, title=None, axis=alt.Axis(labelFontSize=12))
    color = alt.Color('result:N', scale=alt.Scale(domain=['Model better', 'Not conclusive'],
                                                  range=[COLORS['due'], COLORS['overdue']]),
                      legend=alt.Legend(title=None, orient='top'))
    xq = alt.X('low:Q', title='Model minus simple rule, points (95% interval)')
    zero = alt.Chart(pd.DataFrame({'z': [0]})).mark_rule(color=INK, strokeWidth=1.5).encode(x='z:Q')
    bars = alt.Chart(h).mark_rule(strokeWidth=3).encode(xq, x2='high:Q', y=y, color=color)
    dots = alt.Chart(h).mark_circle(size=110, opacity=1).encode(
        alt.X('diff:Q'), y, color=color,
        tooltip=[alt.Tooltip('window:N', title='Window'), alt.Tooltip('diff:Q', title='Difference', format='+.1f'),
                 alt.Tooltip('low:Q', title='Interval from', format='+.1f'),
                 alt.Tooltip('high:Q', title='Interval to', format='+.1f')])
    return alt.layer(zero, bars, dots).properties(height=height).configure(font=FONT, background='transparent')


def holdout_takeaway(holdout):
    clear = [window_label(r.window) for r in holdout.itertuples() if r.ci_low > 0]
    unclear = [window_label(r.window) for r in holdout.itertuples() if r.ci_low <= 0 <= r.ci_high]
    text = f"On customers the model never saw, its lead is clear in {' and '.join(clear)}." if clear else ''
    if unclear:
        text += (f" In {' and '.join(unclear)} the interval crosses zero, so that window is not conclusive.")
    return text.strip()
