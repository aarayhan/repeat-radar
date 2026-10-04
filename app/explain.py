"""Why a customer is on the list, and a draft follow-up message. Facts come from code; the LLM only words them.

Only one customer's facts are ever sent to the LLM. Its answer is checked in code: every invoice number it
mentions must be one of this customer's, and it must mention at least one. Otherwise the template is used.
Every text function returns (text, source) with source 'llm' or 'template'.
"""
import json
import re

import pandas as pd

LANGS = {'en': 'English', 'id': 'Indonesian'}


def customer_facts(orders, tier, as_of):
    """orders: this customer's invoices (invoice_id, date, amount). tier: from audit.score_now.
    as_of: the date the list was made (score_now uses the day after the last order in the file)."""
    o = orders.sort_values('date')
    gaps = o['date'].diff().dt.days.dropna()
    last = o.iloc[::-1].head(3)
    return {
        'tier': tier,
        'n_orders': len(o),
        'last_order': o['date'].iloc[-1].strftime('%Y-%m-%d'),
        'days_since_last': int((pd.Timestamp(as_of) - o['date'].iloc[-1]).days),
        'avg_days_between_orders': round(float(gaps.mean()), 1) if len(gaps) else None,
        'last_orders': [{'invoice_id': str(r.invoice_id), 'date': r.date.strftime('%Y-%m-%d'),
                         'amount': round(float(r.amount), 2)} for r in last.itertuples()],
    }


def template_explanation(facts, lang='en'):
    f, o = facts, facts['last_orders'][0]
    gap = f['avg_days_between_orders']
    if lang == 'id':
        text = (f"Tier {f['tier']}. {f['n_orders']} pesanan; terakhir nota {o['invoice_id']} pada {o['date']}, "
                f"{f['days_since_last']} hari yang lalu."
                + (f" Rata-rata {gap} hari antar pesanan." if gap is not None else ''))
    else:
        text = (f"{f['tier'].capitalize()} tier. {f['n_orders']} orders; the last one was invoice {o['invoice_id']} "
                f"on {o['date']}, {f['days_since_last']} day{'' if f['days_since_last'] == 1 else 's'} ago."
                + (f" On average {gap} days between orders." if gap is not None else ''))
    return text, 'template'


def template_message(facts, lang='en'):
    o = facts['last_orders'][0]
    if lang == 'id':
        text = (f"Halo, terima kasih atas pesanan Anda (nota {o['invoice_id']}, {o['date']}). "
                "Apakah ada yang bisa kami siapkan untuk pesanan berikutnya?")
    else:
        text = (f"Hi, thank you for your order (invoice {o['invoice_id']}, {o['date']}). "
                "Is there anything we can prepare for your next order?")
    return text, 'template'


def _mentioned_ids(text, known):
    """Tokens in the text shaped like this customer's invoice numbers (same letters, same digit count)."""
    shapes = {''.join(r'\d' if ch.isdigit() else re.escape(ch) for ch in k) for k in known}
    pattern = r'(?<![A-Za-z0-9])(?:' + '|'.join(sorted(shapes)) + r')(?![0-9])'
    return set(re.findall(pattern, text))


def check_citations(text, facts):
    """Every invoice number mentioned must be one of the customer's, and at least one must be mentioned."""
    known = {o['invoice_id'] for o in facts['last_orders']}
    found = _mentioned_ids(text or '', known)
    return bool(found) and found <= known


def llm_explanation(facts, lang='en', client=None):
    """client: (OpenAI-compatible client, model) as returned by app.llm.client(), or None."""
    if client is None:
        return template_explanation(facts, lang)
    llm, model = client
    prompt = (f"In {LANGS[lang]}, write two short sentences for a sales person explaining why this customer "
              f"is in the '{facts['tier']}' tier of the follow-up list. Use only these facts and do not add numbers "
              f"that are not in them. Cite at least one invoice number exactly as written.\n"
              f"Facts: {json.dumps(facts)}")
    try:
        r = llm.chat.completions.create(model=model, messages=[{'role': 'user', 'content': prompt}],
                                        temperature=0, max_tokens=200)
        text = (r.choices[0].message.content or '').strip()
    except Exception:  # network, auth, model: fall back, never break the screen
        return template_explanation(facts, lang)
    return (text, 'llm') if check_citations(text, facts) else template_explanation(facts, lang)
