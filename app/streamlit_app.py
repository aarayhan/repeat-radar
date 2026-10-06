"""Repeat Radar UI: 1. Upload and confirm columns, 2. Customers, 3. Audit.

Files are processed in memory only (never written to disk, never logged). All numbers come from app/ code.
"""
import hashlib
import io
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `streamlit run app/streamlit_app.py` puts app/ on the path, not the repo root
from app.audit import compare_tiers, recommend, tier_track_record  # noqa: E402
from app.engine import clean  # noqa: E402
from app.drafts import draft_facts, intents, llm_draft, usual_products  # noqa: E402
from app.explain import customer_facts, llm_explanation, template_message  # noqa: E402
from app.llm import OPTIONAL, REQUIRED, LLMUnavailable, client, validate_mapping  # noqa: E402
from app.mapping import check_values, propose_mapping  # noqa: E402

SAMPLES = {'Indonesian point of sale (synthetic)': 'kasir_indonesia.csv',
           'E-commerce (synthetic)': 'ecommerce.csv'}
SCREENS = ['1. Upload', '2. Customers', '3. Audit']
NONE = '(none)'
INTENT_LABEL = {'not_due': 'Not due yet', 'due': 'Due: restock reminder', 'overdue': 'Overdue: check in',
                'lapsed': 'Lapsed: re-introduce'}
pct = '{:.0%}'.format


# ---------- cached computation (keyed by the SHA-256 of the file content) ----------

@st.cache_data(show_spinner=False, max_entries=8)
def read_table(key, name, _data):
    if name.lower().endswith(('.xlsx', '.xls')):
        sheets = pd.read_excel(io.BytesIO(_data), sheet_name=None)
        first = next(iter(sheets.values()))
        same = [s for s in sheets.values() if list(s.columns) == list(first.columns)]
        raw, dropped = pd.concat(same, ignore_index=True), len(sheets) - len(same)
    else:
        raw, dropped = pd.read_csv(io.BytesIO(_data)), 0
    return raw.set_axis([str(c) for c in raw.columns], axis=1), dropped


@st.cache_data(show_spinner=False, max_entries=8)
def proposal(key, _raw):
    return propose_mapping(_raw)


@st.cache_data(show_spinner='Cleaning, backtesting and scoring...', max_entries=8)
def analyse(key, mapping_json, _raw):
    try:
        inv = clean(_raw, json.loads(mapping_json))
    except ValueError as e:  # refusals from date reading
        return {'error': str(e)}
    if inv.empty:
        return {'error': 'no usable order lines left after cleaning (returns, zero prices, missing customer or date)'}
    out = {'inv': inv, 'warnings': inv.attrs.get('warnings', []), **recommend(inv)}
    if out['audit']['status'] == 'ok':
        out['records'] = {r: tier_track_record(out['audit'], r) for r in ('model', 'recency')}
        out['scored'] = out['scored'].assign(intent=intents(inv, out['scored']))
    m = json.loads(mapping_json)
    if m.get('product'):   # products are only used for the facts of a draft
        lines = pd.DataFrame({'customer_id': _raw[m['customer_id']], 'invoice_id': _raw[m['invoice_id']],
                              'product': _raw[m['product']]}).dropna()
        out['lines'] = lines.assign(invoice_id=lines['invoice_id'].astype(str),
                                    product=lines['product'].astype(str).str.strip())
        out['catalogue'] = sorted(set(out['lines']['product']))
    return out


@st.cache_data(show_spinner='Writing a draft and checking it...', max_entries=256)
def verified_draft(key, facts_json, _catalogue):
    """LLM draft checked by code (app/drafts.py), template if no LLM or if it fails twice."""
    return llm_draft(json.loads(facts_json), llm_client(), _catalogue)


def llm_client():
    try:
        return client()
    except LLMUnavailable:
        return None


# ---------- screen 1: upload and mapping ----------

def current_file():
    """(name, bytes) of the chosen file, kept in session memory so it survives switching screens."""
    st.session_state.setdefault('upload_key', 0)
    up = st.file_uploader('Upload a sales export (CSV or XLSX)', type=['csv', 'xlsx'],
                          key=f"upload_{st.session_state['upload_key']}")
    if up is not None and st.session_state.get('file', (None,))[0] != up.name:
        st.session_state['file'] = (up.name, up.getvalue())
        st.session_state['is_sample'] = False
    c1, c2 = st.columns([3, 1])
    choice = c1.selectbox('Or try a sample file', list(SAMPLES), key='sample_choice')
    if c2.button('Use sample data', key='use_sample'):
        st.session_state['file'] = (SAMPLES[choice], (ROOT / 'app' / 'sample_data' / SAMPLES[choice]).read_bytes())
        st.session_state['is_sample'] = True
        st.session_state['upload_key'] += 1  # the next run shows an empty uploader
    return st.session_state.get('file')


