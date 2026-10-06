"""Verified follow-up drafts.

Code builds a facts object per customer. The LLM only words a short message from it and never computes anything.
Code then checks the draft against the facts:
- blocked phrases (BLOCKED_PHRASES, case-insensitive, word boundaries);
- products: a catalogue product that is not one of the customer's usual products is rejected;
- day counts: if present, written as digits and equal to the exact integer in the facts; worded day counts
  ("three weeks", "a month") and converted units ("3 weeks") are rejected;
- every other number and date must equal a fact.
A verified draft is "specific" if it mentions a usual product (normalized: lowercase, no punctuation, simple
plural; full name or its first 3 words) or the exact day count; otherwise "generic".
One repair attempt (temperature 0.7) with the verifier's errors, then a plain template. Same pattern as app/explain.py.
"""
import json
import re
import time

import pandas as pd

BLOCKED_PHRASES = ['discount', '% off', 'percent off', 'free shipping', 'free delivery', 'free gift', 'for free',
                   'free of charge', 'special offer', 'special price', 'limited time', 'in stock', 'back in stock',
                   'only until', 'expires']
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
          'november', 'december']
NUMBER_WORDS = ['two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
                'dozen', 'hundred']
WORDED_SPAN = (r'\b(a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|couple of|few|several)'
               r'\s+(day|week|month|year)\b')
MIN_PRODUCT_LEN = 8          # shorter catalogue names are too generic to detect as product mentions
TEMP_FIRST, TEMP_REPAIR = 0, 0.7


def usual_products(lines, k=3):
    """lines: one customer's order lines with invoice_id and product. The k products in the most distinct invoices."""
    counts = lines.dropna(subset=['product']).drop_duplicates(['invoice_id', 'product'])['product'].value_counts()
    return sorted(counts.index, key=lambda p: (-counts[p], p))[:k]


def draft_facts(orders, products, customer_id, tier, tier_hit_rate, as_of):
    """The only facts a draft may use. orders: this customer's invoices (date). products: usual_products(...).
    tier_hit_rate: the tier's measured share who ordered again (0-1). as_of: the date the list was made."""
    dates = orders['date'].sort_values()
    gaps = dates.diff().dt.days.dropna()
    if isinstance(customer_id, float) and customer_id.is_integer():
        customer_id = int(customer_id)
    return {'customer_id': str(customer_id),
            'last_order': dates.iloc[-1].strftime('%Y-%m-%d'),
            'days_since_last_order': int((pd.Timestamp(as_of) - dates.iloc[-1]).days),
            'usual_products': [str(p).strip() for p in products],
            'typical_gap_days': int(round(gaps.median())) if len(gaps) else None,
            'tier': tier,
            'tier_hit_rate_pct': int(round(tier_hit_rate * 100))}


def template_draft(facts):
    product = facts['usual_products'][0] if facts['usual_products'] else None
    return (f"Hi, it has been {facts['days_since_last_order']} days since your last order on {facts['last_order']}. "
            + (f'Would you like to order {product} again? ' if product else 'Would you like to place a new order? ')
            + 'Just reply to this message and we will get it ready.')


# ---------- verifier ----------

def normalize(s):
    """Lowercase, punctuation to spaces, simple plural 's' removed (not from 'ss' or words of 3 letters or less)."""
    words = re.sub(r'[^a-z0-9%]+', ' ', str(s).lower()).split()
    return ' '.join(w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w for w in words)


def _has(phrase, text):
    return re.search(r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])', text) is not None


def _mentions(product, norm_text):
    p = normalize(product).split()
    return bool(p) and (_has(' '.join(p), norm_text) or (len(p) >= 3 and _has(' '.join(p[:3]), norm_text)))


