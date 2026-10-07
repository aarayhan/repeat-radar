"""Screen 1: upload a sales export (or try the demo) and confirm the column mapping."""
import hashlib
import json

import pandas as pd
import streamlit as st

from app.charts import day_label, show_dates
from app.llm import OPTIONAL, REQUIRED, validate_mapping
from app.mapping import check_values
from app.screens.common import ROOT, SAMPLE_NOTE, analyse, cap_notice, proposal, read_table

SAMPLES = {'Indonesian point of sale (synthetic)': 'kasir_indonesia.csv',
           'E-commerce (synthetic)': 'ecommerce.csv',
           'Messy export (synthetic)': 'messy_export.csv'}
TRUST_LINE = 'We do not just make predictions. We only make them when the data shows we can trust them.'
NO_AI_MESSAGE = 'AI suggestions are off right now, so the built-in rules were used.'
NONE = '(none)'
HERO_HTML = ('<div class="rr-hero"><div class="rr-sweep" aria-hidden="true"></div><div>'
             '<h1 class="rr-brand">Repeat Radar</h1>'
             f'<p class="rr-trust">{TRUST_LINE}</p>'
             '<p class="rr-lead">Upload a sales export and see which customers are likely to order again, '
             "how often that list was right before, and a message checked against each customer's own orders."
             '</p></div></div>')


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
    with st.expander('Other samples'):
        c1, c2 = st.columns([3, 1], vertical_alignment='bottom')
        choice = c1.selectbox('Sample file (synthetic)', list(SAMPLES), key='sample_choice')
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
               f"{day_label(inv['date'].min())} to {day_label(inv['date'].max())}. Next: open step 2, Customers, "
               'in the sidebar to see who to contact.')
    if result['audit']['status'] != 'ok':
        st.warning(f"Not scored: {show_dates(result['audit']['reason'])}")
