"""Frontend <-> backend smoke test (needs the FastAPI backend running on BACKEND_URL).

    python tests/frontend_smoke.py

Runs every Streamlit page headlessly with streamlit.testing.AppTest and fails if a page raises
an exception or shows a backend error. Not part of the pytest suite because it needs a live backend.
"""
from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
sys.path.insert(0, str(FRONTEND))
PAGES = sorted((FRONTEND / "pages").glob("*.py"))


def run_page(path: Path) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=180)
    at.session_state["include_synthetic"] = True
    return at.run()


def main() -> int:
    failures = 0
    home = AppTest.from_file(str(FRONTEND / "streamlit_app.py"), default_timeout=180).run()
    print(f"streamlit_app.py: exceptions={len(home.exception)} sidebar_success={[s.value[:60] for s in home.sidebar.success]}")
    failures += len(home.exception)
    for p in PAGES:
        at = run_page(p)
        errors = [e.value for e in at.error]
        print(f"{p.name:32s} exceptions={len(at.exception)} errors={errors[:2]} markdown_blocks={len(at.markdown)} "
              f"dataframes={len(at.dataframe)}")
        failures += len(at.exception) + len(errors)
    # chatbot interaction through the real backend
    at = run_page(FRONTEND / "pages" / "4_RiceRate_AI_Chatbot.py")
    at.chat_input[0].set_value("Aaj Multan mein 1121 paddy ka latest available rate kya hai?").run()
    answers = [m.value for m in at.markdown if "Multan" in str(m.value) and "PKR" in str(m.value)]
    print("chatbot answer received:", bool(answers), "| exceptions:", len(at.exception))
    failures += (0 if answers else 1) + len(at.exception)
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
