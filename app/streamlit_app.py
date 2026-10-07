"""Repeat Radar UI: 1. Upload and confirm columns, 2. Customers, 3. Audit.

Files are processed in memory only (never written to disk, never logged). All numbers come from app/ code.
"""
import datetime
import hashlib
import html
import io
import json
import os
import sys
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `streamlit run app/streamlit_app.py` puts app/ on the path, not the repo root
from app.audit import compare_tiers, recommend, tier_track_record  # noqa: E402
from app.charts import (holdout_chart, holdout_takeaway, radar_chart, radar_frame,  # noqa: E402
                        radar_takeaway, window_bars, window_takeaway)
from app.engine import clean  # noqa: E402
from app.drafts import draft_facts, intents, llm_draft, typical_gap, usual_products  # noqa: E402
from app.explain import customer_facts, llm_explanation, template_message  # noqa: E402
from app.llm import OPTIONAL, REQUIRED, LLMUnavailable, client, validate_mapping  # noqa: E402
from app.mapping import check_values, propose_mapping  # noqa: E402

SAMPLES = {'Indonesian point of sale (synthetic)': 'kasir_indonesia.csv',
           'E-commerce (synthetic)': 'ecommerce.csv'}
SCREENS = ['1. Upload', '2. Customers', '3. Audit', '4. Evidence (UCI)']
TRUST_LINE = 'We do not just make predictions. We only make them when the data shows we can trust them.'
NO_AI_MESSAGE = 'AI suggestions are off right now, so the built-in rules were used.'
SAMPLE_NOTE = ('Synthetic sample. Results here show how the app works, not evidence. '
               'The evidence is on the Evidence page.')
EVIDENCE = ROOT / 'app' / 'evidence_uci.json'
GROUPS = [('due', 'Due now'), ('overdue', 'Slipping (overdue)'), ('lapsed', 'Lapsed'), ('not_due', 'Not due yet')]
TIER_ORDER = {'high': 0, 'medium': 1, 'low': 2}
NONE = '(none)'
DEFAULT_LLM_CAP = 20   # LLM requests per session (override with LLM_SESSION_CAP)
DEFAULT_LLM_DAILY_CAP = 500   # LLM requests per day for the whole app, in memory (override with LLM_DAILY_CAP)
SECRET_KEYS = ('FEATHERLESS_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'LLM_PROVIDER', 'LLM_MODEL',
               'LLM_SESSION_CAP', 'LLM_DAILY_CAP')
INTENT_LABEL = {'not_due': 'Not due yet', 'due': 'Due: restock reminder', 'overdue': 'Overdue: check in',
                'lapsed': 'Lapsed: re-introduce'}
pct = '{:.0%}'.format
CSS = (ROOT / 'app' / 'style.css').read_text(encoding='utf-8')
HERO_HTML = ('<div class="rr-hero"><div class="rr-sweep" aria-hidden="true"></div><div>'
             '<h1 class="rr-brand">Repeat Radar</h1>'
             f'<p class="rr-trust">{TRUST_LINE}</p>'
             '<p class="rr-lead">Upload a sales export and see which customers are likely to order again, '
             "how often that list was right before, and a message checked against each customer's own orders."
             '</p></div></div>')
LEGEND_HTML = ('<div class="rr-legend">'
               '<p><b>Distance from the center</b>: days since the last order, divided by the customer\'s usual '
               'gap between orders. Further out means later than usual.</p>'
               '<p><span class="rr-dot" style="background:#9AA5B1"></span>Inside the first ring: not due yet</p>'
               '<p><span class="rr-dot" style="background:#0E9F8E"></span>Between the rings: due now</p>'
               '<p><span class="rr-dot" style="background:#D99A00"></span>Beyond the second ring: slipping</p>'
               '<p><span class="rr-dot" style="background:#B54A3C"></span>Outer band: no order for over a year</p>'
               '<p><b>Sectors</b>: tier from the ranking. High tier customers are the most likely to reorder.</p>'
               '<p>The rings are simple rules, not validated. Hover a dot for details; click it to open the '
               'customer below.</p></div>')


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
def llm_proposal(key, _raw):
    """Proposal made while an LLM key is available. Entries where the LLM was not used are removed by proposal()."""
    return propose_mapping(_raw)


