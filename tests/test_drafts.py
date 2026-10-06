"""Draft verifier: 15 hand-written bad drafts, 5 good drafts, and the LLM flow with FakeLLM."""
import json

import pandas as pd
import pytest

from app.drafts import (BLOCKED_PHRASES, TEMP_FIRST, TEMP_REPAIR, draft_facts, is_specific, llm_draft,
                        template_draft, usual_products, verify)
from test_llm import FakeLLM

T = pd.Timestamp
ORDERS = pd.DataFrame({'date': [T('2011-09-01'), T('2011-10-01'), T('2011-11-01')]})
PRODUCTS = ['WHITE HANGING HEART T-LIGHT HOLDER', 'JUMBO BAG RED RETROSPOT', 'REGENCY CAKESTAND 3 TIER']
FACTS = draft_facts(ORDERS, PRODUCTS, 12345.0, 'high', 0.752, as_of=T('2011-12-10'))     # 39 days
FACTS21 = draft_facts(ORDERS, PRODUCTS, 12345.0, 'high', 0.752, as_of=T('2011-11-22'))   # 21 days
CATALOGUE = PRODUCTS + ['PARTY BUNTING', 'SET OF 3 CAKE TINS PANTRY DESIGN', 'BAG']
JB = 'the Jumbo Bag Red Retrospot'

BAD = [  # (name, facts, draft): none of these may count as good
    ('invented product', FACTS, 'Hi! It has been 39 days. Would you like more Party Bunting?'),
    ('wrong day count', FACTS, f'It has been 40 days since your last order of {JB}.'),
    ('day count in words', FACTS, f'It has been three weeks since you ordered {JB}.'),
    ('converted unit', FACTS21, f'It has been 3 weeks since you ordered {JB}.'),
    ('date not in facts', FACTS, f'Your last order on 3 November 2011 included {JB}.'),
    ('no fact at all', FACTS, 'Hi! We hope all is well. Let us know if you would like to order again.'),
    ('discount', FACTS, f'Order {JB} again with a discount.'),
    ('% off, percent off', FACTS, f'Get 10% off, or 10 percent off, {JB}.'),
    ('free shipping, free delivery', FACTS, f'Free shipping and free delivery on {JB}.'),
    ('free gift, for free', FACTS, f'A free gift for you: {JB} for free.'),
    ('free of charge', FACTS, f'{JB}, free of charge.'),
    ('special offer, special price', FACTS, f'A special offer and special price on {JB}.'),
    ('limited time', FACTS, f'For a limited time, reorder {JB}.'),
    ('in stock, back in stock', FACTS, f'{JB} is in stock, back in stock now.'),
    ('only until, expires', FACTS, f'Only until Friday: the {JB[4:]} offer expires soon.'),
]
GOOD = [
    'Hi! It has been 39 days since your last order. Would you like more of the White Hanging Heart T-Light Holder?',
    'Feel free to reorder the jumbo bags red retrospot whenever you like.',          # no day count, plural product
    'It has been 39 days since your last order on 1 November 2011. We would love to hear from you.',
    "We'd love to offer you the Regency Cakestand 3 Tier again; it has been 39 days.",   # bare "offer" is allowed
    'Thanks for ordering the White Hanging Heart again in November 2011!',           # first 3 words of a product
]


def good(text, facts):
    return verify(text, facts, CATALOGUE) == [] and is_specific(text, facts)


def test_verifier_catches_all_15_bad_drafts():
    missed = [name for name, facts, text in BAD if good(text, facts)]
    assert len(BAD) == 15 and missed == []


def test_verifier_accepts_all_5_good_drafts():
    rejected = [(t, verify(t, FACTS, CATALOGUE)) for t in GOOD if not good(t, FACTS)]
    assert rejected == []


def test_clarified_cases():
    assert verify(GOOD[1], FACTS, CATALOGUE) == [] and is_specific(GOOD[1], FACTS)        # product, no day count
    no_fact = BAD[5][2]
    assert verify(no_fact, FACTS, CATALOGUE) == [] and not is_specific(no_fact, FACTS)    # verified but generic
    assert any('day count in words' in p for p in verify(BAD[2][2], FACTS, CATALOGUE))    # "three weeks"
    assert any('converted unit' in p for p in verify(BAD[3][2], FACTS21, CATALOGUE))      # "3 weeks", fact 21
    assert any('in words' in p for p in verify(f'It has been a couple of weeks since {JB}.', FACTS, CATALOGUE))
    assert any('in words' in p for p in verify(f'About a month ago you ordered {JB}.', FACTS, CATALOGUE))
    assert len(BLOCKED_PHRASES) == 15 and 'feel free' not in BLOCKED_PHRASES and 'offer' not in BLOCKED_PHRASES


def test_facts_and_template():
    assert FACTS == {'customer_id': '12345', 'last_order': '2011-11-01', 'days_since_last_order': 39,
                     'usual_products': PRODUCTS, 'typical_gap_days': round(30.5), 'tier': 'high',
                     'tier_hit_rate_pct': 75}
    lines = pd.DataFrame({'invoice_id': ['1', '1', '2', '3', '3'], 'product': ['A', 'A', 'A', 'B', 'C']})
    assert usual_products(lines) == ['A', 'B', 'C']
    assert good(template_draft(FACTS), FACTS)


def _msg(text):
    return json.dumps({'message': text})


def test_passing_draft_first_try():
    r = llm_draft(FACTS, (FakeLLM(_msg(GOOD[0])), 'x'), CATALOGUE)
    assert r['source'] == 'llm' and r['specific'] and r['attempts'][0][1:] == ([], TEMP_FIRST)


@pytest.mark.parametrize('bad, reason', [
    (BAD[0][2], 'product not in the facts'),
    (BAD[6][2], "blocked phrase: 'discount'"),
])
def test_invented_product_and_discount_fall_back_to_template(bad, reason):
    r = llm_draft(FACTS, (FakeLLM(_msg(bad), _msg(bad)), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['text'] == template_draft(FACTS)
    assert any(reason in p for p in r['attempts'][0][1])
    assert [a[2] for a in r['attempts']] == [TEMP_FIRST, TEMP_REPAIR]


def test_invented_number_fixed_by_repair():
    llm = FakeLLM(_msg(BAD[1][2]), _msg(GOOD[0]))
    r = llm_draft(FACTS, (llm, 'x'), CATALOGUE)
    assert r['source'] == 'llm_repaired' and any("'40 day'" in p for p in r['attempts'][0][1])
    assert '40 day' in llm.calls[1][-1]['content']   # the verifier's error was fed back


def test_json_failure_and_no_client():
    r = llm_draft(FACTS, (FakeLLM('Hi there', 'still not json'), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['json_failures'] == 2
    r = llm_draft(FACTS, (FakeLLM(TimeoutError('slow')), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['attempts'][0][1] == ['API error: TimeoutError']
    assert llm_draft(FACTS, None)['source'] == 'template'
