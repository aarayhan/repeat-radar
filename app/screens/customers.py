"""Screen 2: who to contact this week (radar, tiers, lists, one customer's explanation and draft)."""
import json

import pandas as pd
import streamlit as st

from app.charts import day_label, radar_chart, radar_frame, radar_takeaway, show_dates
from app.drafts import draft_facts, usual_products
from app.explain import customer_facts, template_message
from app.screens.common import (cap_notice, confirmed_result, explanation, pct, plain, takeaway,
                                verified_draft)

GROUPS = [('due', 'Due now'), ('overdue', 'Slipping (overdue)'), ('lapsed', 'Lapsed'), ('not_due', 'Not due yet')]
TIER_ORDER = {'high': 0, 'medium': 1, 'low': 2}
INTENT_LABEL = {'not_due': 'Not due yet', 'due': 'Due: restock reminder', 'overdue': 'Overdue: check in',
                'lapsed': 'Lapsed: re-introduce'}
LEGEND_HTML = ('<div class="rr-legend">'
               "<p><b>Distance</b>: days since the last order divided by the customer's usual gap. Rings at x0.8 "
               'and x1.5; outer band: no order for over a year. The rings are simple rules, not validated.</p>'
               '<p><b>Color</b>: ' + ''.join(f'<span class="rr-dot" style="background:{c}"></span>{t} &nbsp; '
                                            for c, t in (('#0E9F8E', 'due now'), ('#D99A00', 'slipping'),
                                                         ('#B54A3C', 'lapsed'), ('#9AA5B1', 'not due yet')))
               + '</p><p><b>Sector</b>: tier from the ranking; high tier customers are the most likely to reorder. '
               'Click a dot to open the customer below.</p></div>')


