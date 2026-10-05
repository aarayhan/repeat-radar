import json

import pandas as pd

from app.drafts import BANNED, draft_facts, llm_draft, template_draft, usual_products, verify
from test_llm import FakeLLM

T = pd.Timestamp
ORDERS = pd.DataFrame({'date': [T('2011-09-01'), T('2011-10-01'), T('2011-11-01')]})
PRODUCTS = ['WHITE HANGING HEART T-LIGHT HOLDER', 'JUMBO BAG RED RETROSPOT', 'REGENCY CAKESTAND 3 TIER']
FACTS = draft_facts(ORDERS, PRODUCTS, 12345.0, 'high', 0.752, as_of=T('2011-12-10'))
CATALOGUE = PRODUCTS + ['PARTY BUNTING', 'SET OF 3 CAKE TINS PANTRY DESIGN', 'BAG']
GOOD = ('Hi! It has been 39 days since your last order on 1 November 2011. Would you like more of the '
        'White Hanging Heart T-Light Holder or the Regency Cakestand 3 Tier? You may simply reply here.')


def _msg(text):
    return json.dumps({'message': text})


def test_facts():
    assert FACTS == {'customer_id': '12345', 'last_order': '2011-11-01', 'days_since_last_order': 39,
                     'usual_products': PRODUCTS, 'typical_gap_days': round(30.5), 'tier': 'high',
                     'tier_hit_rate_pct': 75}
    lines = pd.DataFrame({'invoice_id': ['1', '1', '2', '3', '3'], 'product': ['A', 'A', 'A', 'B', 'C']})
    assert usual_products(lines) == ['A', 'B', 'C']   # A in 2 invoices; B and C in 1, by name


def test_passing_draft():
    r = llm_draft(FACTS, (FakeLLM(_msg(GOOD)), 'x'), CATALOGUE)
    assert r['source'] == 'llm' and r['text'] == GOOD and r['attempts'][0][1] == []


def test_invented_product_rejected_after_repair():
    bad = _msg('Hi! Would you like to order Party Bunting again?')
    r = llm_draft(FACTS, (FakeLLM(bad, bad), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['text'] == template_draft(FACTS)
    assert "product not in the facts: 'PARTY BUNTING'" in r['attempts'][0][1]


def test_invented_number_fixed_by_repair():
    llm = FakeLLM(_msg('Hi! It has been 45 days since your last order.'), _msg(GOOD))
    r = llm_draft(FACTS, (llm, 'x'), CATALOGUE)
    assert r['source'] == 'llm_repaired' and "number not in the facts: '45'" in r['attempts'][0][1]
    assert '45' in llm.calls[1][-1]['content']   # the verifier's error was fed back


def test_discount_promise_rejected():
    bad = _msg('Order the Jumbo Bag Red Retrospot again and get a discount!')
    r = llm_draft(FACTS, (FakeLLM(bad, bad), 'x'), CATALOGUE)
    assert r['source'] == 'template'
    assert "promise or claim outside the facts: 'discount'" in r['attempts'][-1][1]


def test_verifier_details():
    assert verify(template_draft(FACTS), FACTS, CATALOGUE) == []
    assert any('date' in p for p in verify('Your order on 3 November 2011 arrived.', FACTS))
    assert any('date' in p for p in verify('Since your June order...', FACTS))
    assert verify('Your November 2011 order, in a typical 30 days, at 75%.', FACTS) == []
    assert any("'10'" in p for p in verify('Get 10% off.', FACTS)) and any("'off'" in p for p in verify('Get 10% off.', FACTS))
    assert any("'three'" in p for p in verify('You ordered three times.', FACTS))
    assert any('free' in p for p in verify('Free delivery on Friday!', FACTS))
    assert 'discount' in BANNED and 'stock' in BANNED and 'deadline' in BANNED and 'price' in BANNED


def test_json_failure_and_no_client():
    r = llm_draft(FACTS, (FakeLLM('Hi there', 'still not json'), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['json_failures'] == 2
    r = llm_draft(FACTS, (FakeLLM(TimeoutError('slow')), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['attempts'][0][1] == ['API error: TimeoutError']
    assert llm_draft(FACTS, None)['source'] == 'template'
