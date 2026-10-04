"""Column mapping by LLM (Featherless, OpenAI-compatible). Output is validated in code."""
import json
import os
from pathlib import Path

REQUIRED = ('customer_id', 'invoice_id', 'date', 'quantity', 'price')
OPTIONAL = ('country', 'product')
BASE_URL = 'https://api.featherless.ai/v1'
DEFAULT_MODEL = 'Qwen/Qwen2.5-7B-Instruct'


def validate_mapping(text, columns):
    """Parse the LLM reply and check it against the schema. Returns the mapping dict or raises ValueError."""
    try:
        m = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f'not valid JSON: {e}')
    if not isinstance(m, dict):
        raise ValueError(f'expected a JSON object, got {type(m).__name__}')
    extra = set(m) - set(REQUIRED) - set(OPTIONAL)
    if extra:
        raise ValueError(f'unknown keys: {sorted(extra)}')
    missing = [k for k in REQUIRED if m.get(k) is None]
    if missing:
        raise ValueError(f'missing required keys: {missing}')
    used = [v for v in m.values() if v is not None]
    for k, v in m.items():
        if v is not None and (not isinstance(v, str) or v not in columns):
            raise ValueError(f'{k} -> {v!r} is not a column in the file')
    if len(used) != len(set(used)):
        raise ValueError('the same column is mapped to more than one field')
    return m


def _prompt(columns, sample_rows):
    return (
        'Map the columns of a sales export to a standard schema.\n'
        f'Columns: {json.dumps(columns)}\n'
        f'Sample rows: {json.dumps(sample_rows, default=str)}\n\n'
        f'Return ONLY a JSON object with exactly these keys: {", ".join(REQUIRED + OPTIONAL)}.\n'
        f'Each value is one column name copied exactly from the list. '
        f'Required keys: {", ".join(REQUIRED)}. Optional keys ({", ".join(OPTIONAL)}) may be null.\n'
        'customer_id = buyer id, invoice_id = order/invoice number, date = order date, '
        'quantity = units per line, price = unit price, product = product name or code.\n'
        'No explanation, no markdown, no code fences.'
    )


def client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    key = os.getenv('FEATHERLESS_API_KEY')
    if not key:
        raise RuntimeError('FEATHERLESS_API_KEY is not set (.env)')
    return OpenAI(base_url=BASE_URL, api_key=key)


def map_columns(columns, sample_rows, llm=None, model=None):
    """Ask the LLM for a mapping. One repair attempt, then fail visibly.
    Returns (mapping, attempts) where attempts is a list of (raw_reply, error_or_None)."""
    llm = llm or client()
    model = model or os.getenv('FEATHERLESS_MODEL', DEFAULT_MODEL)
    messages = [{'role': 'user', 'content': _prompt(columns, sample_rows)}]
    attempts = []
    for _ in range(2):
        try:
            r = llm.chat.completions.create(model=model, messages=messages, temperature=0, max_tokens=300)
            text = r.choices[0].message.content
        except Exception as e:  # network, auth, unknown model: counts as a failed attempt
            attempts.append((None, f'API error: {type(e).__name__}: {e}'))
            continue
        try:
            return validate_mapping(text, columns), attempts + [(text, None)]
        except ValueError as e:
            attempts.append((text, str(e)))
            messages += [{'role': 'assistant', 'content': text or ''},
                         {'role': 'user', 'content': f'Invalid: {e}. Reply again with ONLY the corrected JSON object.'}]
    raise RuntimeError(f'column mapping failed twice: {attempts}')
