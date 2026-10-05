"""Verified follow-up drafts.

Code builds a facts object per customer. The LLM only words a short message from it and never computes anything.
Code then checks every number, date and product name in the draft against the facts, and rejects any promise or
claim the facts do not support (BANNED below). One repair attempt with the verifier's errors, then a plain template.
Reuses the pattern of app/explain.py (LLM wording, code check, template fallback, source label).
"""
import json
import re
import time

import pandas as pd

# Promise or claim words the facts can never support. Fixed before the evaluation; matched case-insensitively,
# as whole words (symbols as plain substrings).
BANNED = ['discount', 'off', 'sale', 'free', 'complimentary', 'gift', 'voucher', 'coupon', 'promo', 'promotion',
          'offer', 'deal', 'deals', 'price', 'prices', 'priced', 'pricing', 'cheap', 'cheaper', 'cost', 'save',
          'saving', 'savings', '£', '$', '€', 'stock', 'restock', 'restocked', 'available', 'availability', 'limited',
          'deadline', 'expire', 'expires', 'expiry', 'last chance', 'hurry', 'until', 'ends', 'guarantee',
          'guaranteed', 'delivery', 'deliver', 'shipping', 'ship', 'new arrival', 'new arrivals', 'exclusive',
          'tomorrow', 'next week', 'this week', 'weekend', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
          'saturday', 'sunday']
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
          'november', 'december']
NUMBER_WORDS = {w: i for i, w in enumerate(['two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
                                            'eleven', 'twelve'], start=2)} | {'dozen': 12, 'hundred': 100}
MIN_PRODUCT_LEN = 8  # shorter catalogue names are too generic to detect as product mentions


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

def _remove(pattern, text, check, problems, what):
    def sub(m):
        if not check(m):
            problems.append(f'{what} not in the facts: {m.group(0).strip()!r}')
        return ' '
    return re.sub(pattern, sub, text, flags=re.IGNORECASE)


def verify(text, facts, catalogue=()):
    """Problems with the draft (empty list = passes). catalogue: all product names known in the data."""
    problems = []
    low = ' ' + (text or '').lower() + ' '
    if not low.strip():
        return ['empty draft']
    for w in BANNED:
        hit = w in low if not w[0].isalnum() else re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', low)
        if hit:
            problems.append(f'promise or claim outside the facts: {w!r}')

    allowed = [p.lower() for p in facts['usual_products']]
    for name in catalogue:                      # invented products
        n = str(name).strip().lower()
        if len(n) >= MIN_PRODUCT_LEN and n in low and not any(n in a for a in allowed):
            problems.append(f'product not in the facts: {name.strip()!r}')
    for a in sorted(allowed, key=len, reverse=True):
        low = low.replace(a, ' ')               # product names may contain digits ("SET OF 3 ...")

    last = pd.Timestamp(facts['last_order'])
    month = r'(' + '|'.join(MONTHS) + r')'
    bare_month = r'\b(' + '|'.join(m for m in MONTHS if m != 'may') + r')\b'   # "may" is also a verb
    same_day = lambda d, mo, y: (int(d) == last.day and MONTHS.index(mo.lower()) + 1 == last.month  # noqa: E731
                                 and (y is None or int(y) == last.year))
    low = _remove(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', low,
                  lambda m: (int(m[1]), int(m[2]), int(m[3])) == (last.year, last.month, last.day), problems, 'date')
    low = _remove(r'\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b', low,
                  lambda m: int(m[3]) == last.year and {int(m[1]), int(m[2])} == {last.day, last.month},
                  problems, 'date')
    low = _remove(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?' + month + r'\b(?:,?\s+(\d{4}))?', low,
                  lambda m: same_day(m[1], m[2], m[3]), problems, 'date')
    low = _remove(r'\b' + month + r'\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?', low,
                  lambda m: same_day(m[2], m[1], m[3]), problems, 'date')
    low = _remove(r'\bmay\s+(\d{4})\b', low, lambda m: last.month == 5 and int(m[1]) == last.year, problems, 'date')
    low = _remove(bare_month + r'(?:\s+(\d{4}))?', low,
                  lambda m: MONTHS.index(m[1].lower()) + 1 == last.month and (m[2] is None or int(m[2]) == last.year),
                  problems, 'date')

    numbers = {facts['days_since_last_order'], facts['tier_hit_rate_pct'], last.year}
    numbers |= {facts['typical_gap_days']} if facts['typical_gap_days'] is not None else set()
    allowed_tokens = {str(n) for n in numbers} | {facts['customer_id']}
    for tok in re.findall(r'\d+(?:[.,]\d+)*', low):
        if tok not in allowed_tokens:
            problems.append(f'number not in the facts: {tok!r}')
    for word, value in NUMBER_WORDS.items():
        if re.search(r'\b' + word + r'\b', low) and value not in numbers:
            problems.append(f'number not in the facts: {word!r}')
    return problems


# ---------- LLM draft with one repair ----------

def _prompt(facts):
    return ('Write a short, friendly follow-up message (2 or 3 sentences, English) from a small wholesaler to this '
            'customer, inviting them to order again. Use ONLY these facts. Do not calculate anything. Do not add any '
            'number, date or product that is not in the facts. Do not mention prices, discounts, offers, free items, '
            'stock, delivery or deadlines. Do not mention the tier or the hit rate; they are internal.\n'
            'Return ONLY a JSON object: {"message": "<the message>"}\n'
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
    """Returns a dict: text, source ('llm', 'llm_repaired' or 'template'), attempts [(raw, problems)],
    json_failures, seconds. client: (OpenAI-compatible client, model) or None."""
    t0, attempts, json_failures = time.time(), [], 0
    if client is not None:
        llm, model = client
        messages = [{'role': 'user', 'content': _prompt(facts)}]
        for attempt in range(2):
            try:
                r = llm.chat.completions.create(model=model, messages=messages, temperature=0, max_tokens=250)
                raw = r.choices[0].message.content
            except Exception as e:  # network, auth, rate limit: fall back, never break the screen
                attempts.append((None, [f'API error: {type(e).__name__}']))
                break
            try:
                problems = verify(_parse(raw), facts, catalogue)
            except ValueError as e:
                json_failures += 1
                problems = [str(e)]
            attempts.append((raw, problems))
            if not problems:
                return {'text': _parse(raw), 'source': 'llm' if attempt == 0 else 'llm_repaired',
                        'attempts': attempts, 'json_failures': json_failures, 'seconds': time.time() - t0}
            messages += [{'role': 'assistant', 'content': raw or ''},
                         {'role': 'user', 'content': 'Your draft failed these checks: ' + '; '.join(problems)
                          + '. Rewrite it using only the facts. Return ONLY the JSON object {"message": "..."}.'}]
    return {'text': template_draft(facts), 'source': 'template', 'attempts': attempts,
            'json_failures': json_failures, 'seconds': time.time() - t0}
