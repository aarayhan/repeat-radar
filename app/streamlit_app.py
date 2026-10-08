"""Repeat Radar UI: 1. Upload and confirm columns, 2. Customers, 3. Audit, 4. Results on real shop data.

Each screen is in app/screens/. Files are processed in memory only (never written to disk, never logged).
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `streamlit run app/streamlit_app.py` puts app/ on the path, not the repo root
from app.screens.audit import screen_audit  # noqa: E402
from app.screens.common import mapping_confirmed, secrets_to_env  # noqa: E402
from app.screens.customers import screen_customers  # noqa: E402
from app.screens.evidence import screen_evidence  # noqa: E402
from app.screens.upload import screen_upload  # noqa: E402

SCREENS = ['1. Upload', '2. Customers', '3. Audit', '4. Results on real shop data']
CSS = (ROOT / 'app' / 'style.css').read_text(encoding='utf-8')


def main():
    st.set_page_config(page_title='Repeat Radar', layout='wide')
    secrets_to_env()
    st.markdown(f'<style>{CSS}</style>', unsafe_allow_html=True)
    ready = mapping_confirmed()
    st.sidebar.markdown('<p class="rr-brand" style="font-size:1.5rem;margin:0">Repeat Radar</p>',
                        unsafe_allow_html=True)
    st.sidebar.caption('Who is likely to order again within 8 weeks, and how often that was right before.')
    status = {SCREENS[0]: 'start here' if not ready else 'done', SCREENS[1]: 'ready' if ready else 'locked',
              SCREENS[2]: 'ready' if ready else 'locked', SCREENS[3]: 'always open'}
    # The labels must never change: a browser stores the chosen label and sends it back on every rerun, and a label
    # that no longer matches makes Streamlit fall back to step 1. The status changes, so it goes in the captions.
    screen = st.sidebar.radio('Steps', SCREENS, key='screen', captions=[status[s] for s in SCREENS])
    st.sidebar.caption(f'You are on step {SCREENS.index(screen) + 1} of {len(SCREENS)}.'
                       + ('' if ready else ' Steps 2 and 3 unlock after you confirm the column mapping.'))
    try:
        {SCREENS[0]: screen_upload, SCREENS[1]: screen_customers, SCREENS[2]: screen_audit,
         SCREENS[3]: screen_evidence}[screen]()
    except Exception as e:  # never show a traceback
        st.error(f'Something went wrong: {type(e).__name__}: {e}')

main()
