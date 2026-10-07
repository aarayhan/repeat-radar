"""Screen 4: results on real shop data (read-only, from app/evidence_uci.json)."""
import json

import pandas as pd
import streamlit as st

from app.charts import day_label, holdout_chart, holdout_takeaway
from app.screens.common import ROOT, takeaway

EVIDENCE = ROOT / 'app' / 'evidence_uci.json'


def screen_evidence():
    """Read-only results of our own runs on the public UCI dataset (app/evidence_uci.json, built by
    scripts/build_evidence.py). No raw data is shipped with the app."""
    st.markdown('## Results on real shop data')
    try:
        e = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        st.error('The evidence file is missing. Run python scripts/build_evidence.py locally.')
        return
    d = e['dataset']
    st.write(f"These are the results of our own tests on the public **{d['name']}** dataset: {d['description']} "
             f"{d['customers']:,} customers, {d['invoices_after_cleaning']:,} invoices after cleaning. "
             'This page is read-only; the demo samples elsewhere in the app are synthetic.')
    st.caption(f"Data: {d['name']}, {d['source']}, {d['url']}. Licensed {d['license']}; used with attribution, "
               'not modified except for the cleaning described in the repository.')
    pct1 = '{:.1%}'.format
    b, h = pd.DataFrame(e['backtest_all_customers']), pd.DataFrame(e['holdout'])

    st.markdown('### On customers the model never saw')
    st.altair_chart(holdout_chart(h), width='stretch', theme=None)
    takeaway(holdout_takeaway(h))
    st.caption('Each dot: how many more of the top 20% ordered again within 8 weeks with the model than with the '
               'simple rule, in percentage points. The line is the 95% interval; if it crosses zero, the win is '
               'not conclusive.')
    for r in h.itertuples():
        if r.ci_low <= 0 <= r.ci_high:
            st.warning(f"{day_label(r.window)}: the model's win is not conclusive (the interval includes zero).")

    st.markdown('### The details')
    with st.expander('Backtest on all customers: 3 test windows'):
        st.dataframe(pd.DataFrame({'Test window starts': b['window'].map(day_label), 'Customers': b['customers'],
                                   'Base rate': b['base_rate'].map(pct1), 'AUC model': b['auc_model'],
                                   'AUC recency': b['auc_recency'], 'Top-20% hit model': b['top20_model'].map(pct1),
                                   'Top-20% hit recency': b['top20_recency'].map(pct1)}),
                     hide_index=True, width='stretch')
        t = {k: pd.DataFrame(v) for k, v in e['tiers_all_customers'].items()}
        fmt = lambda r: f'{pct1(r.pooled)} ({pct1(r.min)} to {pct1(r.max)})'  # noqa: E731
        st.dataframe(pd.DataFrame({'Tier': t['model']['tier'],
                                   'Model, pooled (min to max)': [fmt(r) for r in t['model'].itertuples()],
                                   'Simple rule, pooled (min to max)': [fmt(r) for r in t['recency'].itertuples()]}),
                     hide_index=True, width='stretch')
    with st.expander('Locked holdout: 20% of customers, run once, with 95% bootstrap intervals'):
        st.dataframe(pd.DataFrame({'Test window starts': h['window'].map(day_label), 'Customers': h['customers'],
                                   'In top 20%': h['top20_customers'], 'Top-20% hit model': h['top20_model'].map(pct1),
                                   'Top-20% hit recency': h['top20_recency'].map(pct1),
                                   'Difference (points)': (h['diff'] * 100).round(1),
                                   '95% interval (points)': [f'{lo * 100:+.1f} to {hi * 100:+.1f}'
                                                             for lo, hi in zip(h['ci_low'], h['ci_high'])],
                                   'Verdict': h['verdict']}), hide_index=True, width='stretch')
    with st.expander('How well the predicted chances matched (calibration)'):
        st.dataframe(pd.DataFrame({'Test window starts': b['window'].map(day_label), 'ECE, all customers': b['ece'],
                                   'Brier, all customers': b['brier'], 'ECE, holdout': h['ece']}),
                     hide_index=True, width='stretch')
        st.caption('The predicted chances drift in the most recent window, so the app shows tier hit rates '
                   'instead of chances.')
    with st.expander('Column mapping test: UCI and two variants made from it'):
        st.dataframe(pd.DataFrame(e['mapping']).rename(columns={'file': 'File', 'rules': 'Built-in rules',
                                                                'llm': 'LLM'}), hide_index=True, width='stretch')
    with st.expander('Follow-up drafts'):
        st.dataframe(pd.DataFrame(e['drafts']).rename(columns={
            'run': 'Run', 'verifier': 'Checks', 'customers': 'Customers', 'first_try': 'Passed first try',
            'after_repair': 'Passed after repair', 'rejected': 'Rejected', 'good': 'Good', 'note': 'Note'}),
            hide_index=True, width='stretch')
        st.caption('Good means the code found every fact true and a usual product mentioned. It does not judge '
                   'tone; drafts are for you to edit before sending.')
    with st.expander('How this is calculated'):
        st.markdown('- **Holdout:** 20% of customers were set aside by a fixed hash before any design decision and '
                    'tested once, with the model trained only on the other 80%.\n'
                    '- **Interval:** 1,000 bootstrap resamples of the holdout customers in each window.\n'
                    '- **ECE:** average gap between predicted and observed reorder rates (0 is perfect). **AUC:** how '
                    'well a ranking separates buyers from non-buyers (0.5 is chance).\n'
                    '- **Reproduce locally** (needs the UCI file, which is not shipped):')
        st.code('\n'.join(e['reproduce']), language='bash')
        st.caption(f"Built from commit {e['built_from_commit']}.")