def _remove_dates(text, last, problems):
    """Find dates in lowercase text; each must be the last order date. Returns the text without them."""
    month = r'(' + '|'.join(MONTHS) + r')'
    same = lambda d, mo, y: (int(d) == last.day and MONTHS.index(mo) + 1 == last.month  # noqa: E731
                             and (y is None or int(y) == last.year))
    checks = [
        (r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b',
         lambda m: (int(m[1]), int(m[2]), int(m[3])) == (last.year, last.month, last.day)),
        (r'\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b',
         lambda m: int(m[3]) == last.year and {int(m[1]), int(m[2])} == {last.day, last.month}),
        (r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?' + month + r'\b(?:,?\s+(\d{4}))?', lambda m: same(m[1], m[2], m[3])),
        (r'\b' + month + r'\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?', lambda m: same(m[2], m[1], m[3])),
        (r'\bmay\s+(\d{4})\b', lambda m: last.month == 5 and int(m[1]) == last.year),
        (r'\b(' + '|'.join(m for m in MONTHS if m != 'may') + r')\b(?:\s+(\d{4}))?',   # "may" is also a verb
         lambda m: MONTHS.index(m[1]) + 1 == last.month and (m[2] is None or int(m[2]) == last.year)),
    ]
    for pattern, ok in checks:
        def sub(m, ok=ok):
            if not ok(m):
                problems.append(f'date not in the facts: {m.group(0).strip()!r}')
            return ' '
        text = re.sub(pattern, sub, text)
    return text


def verify(text, facts, catalogue=()):
    """Problems with the draft (empty list = verified). catalogue: all product names known in the data."""
    if not (text or '').strip():
        return ['empty draft']
    low = text.lower()
    problems = [f'blocked phrase: {p!r}' for p in BLOCKED_PHRASES
                if (re.search(r'%\s*off\b', low) if p == '% off' else _has(p, low))]
    allowed = [normalize(p) for p in facts['usual_products']]
    norm_all = normalize(text)
    for name in catalogue:                                   # invented products
        n = normalize(name)
        if len(n) >= MIN_PRODUCT_LEN and _has(n, norm_all) and not any(n in a for a in allowed):
            problems.append(f'product not in the facts: {str(name).strip()!r}')

    rest = normalize(_remove_dates(low, pd.Timestamp(facts['last_order']), problems))
    for a in sorted(allowed, key=len, reverse=True):         # product names may contain digits ("set 7 babushka")
        words = a.split()
        for p in [a] + ([' '.join(words[:3])] if len(words) >= 3 else []):
            rest = re.sub(r'(?<![a-z0-9])' + re.escape(p) + r'(?![a-z0-9])', ' ', rest)

    days, gap = facts['days_since_last_order'], facts['typical_gap_days']
    for m in re.finditer(WORDED_SPAN, rest):
        problems.append(f'day count in words: {m.group(0)!r}')
    rest = re.sub(WORDED_SPAN, ' ', rest)
    for m in re.finditer(r'\b(\d+)\s+(week|month|year)\b', rest):
        problems.append(f'converted unit, not the day count: {m.group(0)!r}')
    for m in re.finditer(r'\b(\d+)\s+day\b', rest):
        if int(m[1]) not in {days, gap}:
            problems.append(f'day count not in the facts: {m.group(0)!r} (facts: {days})')
    rest = re.sub(r'\b\d+\s+(day|week|month|year)\b', ' ', rest)
    for w in NUMBER_WORDS:
        if _has(w, rest):
            problems.append(f'number in words: {w!r}')
    allowed_numbers = {str(days), str(facts['tier_hit_rate_pct']), str(pd.Timestamp(facts['last_order']).year),
                       facts['customer_id']} | ({str(gap)} if gap is not None else set())
    for tok in re.findall(r'\d+', rest):
        if tok not in allowed_numbers:
            problems.append(f'number not in the facts: {tok!r}')
    return problems


def is_specific(text, facts):
    """Mentions a usual product (normalized, full name or first 3 words) or the exact day count as digits."""
    n = normalize(text)
    return any(_mentions(p, n) for p in facts['usual_products']) or _has(str(facts['days_since_last_order']), n)


# ---------- LLM draft with one repair ----------

def _prompt(facts):
    return ('Write a short, friendly follow-up message (2 or 3 sentences, English) from a small wholesaler to this '
            'customer, inviting them to order again. Use ONLY these facts and do not calculate anything. '
            f"Include the exact day count ({facts['days_since_last_order']} days, written as digits) and at least "
            'one product name exactly as written in the facts. Do not add any other number, date or product. '
            'Do not mention prices, discounts, offers, free items, stock or deadlines. Do not mention the tier or '
            'the hit rate; they are internal.\nReturn ONLY a JSON object: {"message": "<the message>"}\n'
            f'Facts: {json.dumps(facts)}')


def _parse(text):
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f'not valid JSON: {e}')
    if not (isinstance(d, dict) and set(d) == {'message'} and isinstance(d['message'], str)):
        raise ValueError('expected exactly {"message": "<text>"}')
    return d['message']


def llm_draft(facts, client=None, catalogue=()):
    """Returns a dict: text, source ('llm', 'llm_repaired' or 'template'), specific (bool),
    attempts [(raw, problems, temperature)], json_failures, seconds. client: (OpenAI-compatible client, model) or None."""
    t0, attempts, json_failures = time.time(), [], 0
    if client is not None:
        llm, model = client
        messages = [{'role': 'user', 'content': _prompt(facts)}]
        for attempt, temperature in enumerate((TEMP_FIRST, TEMP_REPAIR)):
            try:
                r = llm.chat.completions.create(model=model, messages=messages, temperature=temperature,
                                                max_tokens=250)
                raw = r.choices[0].message.content
            except Exception as e:  # network, auth, rate limit: fall back, never break the screen
                attempts.append((None, [f'API error: {type(e).__name__}'], temperature))
                break
            try:
                message = _parse(raw)
                problems = verify(message, facts, catalogue)
            except ValueError as e:
                json_failures += 1
                message, problems = None, [str(e)]
            attempts.append((raw, problems, temperature))
            if not problems:
                return {'text': message, 'source': 'llm' if attempt == 0 else 'llm_repaired',
                        'specific': is_specific(message, facts), 'attempts': attempts,
                        'json_failures': json_failures, 'seconds': time.time() - t0}
            messages += [{'role': 'assistant', 'content': raw or ''},
                         {'role': 'user', 'content': 'Your draft failed these checks: ' + '; '.join(problems)
                          + '. Rewrite it using only the facts. Return ONLY the JSON object {"message": "..."}.'}]
    text = template_draft(facts)
    return {'text': text, 'source': 'template', 'specific': is_specific(text, facts), 'attempts': attempts,
            'json_failures': json_failures, 'seconds': time.time() - t0}
