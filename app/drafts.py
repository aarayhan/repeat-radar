"""Verified follow-up drafts.

Code builds the facts per customer and chooses the message intent (not_due, due, overdue, lapsed) from the days
since the last order and the customer's typical gap. The day count and gap are the owner's reason, shown on screen;
they are never written in the customer message. The LLM only gets the intent, the usual products and the last
order date, and words a short message. Code then checks the draft:
- blocked phrases (BLOCKED_PHRASES) and "drop by" (wholesale customers order remotely), always;
- "miss you / miss working / miss your" unless the intent is overdue or lapsed;
- "enjoying" and "hope you like" when the intent is lapsed (do not assume they still use the product);
- no duration of any kind (digits or words with day/week/month/year; "a while" is allowed);
- a catalogue product that is not one of the customer's usual products is rejected;
- every other number and date must match a fact.
A verified draft is "specific" if it mentions at least one usual product (normalized match, full name or its
first 3 words); otherwise "generic". One repair attempt (temperature 0.7), then a plain template.
"""
import json
import re
import time

BLOCKED_PHRASES = ['discount', '% off', 'percent off', 'free shipping', 'free delivery', 'free gift', 'for free',
                   'free of charge', 'special offer', 'special price', 'limited time', 'in stock', 'back in stock',
                   'only until', 'expires', 'drop by']
MISS_PHRASES = ['miss you', 'miss working', 'miss your']          # allowed only for overdue and lapsed
LAPSED_PHRASES = ['enjoying', 'hope you like']                     # not allowed for lapsed
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
          'november', 'december']
NUMBER_WORDS = ['two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
                'dozen', 'hundred']
DURATION = (r'\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|couple of|few|several|'
            r'many|some|last|past|next)\s+(day|week|month|year)\b')
MIN_PRODUCT_LEN = 8          # shorter catalogue names are too generic to detect as product mentions
TEMP_FIRST, TEMP_REPAIR = 0, 0.7
INTENTS = ('not_due', 'due', 'overdue', 'lapsed')

# Lines that are not physical products (UCI analysis, docs/H2_REPORT.md section 11). Excluded from draft facts only.
NON_PRODUCT_CODES = {'ADJUST', 'ADJUST2', 'AMAZONFEE', 'B', 'BANK CHARGES', 'C2', 'C3', 'CRUK', 'D', 'DOT', 'GIFT',
                     'M', 'm', 'PADS', 'POST', 'S', 'TEST001', 'TEST002', '22016', '23444', '23574', '23595',
                     'DCGS0067', 'DCGS0073'}
NON_PRODUCT_DESCRIPTIONS = {'adjust bad debt', 'amazon fee', 'bank charges', 'carriage', 'next day carriage',
                            'cruk commission', 'discount', 'dotcom postage', 'manual', 'pads to match all cushions',
                            'postage', 'samples', 'this is a test product', 'packing charge', 'ebay'}


def is_non_product(value):
    v = str(value).strip()
    if v in NON_PRODUCT_CODES or v.lower().startswith('gift_0001_'):
        return True
    d = re.sub(r'\s+', ' ', v.lower()).rstrip('.')
    return d in NON_PRODUCT_DESCRIPTIONS or d.startswith(('adjustment', 'dotcomgiftshop gift voucher'))


def usual_products(lines, k=3):
    """lines: one customer's order lines with invoice_id and product. The k products in the most distinct invoices,
    leaving out fees, postage, discounts, adjustments, samples, vouchers and test lines."""
    lines = lines.dropna(subset=['product'])
    lines = lines[~lines['product'].map(is_non_product)]
    counts = lines.drop_duplicates(['invoice_id', 'product'])['product'].value_counts()
    return sorted(counts.index, key=lambda p: (-counts[p], p))[:k]


def sentence_case(name):
    """'WHITE HANGING HEART T-LIGHT HOLDER.' -> 'White hanging heart t-light holder'."""
    s = re.sub(r'\s+', ' ', str(name)).strip().rstrip('.,;:!?- ')
    return s[:1].upper() + s[1:].lower()


