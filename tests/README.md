# Tests for hearth

Run the suite from the repository root:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
```

The offscreen Qt platform is what CI uses (3 OS x 2 Python), so a green run
locally means a green run there. The suite is 1,019 tests and counting.

## Layout notes

- `tests/test_effects_lifetime.py` — the fade-rental lifecycle: release,
  re-rent, newer-fade guard, deleted-host guard, and a composite-pixel probe
  asserting shadowed cards still render under a *finished* fade.
- `tests/test_app_smoke.py` — home-view render regressions over the full app
  stack plus the Quick-picks blend rules.
- `tests/conftest.py` — shared fixtures; Qt widgets are created offscreen.

## Conventions

- Tests that need external services (API keys, databases) should skip when
  unavailable rather than fail.
- Integration tests are tagged so they can be excluded from the fast path.
- Keep tests focused: one assertion concept per test.
