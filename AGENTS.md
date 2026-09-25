# Repository instructions

## Scope

These instructions apply to the entire repository.

Keep this file timeless.

Do not record:
- current project status
- completed or pending experiments
- temporary analysis results
- device-specific session information
- local paths or environment details

Unfinished work and its completion criteria belong in `TODO.md`. The next item and brief restart notes belong in `HANDOFF.md`.

---

## Repository authority

Treat the current Git repository state and working tree as the source of truth for the project.

Do not treat:
- chat history
- model memory
- previous conversations
- external summaries

as repository facts.

Information from outside the repository may be used to identify problems, generate hypotheses, or suggest investigations.

External information is not a project fact until it has been verified.

Unverified information may be recorded in the repository as a hypothesis, observation, or investigation note with an appropriate evidence status.

---

## Document roles

The repository has the following information hierarchy.

### AGENTS.md

Purpose:
- permanent instructions for development and analysis

Contains:
- workflow rules
- evidence handling rules
- documentation rules
- safety rules

Does not contain:
- current research status
- pending work
- experiment results

---

### HANDOFF.md

Purpose:
- minimal restart note for future development sessions

Contains:
- the number of the next `TODO.md` item
- brief notes needed to resume that item

Do not copy the task list, completion criteria, or protocol claims into `HANDOFF.md`.

---

### TODO.md

Purpose:
- authoritative list of unfinished work and completion criteria

Contains:
- stable item numbers
- the work needed for each item
- observable conditions for closing each item

Do not use `TODO.md` as a source of protocol specification. Link to `SPEC.md` and evidence instead of repeating protocol claims.
When an item meets its completion criteria, remove it from `TODO.md`, keep its number unused, and update `HANDOFF.md` to the next unfinished item.

Protocol information belongs in `SPEC.md` with an appropriate evidence status.

---

### SPEC.md

Purpose:
- authoritative human-readable record of protocol claims and their evidence status

`SPEC.md` is the only protocol specification authority.

All protocol claims must include an evidence status tag defined by `SPEC.md`.

Examples:
- CONFIRMED
- OBSERVED
- HYPOTHESIS
- UNKNOWN

Do not add protocol facts without an appropriate evidence status.

---

### evidence/

Purpose:
- experimental evidence and raw observations

May contain:
- test results
- raw captures
- logs
- measurements
- generated reports

Evidence is not automatically a specification.

An observation must be reviewed and interpreted before becoming a protocol claim in `SPEC.md`.

---

### docs/

Purpose:
- supporting research materials

May contain:
- static analysis reports
- investigation notes
- technical explanations
- vendor analysis

Documents here support claims but do not override `SPEC.md`.

---

### README.md

Purpose:
- project overview and navigation

README.md is not a second specification.

Avoid duplicating protocol details.

---

## Specification and implementation relationship

Implementation follows the supported protocol claims in SPEC.md; hypotheses and unknowns are not implementation requirements.

Source code and tests describe implemented behavior.

However:

- implementation is not an independent source of protocol truth
- a behavior found only in code must not automatically become a protocol fact
- protocol semantics require appropriate evidence and documentation

When implementation conflicts with `SPEC.md`:

1. Identify the conflict.
2. Review available evidence and documentation.
3. If the conflict cannot be resolved from existing evidence, perform an investigation or experiment.
4. Update the appropriate source based on the result.

Do not silently choose one interpretation.

---

## Evidence discipline

Maintain a strict distinction between:

- confirmed facts
- observations
- hypotheses
- unknowns

Rules:

- Do not promote hypotheses into confirmed facts.
- Do not infer semantic meaning solely from numeric values, identifiers, operating-system events, or decompiled names.
- Use UNKNOWN when evidence is insufficient.
- Preserve missing evidence as missing.
- Do not recreate raw evidence from memory or previous discussion.

A successful host API call proves only that the call completed.

It does not prove:
- device acceptance
- hardware effect
- persistent configuration change

unless the corresponding observation exists.

Failures are valuable evidence.

Record failures when they help distinguish:
- protocol rejection
- transport failure
- timeout
- insufficient test conditions
- restoration failure

---

## Documentation design

Keep documentation minimal and avoid multiple sources of truth.

Rules:

- Each protocol claim should exist in one authoritative location.
- Link to existing information instead of copying it.
- Do not create duplicate specifications.
- Additional indexes or catalogs are allowed when they improve navigation and do not duplicate protocol claims.

The TODO list, handoff document, and evidence indexes serve their stated roles and do not override `SPEC.md`.

---

## Working procedure

Before changing anything:

1. Read `HANDOFF.md` and `TODO.md` if present.
2. Read relevant sections of `README.md`, `SPEC.md`, and documentation.
3. Inspect:
   - `git status`
   - `git diff`
4. Read relevant implementation and tests.
5. Determine whether the change affects:
   - specification
   - implementation
   - experiment
   - documentation

---

## Development changes

Prefer the smallest change that keeps the repository consistent.

Requirements:

- Update tests for implementation changes.
- Do not modify generated binaries or archives as source.
- Do not commit temporary files, caches, local environments, or unrelated artifacts.
- Do not publish releases, tags, or change remote repository state without explicit request.

---

## Experiments

Hardware experiments must balance evidence quality and practical cost.

Rules:

- Prefer experiments that distinguish competing explanations.
- Avoid unnecessary exhaustive testing.
- Large exhaustive tests require confirmation of scope and cost when user effort is significant.
- Do not start expensive experiments without understanding:
  - purpose
  - expected result
  - duration
  - repetition count

When exhaustive testing is justified, document:
- scope
- conditions
- reason for completeness

---

## Hardware safety and reproducibility

Hardware access is read-only by default.

Operations that:
- write configuration
- pair or unpair devices
- restore settings
- change persistent state

require explicit user intent.

Before writing:

- identify the exact device
- verify transport and interface
- verify report capability
- display the target operation

Never assume:
- `/dev/hidrawN`
- `/dev/input/eventN`

remain stable.

For configuration changes:

- preserve restoration information
- record the write operation
- record observed post-operation behavior

For wireless devices:

Distinguish:

- write completion
- transfer opportunity
- verified device behavior

Do not treat elapsed time alone as proof of application.

---

## Python and host integration

- Do not install packages into system Python.
- Prefer standard library when sufficient.
- Use isolated environments for development dependencies.
- Do not use `sudo pip`.
- Keep command-line tools reproducible from repository instructions.

System services and udev rules are integration artifacts.

Validate them, but do not install or enable them without explicit request.

---

## Privacy and publication

Do not commit:

- usernames
- home directory paths
- hostnames
- serial numbers
- personal identifiers

Validate evidence before publication.

Retain only information required for reproduction.

Keep vendor independence and unofficial research status clear.