@st.cache_data(show_spinner=False, max_entries=8)
def rules_proposal(key, _raw):
    """Built-in rules only. Served only while no LLM can be used, so it is never reused once a key is available."""
    return propose_mapping(_raw, use_llm=False)


def proposal(key, raw):
    """(proposal, why the LLM was off: 'no_key', 'budget' or None). A proposal made without the LLM is never reused
    after the LLM becomes available: the two caches are separate, and an LLM attempt that fell back is not kept."""
    if llm_client() is None:
        return rules_proposal(key, raw), 'no_key'
    if not llm_allowed(f'map:{key}'):
        return rules_proposal(key, raw), 'budget'
    p = llm_proposal(key, raw)
    if p['llm'] is None:      # the LLM failed this time (for example an API error): do not keep the fallback
        llm_proposal.clear(key, raw)
    return p, None


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
        gaps = inv.groupby('customer_id')['date'].apply(typical_gap)     # usual gap, shown on the radar
        out['scored'] = out['scored'].assign(intent=intents(inv, out['scored']),
                                             gap=out['scored']['customer_id'].map(gaps))
    m = json.loads(mapping_json)
    if m.get('product'):   # products are only used for the facts of a draft
        lines = pd.DataFrame({'customer_id': _raw[m['customer_id']], 'invoice_id': _raw[m['invoice_id']],
                              'product': _raw[m['product']]}).dropna()
        out['lines'] = lines.assign(invoice_id=lines['invoice_id'].astype(str),
                                    product=lines['product'].astype(str).str.strip())
        out['catalogue'] = sorted(set(out['lines']['product']))
    return out


class _Watched:
    """Wraps an OpenAI-compatible client and records whether any call raised (provider error)."""
    def __init__(self, client):
        self.client, self.failed = client, False
        self.chat = self.completions = self

    def create(self, **kw):
        try:
            return self.client.chat.completions.create(**kw)
        except Exception:
            self.failed = True
            raise


@st.cache_data(show_spinner='Writing a draft and checking it...', max_entries=256)
def llm_draft_cached(key, facts_json, _catalogue):
    """LLM draft checked by code (app/drafts.py). Called only while a key is available; results made without a
    working LLM are removed again by verified_draft()."""
    c = llm_client()
    w = _Watched(c[0]) if c else None
    d = llm_draft(json.loads(facts_json), (w, c[1]) if c else None, _catalogue)
    return {**d, 'provider_error': c is None or w.failed}


def verified_draft(key, facts_json, request, catalogue):
    """LLM results and template fallbacks are never mixed up: templates are cheap and not cached, and an LLM-cache
    entry made after a provider error (or without a key) is dropped, so it is retried once the LLM works."""
    if llm_client() is None or not llm_allowed(request):
        return llm_draft(json.loads(facts_json), None)
    d = llm_draft_cached(key, facts_json, catalogue)
    if d['provider_error']:
        llm_draft_cached.clear(key, facts_json, catalogue)
    return d


@st.cache_data(show_spinner=False, max_entries=256)
def llm_explanation_cached(key, facts_json):
    """Same rule as llm_draft_cached, for the explanation."""
    c = llm_client()
    w = _Watched(c[0]) if c else None
    text, source = llm_explanation(json.loads(facts_json), 'en', (w, c[1]) if c else None)
    return {'text': text, 'source': source, 'provider_error': c is None or w.failed}