def screen_customers():
    st.markdown('## Who to contact this week')
    r = confirmed_result('see your customers')
    if r is None:
        return
    a, rec, inv = r['audit'], r['track_record'], r['inv']
    s = r['scored'].assign(_tier=r['scored']['tier'].map(TIER_ORDER)).sort_values(['_tier', 'rank'])
    counts = s['intent'].value_counts()
    cards = st.columns(5)
    for col, (intent, label) in zip(cards, GROUPS):
        col.metric(label, f'{counts.get(intent, 0):,}')
    badge = ('<span class="rr-badge">The model</span>' if r['ranker'] == 'model'
             else '<span class="rr-badge rule">The simple rule</span>')
    cards[4].markdown(f'<p style="margin:.15rem 0 .35rem;color:#5C6B7A;font-size:.9rem">Ranked by</p>{badge}',
                      unsafe_allow_html=True)
    as_of = inv['date'].max() + pd.Timedelta(days=1)          # the same origin score_now uses for 'recency'
    st.markdown(f'Counted as of {day_label(as_of)}, the day after the last order in your file.')

    ids = {str(c): c for c in s['customer_id']}
    event = st.altair_chart(radar_chart(radar_frame(s)), width='stretch', theme=None, key='radar',
                            on_select='rerun', selection_mode='pick')
    st.markdown(LEGEND_HTML, unsafe_allow_html=True)
    picked = (event.get('selection', {}).get('pick') or [{}])[0].get('customer') if event else None
    if picked in ids and picked != st.session_state.get('radar_last'):   # a click on the radar picks the customer
        st.session_state['radar_last'] = picked
        st.session_state['customer'] = ids[picked]
    takeaway(radar_takeaway(counts.to_dict(), int(((s['intent'] == 'due') & (s['tier'] == 'high')).sum())))

    st.markdown('### How often each tier was right before')
    lo, hi = rec.attrs['base_rate']
    for col, (tier, row) in zip(st.columns(3), rec.iterrows()):
        col.metric(f'{tier.capitalize()} tier', f"{pct(row['min'])[:-1]}–{pct(row['max'])}",
                   help=f"Pooled over the windows: {pct(row['pooled'])}")
    st.caption(f"Share who ordered again within 8 weeks, in {int(rec['windows'].iloc[0])} past test windows "
               f'(all customers: {pct(lo)} to {pct(hi)}). Measured hit rates, not a probability for any one customer.')
    with st.expander('How this is calculated'):
        st.markdown(
            f"- **Ranking:** {'a model trained on earlier order history' if r['ranker'] == 'model' else 'most recent buyers first (the simple rule)'}. "
            f"Why: {plain(a['ranker_reason'])}.\n"
            '- **Tiers:** high = top 20% of the ranking, medium = next 30%, low = the rest.\n'
            "- **Next step:** days since the last order compared with the customer's usual gap. Not due below 0.8 x "
            'the gap, due from 0.8 to 1.5 x, slipping above 1.5 x, lapsed after 365 days. These are simple rules, '
            'not validated.\n'
            '- **Radar:** distance = days since the last order divided by the usual gap, capped at 3; lapsed '
            'customers sit in the outer band. The angle inside a sector only spreads the dots out.')

    st.markdown('### Customers by next step')
    order = []
    for tab, (intent, label) in zip(st.tabs([f'{label} ({counts.get(i, 0):,})' for i, label in GROUPS]), GROUPS):
        g = s[s['intent'] == intent]
        tab.dataframe(pd.DataFrame({'Customer': g['customer_id'].astype(str), 'Tier': g['tier'],
                                    'Last order': g['last_order'].map(day_label), 'Orders': g['n_orders'],
                                    'Days since last order': g['recency'],
                                    'Next step': g['intent'].map(INTENT_LABEL)}),
                      hide_index=True, width='stretch')
        order += list(g['customer_id'])
    for reason, n in r['not_scored'].groupby('reason').size().items():
        st.write(f'**{n:,} customers not scored**: {reason}.')

    st.markdown('### Why this customer, and what to send')
    cust = st.selectbox('Customer (or click a dot on the radar)', order, format_func=str, key='customer')
    lang = st.radio('Message language', ['English', 'Indonesian'], horizontal=True, key='msg_lang')
    row = s[s['customer_id'] == cust].iloc[0]
    orders = inv[inv['customer_id'] == cust]
    facts = customer_facts(orders, row['tier'], row['recency'])
    conf_key = st.session_state['confirmed'][0]
    text, source = explanation(conf_key, json.dumps(facts), f'explain:{cust}')
    st.write(show_dates(text))
    st.caption(f'Explanation source: {source}')
    lines = r.get('lines')
    products = usual_products(lines[lines['customer_id'] == cust]) if lines is not None else []
    dfacts = draft_facts(orders, products, cust, row['tier'], rec.loc[row['tier'], 'pooled'], row['recency'])
    gap = dfacts['typical_gap_days']
    st.write(f"**Reason (for you, not in the message):** last order {row['recency']} days ago, "
             f"usual gap {gap if gap is not None else 'unknown'} days, so: {INTENT_LABEL[dfacts['intent']]}.")
    if dfacts['intent'] == 'not_due':
        if row['tier'] == 'high':
            st.info('Likely to reorder on their own. No message needed yet.')
        st.info(f'Not due yet, usual gap is {gap} days.')
        return
    if lang == 'English':    # verified LLM drafts were evaluated in English only (docs/H2_REPORT.md section 9)
        d = verified_draft(conf_key, json.dumps(dfacts), f'draft:{cust}', r.get('catalogue', ()))
        msg, msg_source = d['text'], d['source']
    else:
        msg, msg_source = template_message(facts, 'id')
    st.markdown('**Draft message** (copy it, then edit before sending)')
    st.code(msg, language=None, wrap_lines=True)
    st.caption(f'Message source: {msg_source}')
    cap_notice()
    if msg_source != 'template':
        st.caption('Checked by code: products and dates match this customer\'s facts, no duration is written, and no '
                   'blocked promise (discount, free shipping, stock, deadline, drop by...) appears. The check cannot '
                   'catch every claim, so read it before sending.')