def screen_upload():
    st.header('1. Upload')
    f = current_file()
    if f is None:
        st.info('Upload a file or pick a sample to begin.')
        return
    name, data = f
    key = hashlib.sha256(data).hexdigest()
    if st.session_state.get('is_sample'):
        st.info(f'Using **{name}**: synthetic sample data. Made-up customers, not a real business.')
    try:
        raw, dropped_sheets = read_table(key, name, data)
    except Exception as e:  # unreadable file
        st.error(f'Could not read {name}: {e}')
        return
    st.write(f'**{name}**: {len(raw):,} rows, {len(raw.columns)} columns.')
    if dropped_sheets:
        st.warning(f'{dropped_sheets} sheet(s) with different columns were ignored; only sheets shaped like the first are used.')

    columns = list(raw.columns)
    p = proposal(key, raw)
    src = {'llm': 'the LLM', 'rules': 'the built-in rules', None: 'nobody (please map by hand)'}[p['source']]
    st.subheader('Column mapping')
    st.write(f'Proposed by {src}.')
    if p['llm_error']:
        st.caption(f"LLM not used: {p['llm_error']}")
    st.caption('If an LLM key is configured, the column names and 3 sample rows are sent to the LLM provider.')

    start, choice = p['mapping'], 'default'
    if p['needs_choice']:   # LLM and rules disagree on a required field, or one leaves it empty: user must pick
        st.warning('The LLM and the built-in rules disagree on a required field (or one of them left it empty). '
                   'Check both and pick one to start from.')
        st.dataframe(pd.DataFrame({'Field': list(REQUIRED + OPTIONAL),
                                   'LLM': [str(p['llm'].get(f) or '') for f in REQUIRED + OPTIONAL],
                                   'Rules': [str(p['rules'].get(f) or '') for f in REQUIRED + OPTIONAL]}),
                     hide_index=True)
        choice = st.radio('Start from', ['LLM proposal', 'Rules proposal'], index=None, key=f'pick_{key[:12]}')
        start = {'LLM proposal': p['llm'], 'Rules proposal': p['rules'], None: {}}[choice]

    mapping = {}
    cols = st.columns(4)
    for i, field in enumerate(REQUIRED + OPTIONAL):
        guess = start.get(field)
        options = [NONE] + columns
        pick = cols[i % 4].selectbox(field + (' *' if field in REQUIRED else ''), options,
                                     index=options.index(guess) if guess in columns else 0,
                                     key=f'map_{field}_{key[:12]}_{choice}')
        mapping[field] = None if pick == NONE else pick
    try:
        validate_mapping(json.dumps(mapping), columns)
        problems = check_values(raw, mapping)
    except ValueError as e:
        problems = [str(e)]
    if choice is None:
        problems = ['Pick the LLM or the rules proposal above before confirming.']
    for msg in problems:
        st.error(msg)
    if st.button('Confirm mapping', key='confirm', disabled=bool(problems), type='primary'):
        st.session_state['confirmed'] = (key, json.dumps(mapping))
    conf = st.session_state.get('confirmed')
    if not conf or conf[0] != key:
        st.caption('Screens 2 and 3 unlock after the mapping is confirmed.')
        return
    if conf[1] != json.dumps(mapping):
        st.warning('The mapping changed since it was confirmed. Confirm again to use the new one.')
    result = analyse(key, conf[1], raw)
    if 'error' in result:
        st.error(f"File refused: {result['error']}")
        return
    for w in result['warnings']:
        st.warning(w)
    inv = result['inv']
    st.success(f"Mapping confirmed. {len(inv):,} invoices from {inv['customer_id'].nunique():,} customers, "
               f"{inv['date'].min():%Y-%m-%d} to {inv['date'].max():%Y-%m-%d}. Open screen 2 in the sidebar.")
    if result['audit']['status'] != 'ok':
        st.warning(f"Not scored: {result['audit']['reason']}")


def confirmed_result():
    """Result for the confirmed mapping of the current file, or None (screen locked or refused)."""
    f, conf = st.session_state.get('file'), st.session_state.get('confirmed')
    if not f or not conf or conf[0] != hashlib.sha256(f[1]).hexdigest():
        st.info('Locked. Upload a file and confirm the column mapping on screen 1 first.')
        return None
    raw, _ = read_table(conf[0], f[0], f[1])
    result = analyse(conf[0], conf[1], raw)
    if 'error' in result:
        st.error(f"File refused: {result['error']}")
        return None
    if result['audit']['status'] != 'ok':
        st.warning(f"Not scored: {result['audit']['reason']}")
        return None
    return result


# ---------- screen 2: customers ----------

