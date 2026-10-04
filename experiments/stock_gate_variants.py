import numpy as np, pandas as pd, json
exec(open('stock_gate.py').read().split("results = []")[0])  # reuse data prep + forecasts (prints prep info)
def run(vs, Lv, strict, model, win_rate, ratio=0.9, min_active=20):
    ve = vs + Lv; te = ve + 12
    active = (X[:, max(0, vs-52):vs] > 0).sum(axis=1); elig = active >= min_active
    bnames = ['naive','ma4'] if strict else ['naive']
    def errs(n, lo, hi): return np.abs(FC[n][:, lo:hi] - X[:, lo:hi])
    ev = np.stack([errs(n, vs, ve) for n in bnames]); et = np.stack([errs(n, ve, te) for n in bnames])
    bidx = ev.mean(axis=2).argmin(axis=0)
    bev = ev[bidx, np.arange(S)]; bet = et[bidx, np.arange(S)]
    mev = errs(model, vs, ve); met = errs(model, ve, te)
    ok = elig & (bev.mean(1) > 0) & (bet.mean(1) > 0)
    r_val = mev.mean(1) / np.where(bev.mean(1) > 0, bev.mean(1), 1)
    wins = (mev < bev).mean(1)
    gate = ok & (r_val <= ratio) & (wins >= win_rate)
    ref = ok & ~gate
    r_test = met.mean(1) / np.where(bet.mean(1) > 0, bet.mean(1), 1)
    def s(m):
        n = int(m.sum())
        if n == 0: return (0, None, None)
        return (n, round(float((r_test[m] < 1).mean()), 3), round(float(met.mean(1)[m].sum() / bet.mean(1)[m].sum()), 3))
    return dict(scored=int(ok.sum()), gate=s(gate), refused=s(ref), all=s(ok))
rows = []
for strict in (False, True):
  for model in ('ses0.2', 'ma8', 'snaive52'):
    for Lv in (12, 24):
      for name, shift in (('A', 0), ('B', 13), ('C', 26)):
        vs = T - 12 - Lv - shift
        if vs < 52: continue
        r = run(vs, Lv, strict, model, 0.6)
        rows.append(dict(baseline='naive/ma4' if strict else 'naive', model=model, Lv=Lv, fold=name, **{k: v for k, v in r.items()}))
out = pd.DataFrame(rows)
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 200)
print(out.to_string(index=False))
