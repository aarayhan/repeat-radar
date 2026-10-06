# Deploy to Streamlit Community Cloud

These steps are for the owner. Nothing here has been run yet: no push, no deploy.

## What gets deployed
- **App:** `app/streamlit_app.py`. Dependencies are pinned in `requirements.txt`; it was built and tested on Python 3.13.
- **Demo data:** the two synthetic sample files in `app/sample_data/`, made-up customers and committed (about 0.7 MB).
- **Not deployed:**
  - The UCI dataset and everything in `data/` is gitignored. The UCI numbers in the README cannot be reproduced on the deployed app; they come from `scripts/` run locally.
  - The API key is never in git. On the cloud it comes from Streamlit secrets; locally from `.env`.

## Before you deploy
1. Review `h2-trust`. If it is good, push it, and push `main` (the local `main` is already fast-forwarded to `h2-trust`):
   ```
   git push origin h2-trust
   git push origin main
   ```
2. Check nothing secret or private is tracked; both commands must print nothing:
   ```
   git ls-files | grep -E '(^|/)\.env$|\.streamlit/secrets\.toml'
   git ls-files data/ | grep -vE '^data/(README\.md|\.gitkeep)$'
   ```

## Deploy
1. Go to https://share.streamlit.io and sign in with the GitHub account that owns `aarayhan/repeat-radar`.
2. Click **Create app**, then choose to deploy from a GitHub repository.
3. Fill in:
   - Repository: `aarayhan/repeat-radar`
   - Branch: `main`
   - Main file path: `app/streamlit_app.py`
   - App URL: any free name, for example `repeat-radar`
4. Open **Advanced settings**:
   - Python version: **3.13**
   - Secrets: paste the following, with your real key between the quotes:
     ```toml
     FEATHERLESS_API_KEY = "paste-your-key-here"
     LLM_SESSION_CAP = "20"
     LLM_DAILY_CAP = "500"
     ```
     `LLM_SESSION_CAP` (per session, default 20) and `LLM_DAILY_CAP` (whole app per day, default 500) are optional.

     To use another provider instead, set `LLM_PROVIDER` (`openai`, `openrouter`), `LLM_MODEL`, and that provider's key (`OPENAI_API_KEY` or `OPENROUTER_API_KEY`).
5. Click **Deploy** and wait for the build to finish (a few minutes the first time).

## Check the deployed app (clean browser window)
1. Click **Use sample data** with "E-commerce (synthetic)", then **Confirm mapping**.
2. Open **2. Customers**. Check that:
   - "Counted as of ..." appears above the table;
   - choosing a customer whose next step is not "Not due yet" shows a draft with "Message source: llm" and the "Checked by code" note.
3. Open **3. Audit** and check that the window table and the tier sentence appear.
4. Optional: remove the key from the secrets and reboot. The app must still work, using built-in rules and templates.

## How the key is protected
- The key is read from Streamlit secrets (`st.secrets`). The app copies known keys into the environment at start; locally it reads `.env` instead. No key is in the code; a test checks this.
- Each session may make at most `LLM_SESSION_CAP` LLM requests (default 20). A file's column mapping, a customer's explanation and a customer's draft each count once; a draft with its one repair counts as one request (up to 2 API calls).
- The whole app may make at most `LLM_DAILY_CAP` LLM requests per day (default 500), counted in server memory. The count resets when the app restarts or the server date changes.
- When either limit is reached, the app says so and uses built-in rules and templates. When the key is missing or the provider fails, the same fallbacks are used.
- Caching (`st.cache_data`) is in server memory and shared across sessions, keyed by the file's content hash. A repeated request can be served without a new API call.
- Featherless limits concurrent calls. Under load some requests may fail; those fall back to templates.
- If the key ever leaks: revoke it in the Featherless dashboard, create a new one, and update the Streamlit secrets.

## Data handling on the deployed app
- Uploaded files are processed in memory and never written to disk by the app.
- When an LLM is used, the column names plus 3 sample rows (mapping), and one customer's facts (explanation and draft) are sent to the LLM provider. No whole file is sent.
- The app is public once deployed. Do not upload real customer data to a public demo.
