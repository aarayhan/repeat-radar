"""Draft facts, intent and verifier: 15 hand-written bad drafts, 5 good drafts, one test per rule, LLM flow."""
import json

import pandas as pd
import pytest

from app.audit import score_now
from app.drafts import (BLOCKED_PHRASES, TEMP_FIRST, TEMP_REPAIR, draft_facts, intent_of, intents, is_specific,
                        llm_draft, llm_facts, sentence_case, template_draft, usual_products, verify)
from test_llm import FakeLLM

T = pd.Timestamp
ORDERS = pd.DataFrame({'date': [T('2011-09-01'), T('2011-10-01'), T('2011-11-01')]})   # typical gap 30 days
PRODUCTS = ['WHITE HANGING HEART T-LIGHT HOLDER', 'JUMBO BAG RED RETROSPOT', 'REGENCY CAKESTAND 3 TIER.']


def facts(days):
    return draft_facts(ORDERS, PRODUCTS, 12345.0, 'high', 0.752, days)


DUE, OVERDUE, LAPSED, NOT_DUE = facts(30), facts(60), facts(400), facts(10)
CATALOGUE = PRODUCTS + ['PARTY BUNTING', 'SET OF 3 CAKE TINS PANTRY DESIGN', 'BAG']
JB = 'the Jumbo bag red retrospot'

BAD = [  # (name, facts, draft): none of these may count as good
    ('invented product', DUE, 'Would you like to restock Party Bunting?'),
    ('duration in digits', DUE, f'It has been 30 days; would you like to restock {JB}?'),
    ('duration in words', DUE, f'It has been three weeks since you ordered {JB}.'),
    ('a couple of weeks', OVERDUE, f'It has been a couple of weeks since you ordered {JB}.'),
    ('date not in facts', DUE, f'Your order on 3 November 2011 included {JB}.'),
    ('no product (generic)', DUE, 'Hi! Let us know if you would like to order again.'),
    ('discount', DUE, f'Restock {JB} with a discount.'),
    ('% off', DUE, f'Get 10% off {JB}.'),
    ('free shipping', DUE, f'Free shipping on {JB}.'),
    ('special offer', DUE, f'A special offer on {JB}.'),
    ('in stock', DUE, f'{JB} is in stock.'),
    ('drop by', OVERDUE, f'Drop by and pick up more of {JB}.'),
    ('miss you when due', DUE, f'We miss you! Would you like to restock {JB}?'),
    ('enjoying when lapsed', LAPSED, f'We hope you are enjoying {JB}.'),
    ('hope you like when lapsed', LAPSED, f'We hope you like {JB} as much as we do.'),
]
GOOD = [
    (DUE, 'Hi! Would you like to restock the White hanging heart t-light holder? Just reply and we will prepare it.'),
    (OVERDUE, 'We miss working with you. Would you like to order the jumbo bags red retrospot again?'),
    (LAPSED, 'It has been a while. You used to order the Regency Cakestand 3 Tier from us; reply if you would like '
             'to order again.'),
    (DUE, 'Thanks for your order on 1 November 2011 of the White Hanging Heart. Time to restock?'),
    (DUE, "We'd be glad to offer the Jumbo bag red retrospot again. Feel free to reply."),
]


def good(text, f):
    return verify(text, f, CATALOGUE) == [] and is_specific(text, f)


def test_verifier_catches_all_15_bad_drafts():
    missed = [name for name, f, text in BAD if good(text, f)]
    assert len(BAD) == 15 and missed == []


def test_verifier_accepts_all_5_good_drafts():
    assert [(t, verify(t, f, CATALOGUE)) for f, t in GOOD if not good(t, f)] == []


# ---------- one test per rule ----------

def test_non_product_lines_left_out_of_facts():
    lines = pd.DataFrame({'invoice_id': ['1', '1', '2', '2', '3', '3', '4'],
                          'product': ['POSTAGE', 'DOTCOM POSTAGE', 'Manual', 'POST',
                                      'Dotcomgiftshop Gift Voucher £10.00', 'Adjustment by john on 26/01/2010 16',
                                      'JUMBO BAG RED RETROSPOT']})
    assert usual_products(lines) == ['JUMBO BAG RED RETROSPOT']


def test_product_names_sentence_case_without_trailing_punctuation():
    assert sentence_case('LUNCH BAG  BLACK SKULL.') == 'Lunch bag black skull'
    assert DUE['usual_products'] == ['White hanging heart t-light holder', 'Jumbo bag red retrospot',
                                     'Regency cakestand 3 tier']


def test_intent_thresholds():
    assert [intent_of(d, 30) for d in (23, 24, 45, 46, 365, 366)] == \
        ['not_due', 'due', 'due', 'overdue', 'overdue', 'lapsed']
    assert intent_of(400, 600) == 'lapsed' and intent_of(5, None) == 'overdue'
    assert (DUE['intent'], OVERDUE['intent'], LAPSED['intent'], NOT_DUE['intent']) == \
        ('due', 'overdue', 'lapsed', 'not_due')