def intent_of(days, gap):
    """Message intent from days since the last order and the typical gap (code decides, not the LLM).
    Over 365 days is always 'lapsed'."""
    if days > 365:
        return 'lapsed'
    if gap is None:
        return 'overdue'
    if days < 0.8 * gap:
        return 'not_due'
    if days <= 1.5 * gap:
        return 'due'
    return 'overdue'


def typical_gap(dates):
    """Median days between a customer's orders (None with fewer than 2 orders)."""
    gaps = dates.sort_values().diff().dt.days.dropna()
    return int(round(gaps.median())) if len(gaps) else None


def intents(inv, scored):
    """Intent for every scored customer: score_now's 'recency' and the typical gap from the same invoices."""
    gaps = inv.groupby('customer_id')['date'].apply(typical_gap)
    return [intent_of(int(d), gaps.get(c)) for c, d in zip(scored['customer_id'], scored['recency'])]


def draft_facts(orders, products, customer_id, tier, tier_hit_rate, days_since_last_order):
    """All facts about one customer. days_since_last_order: the value from scoring (audit.score_now 'recency'),
    never recomputed. The LLM sees only llm_facts(...)."""
    dates = orders['date'].sort_values()
    gap = typical_gap(dates)
    if isinstance(customer_id, float) and customer_id.is_integer():
        customer_id = int(customer_id)
    days = int(days_since_last_order)
    return {'customer_id': str(customer_id),
            'last_order': dates.iloc[-1].strftime('%Y-%m-%d'),
            'days_since_last_order': days,
            'typical_gap_days': gap,
            'intent': intent_of(days, gap),
            'usual_products': [sentence_case(p) for p in products],
            'tier': tier,
            'tier_hit_rate_pct': int(round(tier_hit_rate * 100))}


def llm_facts(facts):
    """What the LLM may see: no customer id, no day count, no gap, no tier."""
    return {k: facts[k] for k in ('intent', 'usual_products', 'last_order')}


