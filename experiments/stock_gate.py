"""Gate experiment: does 'recommend only if it beat a naive baseline in a rolling backtest' hold up out of sample?
Data: UCI Online Retail II (weekly units per product). Horizon = 1 week. Metric = MAE in units.
"""
import numpy as np, pandas as pd, re, sys, json

df = pd.read_csv('retail.csv', parse_dates=['InvoiceDate'])
print('rows raw', len(df))
df['Invoice'] = df['Invoice'].astype(str)
n_cancel = df['Invoice'].str.startswith('C').sum()
df = df[~df['Invoice'].str.startswith('C')]
df = df[(df['Quantity'] > 0) & (df['Price'] > 0)]
df['StockCode'] = df['StockCode'].astype(str)
is_prod = df['StockCode'].str.match(r'^\d{5}[A-Za-z]{0,2}$')
print('cancel rows', n_cancel, 'non-product rows dropped', (~is_prod).sum())
df = df[is_prod]
df['week'] = (df['InvoiceDate'] - pd.to_timedelta(df['InvoiceDate'].dt.weekday, unit='D')).dt.normalize()
wk = sorted(df['week'].unique())
wk = wk[1:-1]  # drop partial first and last week
df = df[df['week'].isin(wk)]
widx = {w: i for i, w in enumerate(wk)}
df['wi'] = df['week'].map(widx)
T = len(wk)
print('weeks', T, wk[0], wk[-1])
M = df.pivot_table(index='StockCode', columns='wi', values='Quantity', aggfunc='sum', fill_value=0)
M = M.reindex(columns=range(T), fill_value=0)
X = M.values.astype(float)
S = X.shape[0]
print('SKUs', S)

# ---- forecasts for week t using data < t ----
def f_naive():
    F = np.full_like(X, np.nan); F[:, 1:] = X[:, :-1]; return F
def f_ma(k):
    F = np.full_like(X, np.nan)
    for t in range(k, T): F[:, t] = X[:, t-k:t].mean(axis=1)
    return F
def f_ses(a):
    F = np.full_like(X, np.nan); lvl = X[:, 0].copy()
    for t in range(1, T):
        F[:, t] = lvl
        lvl = a * X[:, t] + (1 - a) * lvl
    return F
def f_snaive(p=52):
    F = np.full_like(X, np.nan); F[:, p:] = X[:, :-p]; return F

FC = {'naive': f_naive(), 'ma4': f_ma(4), 'ma8': f_ma(8), 'ses0.2': f_ses(0.2), 'ses0.5': f_ses(0.5), 'snaive52': f_snaive(52)}

def mae(F, lo, hi):
    return np.nanmean(np.abs(F[:, lo:hi] - X[:, lo:hi]), axis=1) if False else np.abs(F[:, lo:hi] - X[:, lo:hi]).mean(axis=1)

def run_fold(vs, name, strict, ratio=0.9, min_active=20):
    ve, te = vs + 12, vs + 24
    # eligibility: sold in >= min_active of the 52 weeks before validation start
    active = (X[:, max(0, vs-52):vs] > 0).sum(axis=1)
    elig = active >= min_active
    base_names = ['naive'] if not strict else ['naive', 'ma4']
    cand_names = [n for n in FC if n not in base_names] if strict else [n for n in FC if n != 'naive']
    # drop snaive when not enough history
    use_sn = vs - 52 >= 0
    if not use_sn and 'snaive52' in cand_names: cand_names.remove('snaive52')
    # baseline chosen on validation
    bv = np.stack([mae(FC[n], vs, ve) for n in base_names], axis=1)
    bidx = bv.argmin(axis=1)
    base_val = bv.min(axis=1)
    bt = np.stack([mae(FC[n], ve, te) for n in base_names], axis=1)
    base_test = bt[np.arange(S), bidx]
    cv = np.stack([mae(FC[n], vs, ve) for n in cand_names], axis=1)
    cidx = cv.argmin(axis=1)
    cand_val = cv.min(axis=1)
    ct = np.stack([mae(FC[n], ve, te) for n in cand_names], axis=1)
    cand_test = ct[np.arange(S), cidx]
    ok = elig & (base_val > 0) & (base_test > 0)
    r_val = np.where(ok, cand_val / np.where(base_val > 0, base_val, 1), np.nan)
    r_test = np.where(ok, cand_test / np.where(base_test > 0, base_test, 1), np.nan)
    gate = ok & (r_val <= ratio)
    ref = ok & ~gate
    units = X[:, ve:te].sum(axis=1)
    def summ(mask):
        n = int(mask.sum())
        if n == 0: return dict(n=0)
        rt = r_test[mask]
        return dict(n=n,
                    beat_baseline=float((rt < 1).mean()),
                    beat_by_10pct=float((rt <= 0.9).mean()),
                    median_ratio=float(np.median(rt)),
                    agg_ratio=float(cand_test[mask].sum() / base_test[mask].sum()),
                    worse_by_10pct=float((rt > 1.1).mean()))
    out = dict(fold=name, val_weeks=[vs, ve], test_weeks=[ve, te],
               test_dates=[str(wk[ve].date()), str(wk[te-1].date())],
               baseline='best of naive/ma4' if strict else 'naive (same as last week)',
               n_sku_total=int(S), n_eligible=int(elig.sum()), n_scored=int(ok.sum()),
               gate_pass=summ(gate), refused=summ(ref), all_scored=summ(ok))
    return out

results = []
# fold A: test = last 12 weeks; fold B: 12 weeks ending 26 weeks earlier; fold C: ending 13 weeks earlier
for strict in (False, True):
    for name, shift in (('A_last12', 0), ('B_13wk_earlier', 13), ('C_26wk_earlier', 26)):
        vs = T - 24 - shift
        results.append(run_fold(vs, name, strict))
print(json.dumps(results, indent=1))
json.dump(results, open('results.json', 'w'), indent=1)
