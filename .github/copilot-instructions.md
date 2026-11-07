# FX90 Simulator Copilot Instructions

## Project Context

- This repository is a Python test harness that simulates the subset of the Zebra FXR90 RFID interface consumed by Ultra Tracker.
- The project uses FastAPI, asyncio, WebSockets, and pytest. Keep changes consistent with the existing package and test layout.
- The simulator is not a complete hardware implementation. Preserve the externally visible interface and behavior used for integration testing.

## Decision Order For Any Change

Before writing code, stop at the first rung that holds:

1. Does this need to exist at all? If the requirement is speculative or not yet justified, skip it and say so.
2. Is it already in this codebase? Reuse it.
3. Does the standard library or platform already do it? Use that.
4. Can it be one line? One line.
5. Only then: the minimum code that works.

Additional rules:

- No abstraction with one caller.
- No config for a value that never changes.
- Shortest working diff wins.
- Do not add structure for future hypothetical requirements.

## Repository Conventions

- Keep application code under `src/fx90_simulator/` and tests under `tests/`.
- Use the existing dependencies and pytest configuration; update `requirements.txt` only when a dependency is necessary.
- Keep changes focused and follow existing Python formatting, typing, and async patterns.
- Preserve the FXR90 REST paths, WebSocket payload format, and `FX90_*` environment variables that form the integration contract.
- Keep scenarios as versioned JSON definitions under `src/fx90_simulator/scenarios/`; preserve their existing format and deterministic behavior.

## Documentation And Comments

- Tests and the commit history are the primary documentation of design and requirements.
- Write code comments only when they preserve an important concept or decision that would otherwise be easy to lose.
- Keep comments brief, local, and specific; do not add narrative comments or repetition.

## Data Integrity And Safety

- Prefer additive, reversible changes and preserve existing interface behavior.
- Validate inputs at API boundaries and surface malformed input or configuration errors explicitly.
- Preserve backwards compatibility for existing scenario and reader-profile data formats.
- Keep runtime test settings consistent with the existing rule that they may only be changed while the simulated reader is stopped.

## Validation

- Test-first is useful when it locks down a real requirement, but it is not a substitute for deciding whether the feature is needed or whether the minimal fix already exists.
- Run the narrowest relevant pytest check first, then expand only as needed.
- Do not claim validation you did not run.

## Token And Context Optimization

- Start from the named file, symbol, error, test, or command; avoid broad repository reads.
- Do one targeted search and the minimum surrounding reads needed to confirm the root cause.
- Patch the smallest coherent slice; do not re-read unchanged files or broaden scope without evidence.
- Validate in the smallest relevant check first; stop once the fix is proven and avoid extra exploration.
- Keep progress and final summaries short: changed files, behavior, validation, and remaining risk only.

## Scope

- Keep instructions narrow to the layer they govern; use specialized instruction files for domain-specific rules when needed.
- Prefer the small, explicit rule over broad policy repetition.
