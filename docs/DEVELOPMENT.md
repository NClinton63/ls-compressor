# Development Workflow

This document defines the branching model, the security and performance
ruleset every change must satisfy, and the release process. It applies to all
contributors and all automated agents working in this repository.

## Branching model

```
main                    stable, release-quality only
└── dev                 integration branch — all feature work lands here first
    ├── feature/<name>  one branch per roadmap feature
    ├── fix/<name>      bug fixes targeting the next release
    └── chore/<name>    tooling, packaging, dependency updates
```

Rules:

1. `main` is only updated by merging `dev` at release time, or by
   `hotfix/<name>` branches for urgent production fixes (which must be merged
   back into `dev`).
2. Every feature branch is created from `dev`, not from `main`:
   ```bash
   git checkout dev && git pull
   git checkout -b feature/zstandard
   ```
3. One feature per branch. Do not combine unrelated changes.
4. Merge a feature branch into `dev` only when its Definition of Done (below)
   is fully met.
5. Never commit secrets, passwords, keys, or user data to any branch.
6. Never force-push `main` or `dev`; never rewrite their history.

## Security ruleset (mandatory)

Every change must satisfy these before merge:

- **Crypto only via vetted libraries.** Use `cryptography`, `argon2-cffi`, or
  `keyring`. No hand-rolled ciphers, no `random`/`secrets` misuse — keys,
  salts, and nonces come from `os.urandom` or library primitives.
- **Key derivation policy.** New password-based operations must use Argon2id
  or PBKDF2-HMAC-SHA256 at ≥ 600,000 iterations (OWASP floor). Iteration
  counts and KDF identifiers must be stored in archive metadata so parameters
  can be raised later without breaking old archives.
- **No plaintext secrets at rest.** Passwords may live only in memory, in
  OS keychain storage (`keyring`), or in the encrypted payload itself.
  `WatchFolderConfig` may keep a plaintext `password` field only while
  keychain migration is pending — new features must not extend that pattern.
- **Secrets never in logs.** `logging` calls must never include passwords,
  derived keys, plaintext payloads, or decrypted contents. Review all new
  `_LOGGER` calls.
- **Path safety.** Extraction must validate member paths (no `..`, no
  absolute paths, no symlink escapes) — decompression of untrusted archives
  is the primary attack surface.
- **Input validation at the boundary.** All request dataclasses validate in
  `__post_init__`; CLI/GUI inputs are validated before reaching `core/`.
- **Dependency policy.** Pin exact versions in `pyproject.toml` /
  `requirements*.txt`. Prefer versions published ≥ 7 days ago. No floating
  ranges (`latest`, `*`, unbounded `>=`).
- **Error messages are user-safe.** Expose operation failures, never stack
  internals, key material, or decrypted data.
- **Encrypted data handling.** Decrypted plaintext exists only in temporary
  directories that are cleaned up (`tempfile.TemporaryDirectory`), never in
  logs or the settings store.

## Performance ruleset (mandatory)

- **No blocking work on the GUI thread.** All I/O and CPU-bound work runs in
  `gui/workers.py` / `gui/queue.py` threads; `core/` stays thread-agnostic.
- **Stream, don't slurp.** Archive read/write must chunk (`CHUNK_SIZE` in
  `core/filesystem.py`). A feature that loads a whole file into memory needs
  explicit justification (the encryption payload is the current, documented
  exception — extending it requires review).
- **Progress must be reported.** Every long operation emits
  `OperationProgress` updates so UI and CLI stay responsive and cancellable.
- **No O(n²) filesystem walks.** Directory traversal and exclusion matching
  run once per file; compile glob/regex patterns once, not per entry.
- **Debounce filesystem events.** Watch-service handlers must not process a
  file while it is still being written.
- **Release the GIL when possible.** Prefer algorithms/backends that release
  the GIL (zstd, lzma, zlib release during compression) so jobs can
  parallelize.
- **Measure before optimizing.** New "performance" code needs a benchmark or
  a test demonstrating the improvement; no speculative complexity.

## Definition of Done (per feature)

A feature branch may merge into `dev` only when **all** of these hold:

1. Code lives in the right layer — `core/` imports nothing from `gui/`/`cli/`.
2. Every new `core/` function has a docstring and full type hints.
3. Tests exist: `tests/unit/` for logic, `tests/integration/` for
   roundtrips. `QT_QPA_PLATFORM=offscreen pytest` passes.
4. `black --check src tests scripts packaging` passes.
5. `ruff check src tests scripts packaging` passes.
6. Security ruleset reviewed: no secrets in logs/settings, inputs validated,
   paths sanitized, crypto per policy.
7. Performance ruleset reviewed: streaming I/O, no GUI-thread blocking,
   progress callback wired.
8. `docs/FEATURES.md` and README updated if the feature is user-visible.
9. Commit history is clean, messages explain the "why".

Merge command:

```bash
git checkout dev
git merge --no-ff feature/<name> -m "Merge feature/<name>: <summary>"
git push
git branch -d feature/<name>
```

## Release process

1. Verify `dev` is green: full pytest, black, ruff.
2. Bump `version` in `pyproject.toml` on a `chore/release-vX.Y` branch off
   `dev`; merge to `dev`.
3. Merge `dev` into `main` with `--no-ff`, tag `vX.Y` on `main`, push tags.
4. `release.yml` builds artifacts; verify each platform bundle.
5. Merge `main` back into `dev` so branches never diverge.

## Roadmap execution order

Features are implemented in the order defined in
`LS Compressor — Feature Improvements & Roadmap.md` ("Biggest gaps" first,
then phases v1.1 → v2.0), one branch per feature, from `dev`.
