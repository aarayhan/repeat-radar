import json

import pandas as pd
import pytest

from app.explain import customer_facts, llm_explanation, template_explanation, template_message
from test_llm import FakeLLM

T = pd.Timestamp
ORDERS = pd.DataFrame({'invoice_id': ['NT-100001', 'NT-100007', 'NT-100012', 'NT-100020'],
                       'date': [T('2024-01-01'), T('2024-01-31'), T('2024-03-01'), T('2024-04-10')],
                       'amount': [10000.0, 25000.0, 12500.0, 40000.0]})
FACTS = customer_facts(ORDERS, 'high', 21)


def test_customer_facts():
    assert FACTS['tier'] == 'high' and FACTS['n_orders'] == 4
    assert FACTS['last_order'] == '2024-04-10' and FACTS['days_since_last'] == 21
    assert FACTS['avg_days_between_orders'] == pytest.approx((30 + 30 + 40) / 3, abs=0.05)
    assert [o['invoice_id'] for o in FACTS['last_orders']] == ['NT-100020', 'NT-100012', 'NT-100007']
    one = customer_facts(ORDERS.head(1), 'low', 10)
    assert one['avg_days_between_orders'] is None and one['days_since_last'] == 10


@pytest.mark.parametrize('lang', ['en', 'id'])
def test_templates_cite_a_real_invoice(lang):
    for fn in (template_explanation, template_message):
        text, source = fn(FACTS, lang)
        assert source == 'template' and 'NT-100020' in text
    assert 'pesanan' in template_explanation(FACTS, 'id')[0]


def test_llm_valid_answer_is_used():
    llm = FakeLLM('Ordered 4 times, last on 2024-04-10 (invoice NT-100020), so worth a call.')
    text, source = llm_explanation(FACTS, 'en', (llm, 'x'))
    assert source == 'llm' and 'NT-100020' in text
    prompt = llm.calls[0][0]['content']
    assert json.dumps(FACTS) in prompt and 'NT-100001' not in prompt   # only this customer's facts, last 3 orders


@pytest.mark.parametrize('reply', [
    'Last order NT-100020, and before that NT-999999.',   # invented invoice
    'A loyal customer who buys often.',                   # no invoice cited
    '',
])
def test_llm_unchecked_answer_falls_back(reply):
    assert llm_explanation(FACTS, 'en', (FakeLLM(reply), 'x')) == template_explanation(FACTS, 'en')


def test_client_error_and_no_client_fall_back():
    assert llm_explanation(FACTS, 'id', (FakeLLM(TimeoutError('slow')), 'x')) == template_explanation(FACTS, 'id')
    assert llm_explanation(FACTS, 'en', None) == template_explanation(FACTS, 'en')


@pytest.mark.parametrize('reply', [
    'A significant order of $635,000 on invoice NT-100020.',
    'Pesanan besar Rp 40.000 pada nota NT-100020.',
    'Invoice NT-100020 was worth 40000 USD.',
    'Invoice NT-100020 was worth EUR 40000.',
])
def test_currency_in_explanation_falls_back(reply):   # amounts in the data have no currency; any currency is invented
    assert llm_explanation(FACTS, 'en', (FakeLLM(reply), 'x')) == template_explanation(FACTS, 'en')
