# Tests for hearth

Run the suite from the repository root. See `package.json` (or the README)
for the exact script names.

## Conventions

- Tests that need external services (API keys, databases) should skip when
  unavailable rather than fail.
- Integration tests are tagged so they can be excluded from the fast path.
- Keep tests focused: one assertion concept per test.
