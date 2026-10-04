import pandas as pd, time
t=time.time()
x = pd.read_excel('online_retail_II.xlsx', sheet_name=None, engine='openpyxl')
print({k:v.shape for k,v in x.items()}, time.time()-t, flush=True)
df = pd.concat(x.values(), ignore_index=True)
df.to_csv('retail.csv', index=False)
print(df.shape, df.columns.tolist(), flush=True)
print('done', time.time()-t, flush=True)