def screen_customers():
    st.header('2. Customers')
    r = confirmed_result()
    if r is None:
        return
    a = r['audit']
    if r['ranker'] == 'model':
        st.write(f"**Method: model** (logistic regression on order history). Why: {a['ranker_reason']}.")
    else:
        st.write(f"**Method: recency rule** (most recent buyers first). Why: {a['ranker_reason']}.")

    rec = r['track_record']
    lo, hi = rec.attrs['base_rate']
    st.write(f"Measured on {int(rec['windows'].iloc[0])} past test windows: share of customers in each tier who "
             f"ordered again within 8 weeks (all scored customers: {pct(lo)} to {pct(hi)}).")
    for col, (tier, row) in zip(st.columns(3), rec.iterrows()):
        col.metric(f'{tier.capitalize()} tier', f"{pct(row['min'])} to {pct(row['max'])}",
                   help=f"Pooled over the windows: {pct(row['pooled'])}")
    st.caption('These are measured hit rates of each tier in the past, not a probability for any one customer.')

    inv, s = r['inv'], r['scored']
    as_of = inv['date'].max() + pd.Timedelta(days=1)          # the same origin score_now uses for 'recency'
    st.write(f'Counted as of {as_of.day} {as_of:%b %Y}, the day after the last order in your file.')
    st.dataframe(pd.DataFrame({'Customer': s['customer_id'].astype(str), 'Tier': s['tier'],
                               'Last order': s['last_order'].dt.strftime('%Y-%m-%d'), 'Orders': s['n_orders'],
                               'Days since last order': s['recency'],
                               'Next step': s['intent'].map(INTENT_LABEL)}),
                 hide_index=True, width='stretch')
    for reason, n in r['not_scored'].groupby('reason').size().items():
        st.write(f'**{n:,} customers not scored**: {reason}.')

    st.subheader('Why this customer, and a draft message')
    cust = st.selectbox('Customer', list(s['customer_id']), format_func=str, key='customer')
    lang = st.radio('Message language', ['English', 'Indonesian'], horizontal=True, key='msg_lang')
    row = s[s['customer_id'] == cust].iloc[0]
    orders = inv[inv['customer_id'] == cust]
    facts = customer_facts(orders, row['tier'], row['recency'])
    text, source = llm_explanation(facts, 'en', llm_client())
    st.write(text)
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
        d = verified_draft(st.session_state['confirmed'][0], json.dumps(dfacts), r.get('catalogue', ()))
        msg, msg_source = d['text'], d['source']
    else:
        msg, msg_source = template_message(facts, 'id')
    st.text_area('Draft message', msg, key=f'msg_{cust}_{lang}')
    st.caption(f'Message source: {msg_source}')
    if msg_source != 'template':
        st.caption('Checked by code: products and dates match this customer\'s facts, no duration is written, and no '
                   'blocked promise (discount, free shipping, stock, deadline, drop by...) appears. The check cannot '
                   'catch every claim, so read it before sending.')


# ---------- screen 3: audit ----------

def screen_audit():
    st.header('3. Audit')
    r = confirmed_result()
    if r is None:
        return
    a, w = r['audit'], r['audit']['windows']
    st.subheader('Each test window: model vs recency rule')
    st.dataframe(pd.DataFrame({
        'Test window starts': w['origin'].dt.strftime('%Y-%m-%d'), 'Customers': w['n'],
        'Base rate': w['base_rate'].map(pct),
        'AUC model': w['auc_model'].round(3), 'AUC recency': w['auc_recency'].round(3),
        'Top-20% hit model': w['top20_model'].map(pct), 'Top-20% hit recency': w['top20_recency'].map(pct),
    }), hide_index=True, width='stretch')
    st.caption('Base rate: share of all scored customers who ordered again within 8 weeks. '
               'Top-20% hit: the same share among the top 20% of each ranking.')

    st.subheader('Each tier: model vs recency rule')
    m, rr = r['records']['model'], r['records']['recency']
    fmt = lambda row: f"{pct(row['pooled'])} ({pct(row['min'])} to {pct(row['max'])})"  # noqa: E731
    st.dataframe(pd.DataFrame({'Tier': list(m.index), 'Model': [fmt(x) for _, x in m.iterrows()],
                               'Recency rule': [fmt(x) for _, x in rr.iterrows()]}),
                 hide_index=True, width='stretch')
    st.caption('Pooled share who ordered again within 8 weeks (lowest to highest test window).')
    st.write(compare_tiers(m, rr))

    st.subheader('Refusal rules')
    n1 = len(r['not_scored'])
    st.write(f"1. Fewer than 2 orders: {'triggered' if n1 else 'not triggered'}"
             + (f', {n1:,} customers not scored.' if n1 else '.'))
    st.write('2. Too little history: not triggered'
             + (f" (windows dropped: {'; '.join(a['skipped'])})." if a['skipped'] else '.'))
    st.write('3. Model must beat the recency rule in every window: '
             + ('triggered, using the recency rule' if r['ranker'] == 'recency' else 'not triggered')
             + f" ({a['ranker_reason']}).")


# ---------- main ----------

def main():
    st.set_page_config(page_title='Repeat Radar', layout='wide')
    st.title('Repeat Radar')
    st.caption('Which customers are likely to reorder within 8 weeks, and how often that ranking was right on your '
               'own past data. ForgeHacks 2026, AI + Business.')
    screen = st.sidebar.radio('Step', SCREENS, key='screen')
    try:
        {SCREENS[0]: screen_upload, SCREENS[1]: screen_customers, SCREENS[2]: screen_audit}[screen]()
    except Exception as e:  # never show a traceback
        st.error(f'Something went wrong: {type(e).__name__}: {e}')


main()