def template_draft(facts):
    """Plain fallback per intent; None when not due."""
    p = facts['usual_products'][0] if facts['usual_products'] else None
    intent = facts['intent']
    if intent == 'not_due':
        return None
    if intent == 'due':
        return (f'Hi, would you like to restock {p}? ' if p else 'Hi, would you like to place your next order? ') \
            + 'Just reply to this message and we will get your order ready.'
    if intent == 'overdue':
        return 'Hi, we wanted to check in. ' + (f'Would you like to order {p} again? ' if p else
                                                'Would you like to place a new order? ') \
            + 'Just reply to this message and we will get it ready.'
    return ('Hi, we are getting back in touch. ' + (f'You used to order {p} from us. ' if p else '')
            + 'If you would like to order again, just reply to this message.')


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
    same = lambda d, mo, y: (int(d) == last.tm_mday and MONTHS.index(mo) + 1 == last.tm_mon  # noqa: E731
                             and (y is None or int(y) == last.tm_year))
    checks = [
        (r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b',
         lambda m: (int(m[1]), int(m[2]), int(m[3])) == (last.tm_year, last.tm_mon, last.tm_mday)),
        (r'\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b',
         lambda m: int(m[3]) == last.tm_year and {int(m[1]), int(m[2])} == {last.tm_mday, last.tm_mon}),
        (r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?' + month + r'\b(?:,?\s+(\d{4}))?', lambda m: same(m[1], m[2], m[3])),
        (r'\b' + month + r'\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?', lambda m: same(m[2], m[1], m[3])),
        (r'\bmay\s+(\d{4})\b', lambda m: last.tm_mon == 5 and int(m[1]) == last.tm_year),
        (r'\b(' + '|'.join(m for m in MONTHS if m != 'may') + r')\b(?:\s+(\d{4}))?',   # "may" is also a verb
         lambda m: MONTHS.index(m[1]) + 1 == last.tm_mon and (m[2] is None or int(m[2]) == last.tm_year)),
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
    intent = facts['intent']
    problems = [f'blocked phrase: {p!r}' for p in BLOCKED_PHRASES
                if (re.search(r'%\s*off\b', low) if p == '% off' else _has(p, low))]
    if intent not in ('overdue', 'lapsed'):
        problems += [f'not for a {intent} customer: {p!r}' for p in MISS_PHRASES if _has(p, low)]
    if intent == 'lapsed':
        problems += [f'assumes a lapsed customer still uses the product: {p!r}' for p in LAPSED_PHRASES if _has(p, low)]
    allowed = [normalize(p) for p in facts['usual_products']]
    norm_all = normalize(text)
    for name in catalogue:                                   # invented products
        n = normalize(name)
        if len(n) >= MIN_PRODUCT_LEN and _has(n, norm_all) and not any(n in a for a in allowed):
            problems.append(f'product not in the facts: {str(name).strip()!r}')

    last = time.strptime(facts['last_order'], '%Y-%m-%d')
    rest = normalize(_remove_dates(low, last, problems))
    for a in sorted(allowed, key=len, reverse=True):         # product names may contain digits ("set 7 babushka")
        words = a.split()
        for p in [a] + ([' '.join(words[:3])] if len(words) >= 3 else []):
            rest = re.sub(r'(?<![a-z0-9])' + re.escape(p) + r'(?![a-z0-9])', ' ', rest)
    for m in re.finditer(DURATION, rest):
        problems.append(f'duration in the message: {m.group(0)!r}')
    rest = re.sub(DURATION, ' ', rest)
    for w in NUMBER_WORDS:
        if _has(w, rest):
            problems.append(f'number in words: {w!r}')
    for tok in re.findall(r'\d+', rest):
        if tok != str(last.tm_year):
            problems.append(f'number not in the facts: {tok!r}')
    return problems


def is_specific(text, facts):
    """Mentions at least one usual product (normalized, full name or first 3 words)."""
    n = normalize(text)
    return any(_mentions(p, n) for p in facts['usual_products'])


# ---------- LLM draft with one repair ----------

PURPOSE = {'due': 'a friendly restock reminder: their usual reorder time has come',
           'overdue': 'a short check-in: they have not ordered for longer than usual',
           'lapsed': 'a polite re-introduction: they have not ordered in over a year. Do not assume they still use '
                     'or enjoy the products'}


def _prompt(facts):
    return ('Write a short follow-up message (2 or 3 sentences, English) from a small wholesaler to a business '
            f"customer. Purpose: {PURPOSE[facts['intent']]}. Mention at least one product name exactly as written "
            'in the facts. Do not mention how long it has been (no days, weeks, months or years) and do not add any '
            'number, date or product that is not in the facts. Do not mention prices, discounts, offers, free items, '
            'stock or deadlines. Customers order remotely, so do not invite them to drop by.\n'
            'Return ONLY a JSON object: {"message": "<the message>"}\n'
            f'Facts: {json.dumps(llm_facts(facts))}')


def _parse(text):
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f'not valid JSON: {e}')
    if not (isinstance(d, dict) and set(d) == {'message'} and isinstance(d['message'], str)):
        raise ValueError('expected exactly {"message": "<text>"}')
    return d['message']


def llm_draft(facts, client=None, catalogue=()):
    """Returns a dict: text, source ('not_due', 'llm', 'llm_repaired' or 'template'), specific (bool),
    attempts [(raw, problems, temperature)], json_failures, seconds. Not-due customers get no draft (text None).
    client: (OpenAI-compatible client, model) or None."""
    t0, attempts, json_failures = time.time(), [], 0
    if facts['intent'] == 'not_due':
        return {'text': None, 'source': 'not_due', 'specific': False, 'attempts': [], 'json_failures': 0,
                'seconds': 0.0}
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
