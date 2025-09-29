# Contributing to FIXTranslator

Thanks for your interest in contributing! We welcome contributions of all sizes — bug fixes, new features, tests, docs, and examples.

## How to contribute

1. Fork the repository and clone your fork.
2. Create a feature branch:
   ```bash
   git checkout -b feat/short-description
   ```
3. Write code and tests. Follow existing code style.
4. Run tests locally:
   ```bash
   pip install -r requirements.txt pytest
   ```
5. Commit with clear message and push:
   ```bash
   git add .
   git commit -m "feat(parser): add repeating group handling"
   git push origin feat/short-description
   ```
6. Open a Pull Request to main. Link to any relevant issues.

## Branching & PR rules

- Default branch: main.

- Feature branches: feat/..., bugfix: fix/..., docs: docs/....

- PRs should:
    - Target main.
    - Include a concise description and testing steps.
    - Include tests for new behavior.
    - Pass CI (GitHub Actions).

- Maintainers will review PRs; expect comments and iterative changes.

## Code style & linters

- Python: follow PEP8.

- We run ruff / flake8 and pytest in CI — please fix lint warnings before creating the PR.

## Issues

- Search existing issues before creating a new one.

- Use issue templates (bug/feature) under .github/.

## Local test data & privacy

- Do not commit real production FIX logs or any PII. Use the example files in sample_fix_messages.txt.