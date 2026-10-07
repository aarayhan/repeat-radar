"""Screen 3: how often this was right (model vs simple rule per test window, tiers, refusal checks)."""
import pandas as pd
import streamlit as st

from app.audit import compare_tiers
from app.charts import day_label, window_bars, window_takeaway
from app.screens.common import confirmed_result, pct, plain, takeaway


def screen_audit():
    st.markdown('## How often this was right')
    r = confirmed_result('see how often this was right')
    if r is None:
        return
    a, w = r['audit'], r['audit']['windows']
    if r['ranker'] == 'recency':
        st.markdown('<div class="rr-panel"><h3>Why we did not use the model</h3><p>The model was not better than '
                    'the simple rule on your data, so we use the simple rule.</p></div>', unsafe_allow_html=True)
    st.markdown('### The model and the simple rule, test by test')
    st.altair_chart(window_bars(w), width='stretch', theme=None)
    takeaway(window_takeaway(w, r['ranker']))
    st.caption('Bars: share of the top 20% of each list who ordered again within 8 weeks. Dashed line: the same '
               'share among all customers (the base rate).')

    st.markdown('### Each tier compared')
    m, rr = r['records']['model'], r['records']['recency']
    fmt = lambda row: f"{pct(row['pooled'])} ({pct(row['min'])} to {pct(row['max'])})"  # noqa: E731
    st.dataframe(pd.DataFrame({'Tier': list(m.index), 'Model': [fmt(x) for _, x in m.iterrows()],
                               'Simple rule': [fmt(x) for _, x in rr.iterrows()]}),
                 hide_index=True, width='stretch')
    st.write(plain(compare_tiers(m, rr)))

    st.markdown('### Checks that can stop a prediction')
    n1 = len(r['not_scored'])
    st.write(f"1. Fewer than 2 orders: {'triggered' if n1 else 'not triggered'}"
             + (f', {n1:,} customers not scored.' if n1 else '.'))
    st.write('2. Too little history (each test window needs 50 or more customers with 2+ earlier orders, and at least '
             '2 windows are needed): not triggered'
             + (f" (windows dropped: {plain('; '.join(a['skipped']))})." if a['skipped'] else '.'))
    st.write('3. The model must beat the simple rule in every window: '
             + ('triggered, using the simple rule' if r['ranker'] == 'recency' else 'not triggered')
             + f" ({plain(a['ranker_reason'])}).")

    with st.expander('How this is calculated'):
        st.dataframe(pd.DataFrame({
            'Test window starts': w['origin'].map(day_label), 'Customers': w['n'],
            'Base rate': w['base_rate'].map(pct),
            'AUC model': w['auc_model'].round(3), 'AUC recency': w['auc_recency'].round(3),
            'Top-20% hit model': w['top20_model'].map(pct), 'Top-20% hit recency': w['top20_recency'].map(pct),
        }), hide_index=True, width='stretch')
        st.caption('Each test window hides the last 8 weeks of a past point in your file, ranks customers with '
                   'only the data before it, then checks who really ordered. Base rate: share of all scored '
                   'customers who ordered again. Top-20% hit: the same share among the top 20% of each ranking. '
                   'AUC: how well each ranking separates buyers from non-buyers (0.5 is chance). Tier shares are '
                   'pooled over the windows (lowest to highest window in brackets).')
