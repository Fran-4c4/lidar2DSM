---
name: document-contract-fields
description: Document and review behavior-controlling fields in configuration classes, typed contracts, dataclasses, Pydantic models, DTOs, and serialized schemas. Use when creating or changing fields, defaults, parsers, aliases, validation, or downstream field semantics.
---

# Document Contract Fields

Keep enough context beside the owning type that a maintainer can judge whether
a field is safe to change without reconstructing the whole application flow.

## Establish the field contract

For every externally supplied or behavior-controlling field, determine:

- its semantic meaning and unit or closed domain;
- special values such as zero, empty, `None`, or negative numbers;
- the authoritative default and every parser, factory, compatibility alias,
  example config, environment variable, or schema default that exposes it;
- the runtime stages and downstream consumers affected by it;
- validation, ordering, range, and cross-field invariants;
- whether invalid values are rejected, ignored, or transformed;
- the regression surface required when its behavior changes.

Search consumers before editing. Similar prefixes or names do not prove shared
ownership; explicitly distinguish adjacent flows that use separate contracts.

## Document locally

Put the stable contract in the owning class or schema documentation. Use
sections such as `Fields`, `External coupling`, `Change impact`, and `Do not`
when they make the boundary clearer. Each non-obvious field description should
state its meaning, unit/domain, special-value behavior, and change impact.

Keep rationale beside critical validation or compatibility code when removing
it would plausibly reintroduce a defect. External process documentation may add
examples, but it must not be the only source for field semantics.

Trivial transport fields may be grouped when their semantics and ownership are
obvious. Do not add comments that merely repeat field names or types.

## Preserve one owner

Use one authoritative owner for defaults and closed field names. Parsers and
factories should reference that owner rather than copy literals. If several
existing defaults disagree, establish which runtime behavior is authoritative,
make the discrepancy explicit, and add a regression before consolidating it.

Reject invalid and contradictory values at the boundary. Do not silently clamp,
truncate, or substitute a different valid value unless the local field contract
defines that behavior intentionally.

## Verify changes

When behavior changes, test the default path, explicit override, invalid input,
and the narrowest affected downstream invariant. Update generated contract or
class indexes when the project requires them, and record the change in the
project's durable history if local rules require it.
