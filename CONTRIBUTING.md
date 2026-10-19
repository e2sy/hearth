# Contributing to hearth

Thanks for considering a contribution.

## Development setup

Clone the repository, then:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
QT_QPA_PLATFORM=offscreen python -m pytest tests/
```

The offscreen platform is what CI uses (3 OS x 2 Python), so a green
local run means a green CI run. Run the suite before pushing.

## Opening a pull request

1. Fork the repository and create a feature branch off `main`.
2. Make focused commits with clear messages.
3. Run the test suite.
4. Open a pull request against `main` describing the problem, the change,
   and the test plan.

## Code style

Follow the existing style in the repository. Keep changes focused — one
logical change per PR.

## Security disclosures

Do not open a public issue for security vulnerabilities. See
[SECURITY.md](SECURITY.md) for the private reporting channel.
