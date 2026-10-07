"""Shared by the screens: cached computation, LLM budgets, the confirmed result and small display helpers.

Files are processed in memory only (never written to disk, never logged). All numbers come from app/ code.
"""
import datetime
import hashlib
import html
import io
import json
import os
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

import app.llm as llm
from app.audit import recommend, tier_track_record
from app.charts import show_dates
from app.drafts import intents, llm_draft, typical_gap
from app.engine import clean
from app.explain import llm_explanation
from app.mapping import propose_mapping

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_NOTE = ('Synthetic sample. Results here show how the app works, not evidence. '
               'For evidence, see step 4, Results on real shop data.')
DEFAULT_LLM_CAP = 20   # LLM requests per session (override with LLM_SESSION_CAP)
DEFAULT_LLM_DAILY_CAP = 500   # LLM requests per day for the whole app, in memory (override with LLM_DAILY_CAP)
SECRET_KEYS = ('FEATHERLESS_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'LLM_PROVIDER', 'LLM_MODEL',
               'LLM_SESSION_CAP', 'LLM_DAILY_CAP')
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
        return llm.client()
    except llm.LLMUnavailable:
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
        st.warning(f"Not scored: {show_dates(result['audit']['reason'])}")
        return None
    return result


def plain(text):
    """Display wording only: the app calls the recency rule 'the simple rule'."""
    return show_dates(text.replace('recency rule', 'simple rule').replace(' vs recency ', ' vs simple rule '))


def takeaway(text):
    st.markdown(f'<p class="rr-takeaway">{html.escape(text)}</p>', unsafe_allow_html=True)