def test_reference_date_is_day_after_last_order_and_intent_uses_the_same_value(make_inv):
    inv = make_inv()
    end = inv['date'].max()
    extra = pd.DataFrame({'customer_id': [9001] * 3, 'invoice_id': ['x1', 'x2', 'x3'],
                          'date': [end - pd.Timedelta(days=60), end - pd.Timedelta(days=30), end],
                          'amount': [10.0, 10.0, 10.0]})
    inv = pd.concat([inv, extra], ignore_index=True)
    s = score_now(inv)['scored']
    row = s[s['customer_id'] == 9001].iloc[0]
    assert row['recency'] == 1                                   # last order on the file's last date -> 1 day
    f = draft_facts(extra, [], 9001, row['tier'], 0.5, row['recency'])
    assert f['days_since_last_order'] == 1 and f['intent'] == intent_of(1, 30) == 'not_due'
    assert intents(inv, s)[list(s['customer_id']).index(9001)] == f['intent']


def test_not_due_gets_no_draft():
    llm = FakeLLM()
    r = llm_draft(NOT_DUE, (llm, 'x'), CATALOGUE)
    assert r['source'] == 'not_due' and r['text'] is None and llm.calls == []
    assert template_draft(NOT_DUE) is None


def test_no_duration_in_message():
    for text in ('restock it after 30 days', 'two weeks ago', 'a few months', 'over a year', 'last week', '4 years'):
        assert any('duration' in p for p in verify(f'{text}, {JB}', OVERDUE, CATALOGUE)), text
    assert verify(f'It has been a while. Would you like {JB} again?', OVERDUE, CATALOGUE) == []
    assert 'days_since_last_order' not in llm_facts(DUE) and 'typical_gap_days' not in llm_facts(DUE)
    assert set(llm_facts(DUE)) == {'intent', 'usual_products', 'last_order'}


def test_specific_means_a_usual_product():
    assert is_specific(f'Time to restock {JB}?', DUE)
    assert not is_specific('It has been 30 days since your last order.', DUE)


def test_miss_phrases_only_for_overdue_or_lapsed():
    text = f'We miss your orders. Would you like {JB} again?'
    assert any('not for a due' in p for p in verify(text, DUE, CATALOGUE))
    assert verify(text, OVERDUE, CATALOGUE) == [] and verify(text, LAPSED, CATALOGUE) == []


def test_enjoying_and_hope_you_like_rejected_only_when_lapsed():
    for text in (f'We hope you are enjoying {JB}.', f'We hope you like {JB}.'):
        assert any('lapsed' in p for p in verify(text, LAPSED, CATALOGUE))
        assert verify(text, DUE, CATALOGUE) == []


def test_drop_by_always_rejected():
    for f in (DUE, OVERDUE, LAPSED):
        assert "blocked phrase: 'drop by'" in verify(f'Drop by for {JB}.', f, CATALOGUE)
    assert 'drop by' in BLOCKED_PHRASES and 'feel free' not in BLOCKED_PHRASES


# ---------- templates and LLM flow ----------

@pytest.mark.parametrize('f', [DUE, OVERDUE, LAPSED])
def test_templates_pass_their_own_verifier(f):
    assert good(template_draft(f), f)


def _msg(text):
    return json.dumps({'message': text})


def test_passing_draft_first_try_and_prompt_has_no_day_count():
    llm = FakeLLM(_msg(GOOD[0][1]))
    r = llm_draft(DUE, (llm, 'x'), CATALOGUE)
    assert r['source'] == 'llm' and r['specific'] and r['attempts'][0][1:] == ([], TEMP_FIRST)
    prompt = llm.calls[0][0]['content']
    assert 'restock reminder' in prompt and '12345' not in prompt and '"days_since_last_order"' not in prompt


def test_rejected_draft_falls_back_to_template_after_repair_at_0_7():
    bad = _msg(BAD[0][2])
    r = llm_draft(DUE, (FakeLLM(bad, bad), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['text'] == template_draft(DUE)
    assert [a[2] for a in r['attempts']] == [TEMP_FIRST, TEMP_REPAIR]


def test_repair_fixes_a_duration():
    llm = FakeLLM(_msg(BAD[1][2]), _msg(GOOD[0][1]))
    r = llm_draft(DUE, (llm, 'x'), CATALOGUE)
    assert r['source'] == 'llm_repaired' and any('duration' in p for p in r['attempts'][0][1])


def test_json_failure_and_no_client():
    r = llm_draft(DUE, (FakeLLM('Hi there', 'still not json'), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['json_failures'] == 2
    r = llm_draft(DUE, (FakeLLM(TimeoutError('slow')), 'x'), CATALOGUE)
    assert r['source'] == 'template' and r['attempts'][0][1] == ['API error: TimeoutError']
    assert llm_draft(DUE, None)['source'] == 'template'


def test_no_product_data_blocks_invented_product_names():   # kasir_indonesia.csv has no product column
    f = draft_facts(ORDERS, [], 'Toko A', 'high', 0.75, 30)
    invented = 'Hi, it is time to restock your shelves with our delicious Chocolate Delights. Just reply to order.'
    assert any('Chocolate Delights' in p for p in verify(invented, f, ()))
    assert verify('Hi, would you like to place your next order? Just reply to this message.', f, ()) == []
    assert verify(template_draft(f), f, ()) == []
    llm = FakeLLM(_msg(invented), _msg(invented))
    r = llm_draft(f, (llm, 'x'), ())
    assert r['source'] == 'template' and 'no product names' in llm.calls[0][0]['content']
