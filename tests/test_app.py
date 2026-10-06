"""Smoke test of the Streamlit app with each sample file, without any LLM key."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / 'app' / 'streamlit_app.py')
SAMPLES = ['Indonesian point of sale (synthetic)', 'E-commerce (synthetic)']


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'none')  # beats any .env (load_dotenv does not override); no key, no network


def _go(at, screen):
    return at.sidebar.radio(key='screen').set_value(screen).run()


def _customers(at):
    """All intent-group tables of the contact list, in display order, as one frame."""
    import pandas as pd
    return pd.concat([d.value for d in at.dataframe if 'Next step' in d.value.columns], ignore_index=True)


def _pick_customer(at, due=True):
    """Select the first customer in the list who is (or is not) due for a message."""
    table = _customers(at)
    rows = table[(table['Next step'] != 'Not due yet') == due]
    return at.selectbox(key='customer').set_value(rows['Customer'].iloc[0]).run()


def test_screens_locked_until_mapping_confirmed(no_llm):
    at = AppTest.from_file(APP, default_timeout=180).run()
    for screen in ('2. Customers', '3. Audit'):
        _go(at, screen)
        assert not at.exception and any('Locked' in i.value for i in at.info)


@pytest.mark.parametrize('sample', SAMPLES)
def test_each_sample_end_to_end(no_llm, sample):
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value(sample)
    at.button(key='use_sample').click().run()
    assert not at.exception and not at.error
    at.button(key='confirm').click().run()
    assert not at.exception and not at.error
    assert any('Mapping confirmed' in s.value for s in at.success)

    _go(at, '2. Customers')
    assert not at.exception and not at.error
    assert any(m.value.startswith('Counted as of ') and 'the day after the last order in your file' in m.value
               for m in at.markdown)
    assert len(at.metric) == 3                                     # one measured hit rate per tier
    table = at.dataframe[0].value
    assert list(table.columns) == ['Customer', 'Tier', 'Last order', 'Orders', 'Days since last order',
                                   'Next step']                    # no probability column
    _pick_customer(at, due=True)
    assert not at.exception and not at.error
    captions = [c.value for c in at.caption]
    assert 'Explanation source: template' in captions and 'Message source: template' in captions
    _pick_customer(at, due=False)
    assert any(i.value.startswith('Not due yet, usual gap is') for i in at.info)
    assert not any(c.value.startswith('Message source') for c in at.caption)

    _go(at, '3. Audit')
    assert not at.exception and not at.error
    windows = at.dataframe[0].value
    assert len(windows) >= 2 and {'AUC model', 'AUC recency', 'Base rate'} <= set(windows.columns)
    assert any(m.value.startswith('Pooled over the test windows') for m in at.markdown)


def test_disagreement_blocks_confirm_until_user_picks(no_llm, monkeypatch):
    import json as _json
    import streamlit as st
    import app.mapping as mapping_mod
    swapped = {'customer_id': 'customer_email', 'invoice_id': 'order_id', 'date': 'order_date',
               'quantity': 'unit_price', 'price': 'quantity', 'country': None, 'product': None}
    monkeypatch.setattr(mapping_mod, 'map_columns', lambda *a, **k: (swapped, []))
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, 'client', lambda: (object(), 'fake'))   # a key is available (map_columns is faked)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    assert not at.exception
    assert any('disagree' in w.value for w in at.warning)
    assert at.button(key='confirm').disabled
    at.radio[0].set_value('Rules proposal').run()
    assert not at.exception and not at.button(key='confirm').disabled
    at.button(key='confirm').click().run()
    assert any('Mapping confirmed' in s.value for s in at.success)
    st.cache_data.clear()


class _PromptFake:
    """Stand-in LLM: refuses mapping (rules are used), answers the draft prompt, gives no usable explanation."""
    def __init__(self):
        self.chat = self.completions = self

    def create(self, messages, **kw):
        prompt = messages[0]['content']
        if 'Map the columns' in prompt:
            raise ConnectionError('mapping not faked')
        text = '{"message": "Hi! We hope all is well. Let us know when you would like to order again."}' \
            if 'follow-up message' in prompt else 'no'
        msg = type('M', (), {'content': text})
        return type('R', (), {'choices': [type('C', (), {'message': msg, 'finish_reason': 'stop'})]})


def test_verified_llm_draft_is_labelled(monkeypatch):
    import streamlit as st
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, 'client', lambda: (_PromptFake(), 'fake'))
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    at.button(key='confirm').click().run()
    _go(at, '2. Customers')
    _pick_customer(at, due=True)
    assert not at.exception and not at.error
    captions = [c.value for c in at.caption]
    assert 'Message source: llm' in captions and any(c.startswith('Checked by code') for c in captions)
    assert 'Explanation source: template' in captions
    st.cache_data.clear()


def test_high_tier_not_due_says_no_message_needed(no_llm):
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    at.button(key='confirm').click().run()
    _go(at, '2. Customers')
    table = _customers(at)
    rows = table[(table['Tier'] == 'high') & (table['Next step'] == 'Not due yet')]
    assert len(rows), 'sample has no high-tier customer who is not due'
    at.selectbox(key='customer').set_value(rows['Customer'].iloc[0]).run()
    infos = [i.value for i in at.info]
    assert 'Likely to reorder on their own. No message needed yet.' in infos
    assert any(i.startswith('Not due yet, usual gap is') for i in infos)


class _CountingFake(_PromptFake):
    calls = 0

    def create(self, messages, **kw):
        _CountingFake.calls += 1
        return super().create(messages, **kw)


def test_llm_session_cap_falls_back_to_templates(monkeypatch):
    import streamlit as st
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, 'client', lambda: (_CountingFake(), 'fake'))
    monkeypatch.setenv('LLM_SESSION_CAP', '1')          # only the column mapping may use the LLM
    st.cache_data.clear()
    _CountingFake.calls = 0
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    at.button(key='confirm').click().run()
    mapping_calls = _CountingFake.calls
    _go(at, '2. Customers')
    _pick_customer(at, due=True)
    assert not at.exception and not at.error
    captions = [c.value for c in at.caption]
    assert 'Message source: template' in captions and 'Explanation source: template' in captions
    assert any('LLM limit for this session reached (1 requests)' in w.value for w in at.warning)
    assert _CountingFake.calls == mapping_calls                # no LLM call after the cap
    st.cache_data.clear()


def test_secrets_are_not_in_code():
    import re
    from pathlib import Path
    root = Path(APP).parents[1]
    for f in list((root / 'app').glob('*.py')) + list((root / 'scripts').glob('*.py')):
        text = f.read_text(encoding='utf-8')
        assert not re.search(r'(?i)(api_key|secret)\s*=\s*["\'][A-Za-z0-9_\-]{16,}', text), f
        assert not re.search(r'\b(sk|rc)_[A-Za-z0-9]{20,}', text), f


def _open_sample(at, sample='E-commerce (synthetic)'):
    at.selectbox(key='sample_choice').set_value(sample)
    at.button(key='use_sample').click().run()
    at.button(key='confirm').click().run()
    return at


SAMPLE_NOTE = ('Synthetic sample. Results here show how the app works, not evidence. '
               'The evidence is on the Evidence page.')


def test_contact_list_grouped_by_intent_with_counts_and_sample_note(no_llm):
    import streamlit as st
    st.cache_data.clear()
    at = _open_sample(AppTest.from_file(APP, default_timeout=180).run())
    assert any(SAMPLE_NOTE in i.value for i in at.info)                       # screen 1
    _go(at, '2. Customers')
    assert SAMPLE_NOTE in [i.value for i in at.info]                          # screen 2
    heads = [m.value for m in at.markdown if m.value.startswith('#### ')]
    assert [h.rsplit(' (', 1)[0][5:] for h in heads] == ['Due now', 'Slipping (overdue)', 'Lapsed', 'Not due yet']
    groups = [d.value for d in at.dataframe if 'Next step' in d.value.columns]
    order = {'high': 0, 'medium': 1, 'low': 2}
    for h, g in zip(heads, groups):
        assert h.endswith(f'({len(g):,})')                                    # count per group
        assert list(g['Tier'].map(order)) == sorted(g['Tier'].map(order))     # tier order inside the group
    assert any(m.value.startswith('**Due now**:') for m in at.markdown)
    _go(at, '3. Audit')
    assert SAMPLE_NOTE in [i.value for i in at.info]                          # screen 3


def test_evidence_page_without_upload(no_llm):
    at = AppTest.from_file(APP, default_timeout=180).run()
    _go(at, '4. Evidence (UCI)')
    assert not at.exception and not at.error
    assert len(at.dataframe) == 6                       # backtest, tiers, holdout, calibration, mapping, drafts
    holdout = at.dataframe[2].value
    assert list(holdout['Verdict']) == ['model better (interval above 0)', 'model better (interval above 0)',
                                        'not conclusive (interval includes 0)']
    assert any('2011-04-15' in w.value and 'not conclusive' in w.value for w in at.warning)
    assert any('CC BY 4.0' in c.value and 'archive.ics.uci.edu' in c.value for c in at.caption)
    assert any('build_evidence.py' in c.value for c in at.code)


def test_global_daily_cap_falls_back_to_templates(monkeypatch):
    import streamlit as st
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, 'client', lambda: (_CountingFake(), 'fake'))
    monkeypatch.setenv('LLM_DAILY_CAP', '1')            # the whole app may make 1 LLM request today
    monkeypatch.setenv('LLM_SESSION_CAP', '20')
    st.cache_data.clear()
    st.cache_resource.clear()                          # fresh in-memory daily counter
    _CountingFake.calls = 0
    at = _open_sample(AppTest.from_file(APP, default_timeout=180).run())   # the mapping uses the 1 request
    used = _CountingFake.calls
    _go(at, '2. Customers')
    _pick_customer(at, due=True)
    assert not at.exception and not at.error
    captions = [c.value for c in at.caption]
    assert 'Message source: template' in captions and 'Explanation source: template' in captions
    assert any('Daily LLM limit for this app reached (1 requests)' in w.value for w in at.warning)
    assert _CountingFake.calls == used
    other = _open_sample(AppTest.from_file(APP, default_timeout=180).run())  # a second session shares the limit
    assert _CountingFake.calls == used
    st.cache_data.clear()
    st.cache_resource.clear()


ECOM_MAPPING = {'customer_id': 'customer_email', 'invoice_id': 'order_id', 'date': 'order_date',
                'quantity': 'quantity', 'price': 'unit_price', 'country': None, 'product': None, 'line_total': None}


class _MappingFake(_PromptFake):
    """Answers the mapping prompt with the true e-commerce mapping; counts mapping calls."""
    mapping_calls = 0

    def create(self, messages, **kw):
        if 'Map the columns' in messages[0]['content']:
            _MappingFake.mapping_calls += 1
            import json as _json
            msg = type('M', (), {'content': _json.dumps(ECOM_MAPPING)})
            return type('R', (), {'choices': [type('C', (), {'message': msg, 'finish_reason': 'stop'})]})
        return super().create(messages, **kw)


def _no_key():
    from app.llm import LLMUnavailable
    raise LLMUnavailable('FEATHERLESS_API_KEY is not set (.env)')


def test_fallback_mapping_without_key_is_not_reused_once_a_key_is_available(monkeypatch):
    import streamlit as st
    import app.llm as llm_mod
    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setattr(llm_mod, 'client', _no_key)                       # no key yet
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    assert 'Proposed by the built-in rules.' in [m.value for m in at.markdown]
    monkeypatch.setattr(llm_mod, 'client', lambda: (_MappingFake(), 'fake'))   # the key is added; caches are kept
    _MappingFake.mapping_calls = 0
    at2 = AppTest.from_file(APP, default_timeout=180).run()
    at2.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at2.button(key='use_sample').click().run()
    assert 'Proposed by the LLM.' in [m.value for m in at2.markdown] and _MappingFake.mapping_calls == 1
    st.cache_data.clear()
    st.cache_resource.clear()


def test_failed_llm_mapping_is_not_kept_in_the_cache(monkeypatch):
    import streamlit as st
    import app.llm as llm_mod

    class _Down(_PromptFake):
        def create(self, messages, **kw):
            raise ConnectionError('provider down')
    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setattr(llm_mod, 'client', lambda: (_Down(), 'fake'))
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    assert 'Proposed by the built-in rules.' in [m.value for m in at.markdown]
    monkeypatch.setattr(llm_mod, 'client', lambda: (_MappingFake(), 'fake'))  # provider back
    at2 = AppTest.from_file(APP, default_timeout=180).run()
    at2.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at2.button(key='use_sample').click().run()
    assert 'Proposed by the LLM.' in [m.value for m in at2.markdown]
    st.cache_data.clear()
    st.cache_resource.clear()


def test_no_key_message_and_trust_line_without_variable_names(monkeypatch):
    import streamlit as st
    import app.llm as llm_mod
    st.cache_data.clear()
    monkeypatch.setattr(llm_mod, 'client', _no_key)
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert ('**We do not just make predictions. We only make them when the data shows we can trust them.**'
            in [m.value for m in at.markdown])
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    captions = [c.value for c in at.caption]
    assert 'AI suggestions are off right now, so the built-in rules were used.' in captions
    shown = ' '.join(e.value for kind in (at.caption, at.markdown, at.info, at.warning, at.error) for e in kind
                     if isinstance(e.value, str))
    for bad in ('.env', 'FEATHERLESS', 'API_KEY', 'LLM_PROVIDER', 'LLM_MODEL'):
        assert bad not in shown, bad
    st.cache_data.clear()


class _ExplainDraftFake(_PromptFake):
    """Working LLM: no mapping (rules are used), a valid explanation citing a real invoice, a valid draft."""
    def create(self, messages, **kw):
        prompt = messages[0]['content']
        if 'Map the columns' in prompt:
            raise ConnectionError('mapping not faked')
        if 'follow-up message' in prompt:
            text = '{"message": "Hi! Let us know when you would like to order again."}'
        else:
            import json as _json
            facts = _json.loads(prompt.split('Facts: ', 1)[1])
            text = f"Their last invoice was {facts['last_orders'][0]['invoice_id']}."
        msg = type('M', (), {'content': text})
        return type('R', (), {'choices': [type('C', (), {'message': msg, 'finish_reason': 'stop'})]})


class _ProviderDown(_PromptFake):
    def create(self, messages, **kw):
        raise ConnectionError('provider down')


def _sources_for_first_due_customer():
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox(key='sample_choice').set_value('E-commerce (synthetic)')
    at.button(key='use_sample').click().run()
    at.button(key='confirm').click().run()
    _go(at, '2. Customers')
    _pick_customer(at, due=True)
    assert not at.exception and not at.error
    return {c.value for c in at.caption if 'source:' in c.value}


@pytest.mark.parametrize('first', ['no key', 'provider error'])
def test_template_explanation_and_draft_are_not_reused_once_the_llm_works(monkeypatch, first):
    import streamlit as st
    import app.llm as llm_mod
    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setattr(llm_mod, 'client', _no_key if first == 'no key' else (lambda: (_ProviderDown(), 'fake')))
    assert _sources_for_first_due_customer() == {'Explanation source: template', 'Message source: template'}
    monkeypatch.setattr(llm_mod, 'client', lambda: (_ExplainDraftFake(), 'fake'))   # key added / provider back
    assert _sources_for_first_due_customer() == {'Explanation source: llm', 'Message source: llm'}
    st.cache_data.clear()
    st.cache_resource.clear()
