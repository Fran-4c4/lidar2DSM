# Contributing

Install with `python -m pip install -e ".[test]"` and run `python -m pytest -q`.
Keep changes focused and explain the problem, resulting behaviour and validation.
See [AGENTS.md](AGENTS.md) for invariants and [docs/configuration.md](docs/configuration.md)
for the configuration contract. Write documentation and agent instructions in English.

Preserve third-party notices and attribution. Do not include private datasets,
credentials, large generated outputs or third-party code without checking its terms.

Numerical changes need known ground/roof cases and an explained tolerance.
A successful synthetic example does not establish the accuracy of a real survey.
