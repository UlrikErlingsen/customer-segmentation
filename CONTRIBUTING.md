# Contributing

Contributions that make SegmentSignal clearer, safer, more accurate, or easier for marketers are welcome.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest
python -m streamlit run app.py
```

On Windows, activate with `.venv\Scripts\activate`.

## Design rules

- Keep statistical and data logic in typed, testable functions under `src/segmentsignal/`; do not import Streamlit there.
- Use plain-language error messages with a concrete next action.
- Preserve row counts and customer IDs through every pipeline.
- Do not present one cluster metric, method, or segment count as universally correct.
- Add a synthetic reference or independently derived test for every statistical change.
- Never add telemetry or persistent upload storage without an explicit public design discussion.
- Do not use real customer or personal data in issues, examples, tests, or screenshots.

Open a focused pull request and describe the user problem, methodological effect, tests, and any new limitations.