def explanation(key, facts_json, request):
    if llm_client() is None or not llm_allowed(request):
        return llm_explanation(json.loads(facts_json), 'en', None)
    r = llm_explanation_cached(key, facts_json)
    if r['provider_error']:
        llm_explanation_cached.clear(key, facts_json)
    return r['text'], r['source']


def llm_client():
    try:
        return client()
    except LLMUnavailable:
        return None


def secrets_to_env():
    """On Streamlit Community Cloud, keys come from st.secrets; locally, app/llm.py reads .env. Never in code."""
    try:
        for k in SECRET_KEYS:
            if k in st.secrets and not os.getenv(k):
                os.environ[k] = str(st.secrets[k])
    except Exception:   # no secrets.toml (local run): .env is used instead
        pass


@st.cache_resource
def daily_counter():
    """App-wide LLM request counter, shared by all sessions of this server process. In memory: resets on restart
    and when the server's date changes."""
    return {'lock': threading.Lock(), 'day': None, 'count': 0}


def llm_allowed(request):
    """Budgets for LLM requests, to protect the API key on a public deploy: per session (LLM_SESSION_CAP) and per
    day for the whole app (LLM_DAILY_CAP). Each distinct request (a file's mapping, a customer's explanation, a
    customer's draft) counts once per session; cached repeats do not count again."""
    used = st.session_state.setdefault('llm_requests', set())
    if request in used:
        return True
    cap = int(os.getenv('LLM_SESSION_CAP', DEFAULT_LLM_CAP))
    if len(used) >= cap:
        st.session_state['llm_cap_hit'] = cap
        return False
    daily_cap, c = int(os.getenv('LLM_DAILY_CAP', DEFAULT_LLM_DAILY_CAP)), daily_counter()
    with c['lock']:
        today = datetime.date.today().isoformat()
        if c['day'] != today:
            c['day'], c['count'] = today, 0
        if c['count'] >= daily_cap:
            st.session_state['llm_daily_hit'] = daily_cap
            return False
        c['count'] += 1
    used.add(request)
    return True


def cap_notice():
    if st.session_state.get('llm_cap_hit'):
        st.warning(f"LLM limit for this session reached ({st.session_state['llm_cap_hit']} requests). "
                   'The app now uses built-in rules and templates; everything else works as before.')
    if st.session_state.get('llm_daily_hit'):
        st.warning(f"Daily LLM limit for this app reached ({st.session_state['llm_daily_hit']} requests). "
                   'The app uses built-in rules and templates until the limit resets; everything else works.')


# ---------- screen 1: upload and mapping ----------

def load_sample(choice):
    st.session_state['file'] = (SAMPLES[choice], (ROOT / 'app' / 'sample_data' / SAMPLES[choice]).read_bytes())
    st.session_state['is_sample'] = True
    st.session_state['upload_key'] = st.session_state.get('upload_key', 0) + 1  # the next run shows an empty uploader


def current_file():
    """(name, bytes) of the chosen file, kept in session memory so it survives switching screens."""
    st.session_state.setdefault('upload_key', 0)
    up = st.file_uploader('Upload a sales export (CSV or XLSX)', type=['csv', 'xlsx'],
                          key=f"upload_{st.session_state['upload_key']}")
    if up is not None and st.session_state.get('file', (None,))[0] != up.name:
        st.session_state['file'] = (up.name, up.getvalue())
        st.session_state['is_sample'] = False
    c1, c2 = st.columns([3, 1], vertical_alignment='bottom')
    choice = c1.selectbox('Or try a sample file', list(SAMPLES), key='sample_choice')
    if c2.button('Use sample data', key='use_sample'):
        load_sample(choice)
    return st.session_state.get('file')


