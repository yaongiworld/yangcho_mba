# Secrecy Checklist

Yangcho is preparing this MBA application **without her employer's
knowledge**. The hardest career-risk vector for the entire project is a
slip — a stray comment, a debug log, a README line — that ties this work
to her current employer. This document defines the controls.

## Threat model

The risk isn't a malicious leak. It's an accidental one:

- A debug log statement that names an internal project ("hmm this looks
  like the [INTERNAL_CODE] formulation problem we hit last quarter").
- A comment with a brand name ("based on Sulwhasoo's actual emulsion
  approach").
- A test fixture that uses a real employer-internal ingredient code.
- A commit message that names her employer.
- An ENV variable example that mentions a real product.

Once any of those land in a public commit, history rewrites won't fully
help — anyone who already cloned has it. Prevention is the only control
that matters.

## Three layers of defense

### Layer 1 — Local blocklist file (off-repo)

Path: `~/.config/yangcho-mba-secrecy.txt` (or override with the
`YANGCHO_MBA_SECRECY_FILE` env var).

The file is a plain text list, one term per non-comment line. It lives
outside the repo on purpose — the blocklist itself is information about
what we're hiding, so committing it defeats the point.

Two halves:

- **Public half** — employer name variants, well-known consumer brands,
  Yangcho's identifying details. Already populated by Towee 2026-05-04.
- **Private half** — internal project codenames, ingredient codes,
  co-worker names, NDA terms. Yangcho appends these when convenient.
  Empty until she adds them.

The file ships pre-populated with placeholder tokens for Yangcho's
specific identifiers (`__YANGCHO_FULL_NAME_EN__` etc.) that must be
replaced before the hook is enabled in production.

### Layer 2 — Pre-commit hook (W1 deliverable)

A script in the repo that reads the blocklist file and greps every
staged file for any listed term. If a term matches, the commit fails
with a clear message naming the offending term and file (but NOT the
matched line, to avoid the error message itself becoming a leak in CI
logs).

Pre-commit alone is insufficient — `git commit --no-verify` bypasses it,
and a different machine without the hook installed produces no check.
That's what Layer 3 is for.

### Layer 3 — GitHub Action on every PR (W1 deliverable)

A second copy of the same check runs as a required GitHub Action on
every PR to `main`. The blocklist for CI lives in GitHub Actions
secrets (a single multi-line secret named `SECRECY_BLOCKLIST`),
populated by Towee from the local file. Updates require manually
re-syncing the secret — but updates are rare.

The CI check fails the PR if any term is found. Failure messages name
the file and line number but redact the matched term itself.

## What goes in the blocklist

Public terms Towee populates without Yangcho:

- All employer name variants (English, Korean, Hangul, common
  abbreviations).
- All publicly-known consumer brands the employer owns.
- Yangcho's full real name in the forms it's likely to appear.
- Email domain of her employer.
- Her LinkedIn handle (if applicable).

Private terms only Yangcho can populate:

- Internal project codenames.
- Internal product development codes.
- Internal ingredient codes / dev names.
- Names of co-workers, supervisors, recommenders.
- Specific products she's been the named formulator on.
- Anything she has signed an NDA about.

## What is NOT in the blocklist

The blocklist is for **terms that should never appear in the codebase**.
It is not for general PII protection or for filtering scraped Reddit
content. The pipeline strips Reddit usernames as a separate concern (see
Section 3 of the CEO plan).

The blocklist also does not cover the actual *substance* of what Yangcho
knows — there's no way to grep for "she described the film former issue
in a way that only an LG H&H R&D person would know." Substantive secrecy
is editorial: she reviews everything before it goes public on the
dashboard or in the white paper.

## Maintenance

- **Adding a term:** edit `~/.config/yangcho-mba-secrecy.txt`, then
  re-sync the GitHub Actions `SECRECY_BLOCKLIST` secret if the new term
  is genuinely hostile (most adds are private-half and Yangcho can
  defer the CI sync until something needs to ship).
- **Removing a term:** rare. Only if a term turns out to cause too many
  false positives.
- **Rotating:** never. Append-only.

## Bypass policy

`--no-verify` is **never** used to bypass the pre-commit hook on this
repo. If the hook flags something legitimately (e.g., a Python package
named `belif` happens to exist), the resolution is to update the
blocklist with a more specific term (e.g., the brand context), not to
bypass.

The CI check has no bypass.

## Pre-launch final review

Before the public dashboard URL is shared with anyone, Towee runs a
manual `git grep -i` across the full repo for each public-half term as
a final belt-and-suspenders check. This catches anything the automated
hooks missed (e.g., a term added to the blocklist after that file was
last edited).

## Hook implementation

The actual hook script and CI workflow are W1 deliverables. Plan:

- `pipeline/scripts/secrecy_grep.py` — reads
  `$YANGCHO_MBA_SECRECY_FILE` (default
  `~/.config/yangcho-mba-secrecy.txt`), iterates staged files (or the
  PR diff in CI), exits non-zero on any match. Match output names the
  file but redacts the term.
- `.pre-commit-config.yaml` — entry pointing to the script as a `local`
  hook, runs on every commit.
- `.github/workflows/secrecy-grep.yml` — required PR check that runs
  the same script with `SECRECY_BLOCKLIST` from secrets, against the
  PR diff.
