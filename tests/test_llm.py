import json

import pytest

from app.llm import map_columns, validate_mapping

COLS = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country']
GOOD = {'customer_id': 'Customer ID', 'invoice_id': 'Invoice', 'date': 'InvoiceDate',
        'quantity': 'Quantity', 'price': 'Price', 'country': 'Country', 'product': None}


def test_accepts_valid_mapping():
    assert validate_mapping(json.dumps(GOOD), COLS) == GOOD


@pytest.mark.parametrize('text, reason', [
    ('```json\n{}\n```', 'not valid JSON'),
    ('{"customer_id": "Customer ID",}', 'not valid JSON'),
    (None, 'not valid JSON'),
    ('["Invoice"]', 'expected a JSON object'),
    (json.dumps({**GOOD, 'price': None}), 'missing required'),
    (json.dumps({k: v for k, v in GOOD.items() if k != 'date'}), 'missing required'),
    (json.dumps({**GOOD, 'price': 'UnitPrice'}), 'not a column'),
    (json.dumps({**GOOD, 'price': 3}), 'not a column'),
    (json.dumps({**GOOD, 'product': 'Invoice'}), 'more than one field'),
    (json.dumps({**GOOD, 'amount': 'Price'}), 'unknown keys'),
])
def test_rejects_invalid(text, reason):
    with pytest.raises(ValueError, match=reason):
        validate_mapping(text, COLS)


class FakeLLM:
    """Stands in for the OpenAI client: returns canned replies in order."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls.append(list(kw['messages']))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        msg = type('M', (), {'content': r})
        return type('R', (), {'choices': [type('C', (), {'message': msg})]})


def test_repair_attempt_then_success():
    llm = FakeLLM('not json', json.dumps(GOOD))
    m, attempts = map_columns(COLS, [], llm=llm, model='x')
    assert m == GOOD and len(attempts) == 2 and attempts[0][1].startswith('not valid JSON')
    assert 'Invalid' in llm.calls[1][-1]['content']  # error was fed back


def test_fails_visibly_after_two_failures():
    with pytest.raises(RuntimeError, match='failed twice'):
        map_columns(COLS, [], llm=FakeLLM(ConnectionError('down'), '[]'), model='x')
