"""Column mapping by LLM (any OpenAI-compatible provider, chosen by LLM_PROVIDER). Output is validated in code."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

REQUIRED = ('customer_id', 'invoice_id', 'date', 'quantity', 'price')
OPTIONAL = ('country', 'product')
PROVIDERS = {  # name -> (base_url, env var holding the key; None = no key needed)
    'featherless': ('https://api.featherless.ai/v1', 'FEATHERLESS_API_KEY'),
    'openai': ('https://api.openai.com/v1', 'OPENAI_API_KEY'),
    'openrouter': ('https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY'),
    'ollama': ('http://localhost:11434/v1', None),
}
DEFAULT_MODELS = {'featherless': 'Qwen/Qwen2.5-7B-Instruct'}  # others need LLM_MODEL


class LLMUnavailable(RuntimeError):
    """No usable provider configured. Callers fall back to rule-based mapping."""


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
    """(OpenAI-compatible client, model) for LLM_PROVIDER (default featherless). Raises LLMUnavailable."""
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    name = os.getenv('LLM_PROVIDER', 'featherless').strip().lower()
    if name not in PROVIDERS:
        raise LLMUnavailable(f'unknown LLM_PROVIDER {name!r}; use one of {sorted(PROVIDERS)}')
    url, key_env = PROVIDERS[name]
    key = os.getenv(key_env) if key_env else 'not-needed'
    if not key:
        raise LLMUnavailable(f'{key_env} is not set (.env)')
    model = os.getenv('LLM_MODEL') or DEFAULT_MODELS.get(name)
    if not model:
        raise LLMUnavailable(f'LLM_MODEL is not set for provider {name!r}')
    return OpenAI(base_url=url, api_key=key), model


def map_columns(columns, sample_rows, llm=None, model=None):
    """Ask the LLM for a mapping. One repair attempt, then fail visibly.
    Returns (mapping, attempts) where attempts is a list of (raw_reply, error_or_None)."""
    if llm is None:
        llm, model = client()
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