def screen_upload():
    st.markdown(HERO_HTML, unsafe_allow_html=True)
    if st.button('Try the demo', key='try_demo', type='primary'):
        load_sample('Indonesian point of sale (synthetic)')
    st.caption('The demo uses a synthetic sample from a made-up Indonesian shop.')
    st.markdown('### Or start with your own sales export')
    f = current_file()
    if f is None:
        st.info('Try the demo above, or upload your sales export (CSV or XLSX) to begin.')
        return
    name, data = f
    key = hashlib.sha256(data).hexdigest()
    if st.session_state.get('is_sample'):
        st.info(f'Using **{name}**, made-up customers. ' + SAMPLE_NOTE)
    try:
        raw, dropped_sheets = read_table(key, name, data)
    except Exception as e:  # unreadable file
        st.error(f'Could not read {name}: {e}')
        return
    st.write(f'**{name}**: {len(raw):,} rows, {len(raw.columns)} columns.')
    if dropped_sheets:
        st.warning(f'{dropped_sheets} sheet(s) with different columns were ignored; only sheets shaped like the first are used.')

    columns = list(raw.columns)
    p, llm_off = proposal(key, raw)
    cap_notice()
    src = {'llm': 'the LLM', 'rules': 'the built-in rules', None: 'nobody (please map by hand)'}[p['source']]
    st.markdown('### Check that the columns match')
    st.write(f'Proposed by {src}.')
    if llm_off == 'no_key':
        st.caption(NO_AI_MESSAGE)
    elif llm_off is None and p['llm_error']:
        st.caption(f"LLM not used: {p['llm_error']}")
    st.caption('With AI suggestions on, the column names and 3 sample rows are sent to the AI provider.')

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
        st.caption('Steps 2 and 3 unlock after you confirm the column mapping.')
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
               f"{inv['date'].min():%Y-%m-%d} to {inv['date'].max():%Y-%m-%d}. Next: open step 2, Customers, "
               'in the sidebar to see who to contact.')
    if result['audit']['status'] != 'ok':
        st.warning(f"Not scored: {result['audit']['reason']}")


def mapping_confirmed():
    f, conf = st.session_state.get('file'), st.session_state.get('confirmed')
    return bool(f and conf and conf[0] == hashlib.sha256(f[1]).hexdigest())


def confirmed_result(next_step):
    """Result for the confirmed mapping of the current file, or None (screen locked or refused)."""
    if not mapping_confirmed():
        st.info(f'Locked: confirm the column mapping on step 1 to {next_step}.')
        return None
    f, conf = st.session_state['file'], st.session_state['confirmed']
    if st.session_state.get('is_sample'):
        st.info(SAMPLE_NOTE)
    raw, _ = read_table(conf[0], f[0], f[1])
    result = analyse(conf[0], conf[1], raw)
    if 'error' in result:
        st.error(f"File refused: {result['error']}")
        return None
    if result['audit']['status'] != 'ok':
        st.warning(f"Not scored: {result['audit']['reason']}")
        return None
    return result


def plain(text):
    """Display wording only: the app calls the recency rule 'the simple rule'."""
    return text.replace('recency rule', 'simple rule').replace(' vs recency ', ' vs simple rule ')


def takeaway(text):
    st.markdown(f'<p class="rr-takeaway">{html.escape(text)}</p>', unsafe_allow_html=True)


# ---------- screen 2: customers ----------

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
    st.markdown(f'Counted as of {as_of.day} {as_of:%b %Y}, the day after the last order in your file.')

    ids = {str(c): c for c in s['customer_id']}
    chart_col, legend_col = st.columns([3, 2])
    with chart_col:
        event = st.altair_chart(radar_chart(radar_frame(s)), width='content', theme=None, key='radar',
                                on_select='rerun', selection_mode='pick')
    legend_col.markdown(LEGEND_HTML, unsafe_allow_html=True)
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
                                    'Last order': g['last_order'].dt.strftime('%Y-%m-%d'), 'Orders': g['n_orders'],
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


