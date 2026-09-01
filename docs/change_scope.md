# Minimal Change Scope

## Goal

Produce the simplest complete target state. Minimality is measured by the
remaining system complexity, not by the number of files or lines changed.

## Remove obsolete constructs completely

When the requested target state makes an existing construct obsolete:

- remove it through its complete logical dependency chain;
- update every necessary producer, consumer, interface, document, and
  compatibility path;
- do not retain it merely to avoid an interface change or reduce the diff.

Do not use that removal as permission to change unrelated code.

## Minimize additions

Prefer deletion over replacement when the target behavior no longer needs the
removed concept. Add fields, schemas, validators, compatibility branches,
warnings, tests, or policy text only when the target behavior requires them, or
when omitting validation creates a concrete material stability risk.

## Prevent recurrence proportionally

Before adding a prevention mechanism, mentally rerun the corrected workflow
without it. If removing the original mechanism already makes the failure
unlikely to recur, add no incident-specific guard. If the failure mechanism
remains, add the smallest general guard at its source.
