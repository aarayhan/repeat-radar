import numpy as np, pandas as pd
exec(open('stock_gate.py').read().split("results = []")[0])
pd.set_option('display.width', 250)
F = FC['ses0.2']
# ---------- Test 1: interval coverage (nominal 80%) ----------
def coverage(ts, te_, win=26, min_active=20, qlo=10, qhi=90):
    rows = []
    for name, (lo_t, hi_t) in ts.items():
        active = (X[:, max(0, lo_t-52):lo_t] > 0).sum(axis=1)
        elig = (active >= min_active) & (X[:, lo_t-52:lo_t].mean(axis=1) > 0)
        inside = []; width = []; lvl = []
        for t in range(lo_t, hi_t):
            res = (X[:, t-win:t] - F[:, t-win:t])
            q = np.percentile(res, [qlo, qhi], axis=1)
            lo = np.maximum(F[:, t] + q[0], 0); hi = F[:, t] + q[1]
            inside.append((X[:, t] >= lo) & (X[:, t] <= hi)); width.append(hi - lo); lvl.append(X[:, t])
        inside = np.array(inside).T; width = np.array(width).T; lvl = np.array(lvl).T
        cov_all = inside[elig].mean()
        # by activity bucket
        b = pd.cut(active[elig], [19, 29, 39, 52], labels=['20-29', '30-39', '40-52'])
        cb = pd.Series(inside[elig].mean(axis=1)).groupby(b).mean().round(3).to_dict()
        # share of SKUs whose own coverage is within 65-95%
        per = inside[elig].mean(axis=1)
        rows.append(dict(window=name, n_sku=int(elig.sum()), coverage=round(float(cov_all), 3),
                         by_active_weeks={k: v for k, v in cb.items()},
                         sku_share_cov_65_95=round(float(((per >= .65) & (per <= .95)).mean()), 3),
                         median_width_over_mean_level=round(float(np.median(width[elig].mean(axis=1) / np.maximum(lvl[elig].mean(axis=1), 1e-9))), 2)))
    return rows
wins = {'A_Sep-Nov2011': (T-12, T), 'B_Jun-Aug2011': (T-25, T-13), 'C_Mar-May2011': (T-38, T-26)}
print('=== Test 1: coverage of 80% interval (SES0.2, residual quantiles from prior 26 weeks) ===')
for r in coverage(wins, None): print(r)
# ---------- Test 2: aggregate level ----------
print('=== Test 2: aggregate weekly units, error vs baselines (MAE ratio; <1 = better) ===')
def agg_eval(series_name, mask):
    y = X[mask].sum(axis=0)
    out = []
    for wname, (lo, hi) in wins.items():
        errs = {}
        for m, Fm in FC.items():
            f = Fm[mask].sum(axis=0)
            errs[m] = np.abs(f[lo:hi] - y[lo:hi]).mean()
        base = min(errs['naive'], errs['ma4'])
        out.append(dict(series=series_name, window=wname, **{m: round(v/base, 2) for m, v in errs.items()}, level=int(y[lo:hi].mean())))
    return out
tot = X.sum(axis=1)
eligA = (X[:, T-76:T-24] > 0).sum(axis=1) >= 20
top100 = np.zeros(S, bool); top100[np.argsort(-tot)[:100]] = True
top500 = np.zeros(S, bool); top500[np.argsort(-tot)[:500]] = True
allm = np.ones(S, bool)
res = []
for n, m in (('all products', allm), ('top500 products', top500), ('top100 products', top100)): res += agg_eval(n, m)
print(pd.DataFrame(res).to_string(index=False))
