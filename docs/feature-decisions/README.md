# Feature Decisions

This directory stores machine-readable edition decisions for feature work.

Every feature, workflow, provider, route, UI entry, runtime limit, or user-visible behavior change that affects product behavior should add or update one `*.json` file here.

Run:

```bash
python3 scripts/check_feature_decisions.py
```

PR CI can additionally require a changed decision file when backend, frontend, scripts, community export, or CI workflow code changes:

```bash
python3 scripts/check_feature_decisions.py --require-decision-for-changes --base origin/main --head HEAD
```