# ---------- screen 3: audit ----------

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
    st.write('2. Too little history: not triggered'
             + (f" (windows dropped: {'; '.join(a['skipped'])})." if a['skipped'] else '.'))
    st.write('3. The model must beat the simple rule in every window: '
             + ('triggered, using the simple rule' if r['ranker'] == 'recency' else 'not triggered')
             + f" ({plain(a['ranker_reason'])}).")

    with st.expander('How this is calculated'):
        st.dataframe(pd.DataFrame({
            'Test window starts': w['origin'].dt.strftime('%Y-%m-%d'), 'Customers': w['n'],
            'Base rate': w['base_rate'].map(pct),
            'AUC model': w['auc_model'].round(3), 'AUC recency': w['auc_recency'].round(3),
            'Top-20% hit model': w['top20_model'].map(pct), 'Top-20% hit recency': w['top20_recency'].map(pct),
        }), hide_index=True, width='stretch')
        st.caption('Each test window hides the last 8 weeks of a past point in your file, ranks customers with '
                   'only the data before it, then checks who really ordered. Base rate: share of all scored '
                   'customers who ordered again. Top-20% hit: the same share among the top 20% of each ranking. '
                   'AUC: how well each ranking separates buyers from non-buyers (0.5 is chance). Tier shares are '
                   'pooled over the windows (lowest to highest window in brackets).')


# ---------- screen 4: evidence (UCI) ----------

def screen_evidence():
    """Read-only results of our own runs on the public UCI dataset (app/evidence_uci.json, built by
    scripts/build_evidence.py). No raw data is shipped with the app."""
    st.markdown('## Does it work on real shop data?')
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
            st.warning(f"{r.window}: the model's win is not conclusive (the interval includes zero).")

    st.markdown('### The details')
    with st.expander('Backtest on all customers: 3 test windows'):
        st.dataframe(pd.DataFrame({'Test window starts': b['window'], 'Customers': b['customers'],
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
        st.dataframe(pd.DataFrame({'Test window starts': h['window'], 'Customers': h['customers'],
                                   'In top 20%': h['top20_customers'], 'Top-20% hit model': h['top20_model'].map(pct1),
                                   'Top-20% hit recency': h['top20_recency'].map(pct1),
                                   'Difference (points)': (h['diff'] * 100).round(1),
                                   '95% interval (points)': [f'{lo * 100:+.1f} to {hi * 100:+.1f}'
                                                             for lo, hi in zip(h['ci_low'], h['ci_high'])],
                                   'Verdict': h['verdict']}), hide_index=True, width='stretch')
    with st.expander('How well the predicted chances matched (calibration)'):
        st.dataframe(pd.DataFrame({'Test window starts': b['window'], 'ECE, all customers': b['ece'],
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


# ---------- main ----------

def main():
    st.set_page_config(page_title='Repeat Radar', layout='wide')
    secrets_to_env()
    st.markdown(f'<style>{CSS}</style>', unsafe_allow_html=True)
    ready = mapping_confirmed()
    st.sidebar.markdown('<p class="rr-brand" style="font-size:1.5rem;margin:0">Repeat Radar</p>',
                        unsafe_allow_html=True)
    st.sidebar.caption('Who is likely to order again within 8 weeks, and how often that was right before.')
    status = {SCREENS[0]: 'start here' if not ready else 'done', SCREENS[1]: 'ready' if ready else 'locked',
              SCREENS[2]: 'ready' if ready else 'locked', SCREENS[3]: 'always open'}
    screen = st.sidebar.radio('Steps', SCREENS, key='screen', format_func=lambda x: f'{x} ({status[x]})')
    st.sidebar.caption(f'You are on step {SCREENS.index(screen) + 1} of {len(SCREENS)}.'
                       + ('' if ready else ' Steps 2 and 3 unlock after you confirm the column mapping.'))
    try:
        {SCREENS[0]: screen_upload, SCREENS[1]: screen_customers, SCREENS[2]: screen_audit,
         SCREENS[3]: screen_evidence}[screen]()
    except Exception as e:  # never show a traceback
        st.error(f'Something went wrong: {type(e).__name__}: {e}')

main()
