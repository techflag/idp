## Summary

-

## Edition Impact

- [ ] Community edition is affected.
- [ ] Commercial edition is affected.
- [ ] Shared core is affected.
- [ ] Internal-only change; not intended for GitHub community export.

## Capability Decision

- Feature Decision file:
- Capability key:
- Capability level in community: `unavailable` / `demo` / `basic` / `limited` / `full`
- Capability level in commercial: `unavailable` / `demo` / `basic` / `limited` / `full`
- Provider dependency:
- No-configuration behavior:
- Community implementation boundary:
- Commercial/private implementation boundary:

## Guardrail Checklist

- [ ] I updated the capability registry or confirmed this change does not need one.
- [ ] I did not add edition checks outside the policy/capability/provider/extension layer.
- [ ] I did not duplicate community and commercial product code for the same workflow.
- [ ] I did not remove OCR, tables, document trees, evidence, artifacts, or result data to enforce community limits.
- [ ] Missing provider keys or tokens show clear guidance and do not leave users in pending state.
- [ ] MinerU no-token guidance links to `https://mineru.net/?source=github` when relevant.
- [ ] New user-visible strings are covered by i18n or explicitly accepted as legacy scope.
- [ ] Community GitHub export impact is understood.

## Test Matrix

- [ ] Community no-config path tested.
- [ ] Community configured path tested.
- [ ] Commercial/full path tested in internal environment, if applicable.
- [ ] GitHub community export remains free of secrets, internal samples, internal PRDs, and commercial implementations.
