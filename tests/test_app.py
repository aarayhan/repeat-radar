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


def _pick_customer(at, due=True):
    """Select the first customer in the list who is (or is not) due for a message."""
    table = at.dataframe[0].value
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
    table = at.dataframe[0].value
    rows = table[(table['Tier'] == 'high') & (table['Next step'] == 'Not due yet')]
    assert len(rows), 'sample has no high-tier customer who is not due'
    at.selectbox(key='customer').set_value(rows['Customer'].iloc[0]).run()
    infos = [i.value for i in at.info]
    assert 'Likely to reorder on their own. No message needed yet.' in infos
    assert any(i.startswith('Not due yet, usual gap is') for i in infos)
