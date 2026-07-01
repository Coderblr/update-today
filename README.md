# NBC Workflow Automation Platform — Phase 4

AI-powered NBC banking workflow automation platform. **Phase 1 delivered Module 1**
(DOM Crawling & Locator Repository Builder). **Phase 2 delivered Module 2 core** (the
AI Workflow Execution Engine — feature-file-driven execution, Maker-Checker,
lightweight self-healing, smart waits, screenshots, HTML/JSON reporting). **Phase 3
delivered Module 3 core** (Locator Repository Upload & Override — 5 file formats,
layered version control, a layered execution priority chain, pre-execution
validation). **Phase 3b adds the previously-deferred polish**: the PDF report format,
an execution video (screenshot timelapse), a multi-chart analytics dashboard,
repository merging, and per-locator usage statistics. **Phase 4 aligns the platform
with the user's real production NBC/Cucumber framework**: a backend credential vault
(maker/checker/default login, transaction defaults — no more typing credentials into
the frontend), step-DSL aliases that parse the user's actual feature-file phrasing
directly, fuzzy field-name resolution so phrases like "the account" resolve to a
stored field named "Account Number", a rewritten safety-first recursive crawler (fixes
a real reported bug where crawling a transaction ended in an unintended logout), and
sample-data-driven crawling for data-gated screens — all end-to-end and verified for
real against a local synthetic NBC-style fixture app using a genuine, visible
Microsoft Edge session. Docker/Render deployment remains explicitly out of scope (per
instruction). Visual/image-based element matching remains a permanent non-goal (no
real product justification for adding a CV/image-matching library over the existing
locator-strategy chain).

## Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite, Selenium + Microsoft Edge, LangChain +
  Azure OpenAI (optional — falls back to rule-based heuristics when no key is
  configured), Chroma (offline hash embeddings, no network dependency), Jinja2 (HTML
  reports).
- **Frontend**: Next.js 15 (App Router) + JavaScript (plain JS, no TypeScript — see
  "Plain JavaScript" note below) + Tailwind CSS + shadcn/ui + Framer Motion + Recharts
  (analytics charts).
- **Reporting/media**: Playwright (also used for UI verification) prints the HTML
  report to PDF; `imageio` + `imageio-ffmpeg` (bundled static ffmpeg binary, no system
  install) stitch step screenshots into an MP4.

## What Module 1 does (Phase 1)

1. Launches Microsoft Edge (visible by default, so you can watch the automation run).
2. Logs in with the provided credentials (heuristic field detection — no hardcoded
   selectors).
3. Searches for a transaction by number or name. Transaction numbers are normalized
   for leading-zero variants (`1060` and `001060` match the same transaction; this is
   NOT the same as treating differently-padded numbers like `010600` as equal — see
   `transaction_search_agent.normalize_transaction_number`).
4. Crawls every reachable screen of that transaction: multi-page wizards, popups
   (separate browser windows), iframes, and Shadow DOM hosts.
5. For each control, extracts: tag, id/name/class/aria-label, XPath, CSS selector,
   control type, visibility/enabled/readonly state, dropdown options, and a mandatory-
   field verdict (rule-based, refined by an optional Azure OpenAI pass).
6. Ranks locator strategies per field (id > name > css > xpath) into a priority +
   fallback locator pair with a confidence score, persisted to the Locator Repository.
7. Exposes JSON and Excel export of the repository.

## What Module 2 core does (Phase 2)

1. Accepts one or more `.feature` files (a small, explicit Gherkin-shaped step DSL —
   see `backend/app/agents/feature_step_parser.py` for every supported step pattern:
   `I am logged in as maker/checker "..." with password "..."`, `I search for
   transaction "..."`, `I fill "field" with "value"`, `I select "field" as "value"`,
   `I check "field"`, `I click "text"`, `I submit for approval`,
   `I approve the transaction`, `I logout`, `I should see "field"`) and executes them
   **sequentially in upload order** against a fresh Edge session per feature file.
   The Execution Center form also has optional **Login ID / Password / Transaction
   Number / Transaction Name** fields (mirroring Module 1's Crawl page) — when
   filled in, the equivalent login/search steps are auto-injected at the start of
   *every* feature file (each gets its own fresh session, so each needs its own
   login/search), so feature files only need to contain the actual business steps
   (`backend/app/agents/execution_setup.py`). Feature files can still hand-write
   their own login/search lines instead if you'd rather not use the form fields.
2. Resolves every step's target field via the Locator Repository (priority locator,
   then fallback locator) — automatically switching into iframes and piercing Shadow
   DOM boundaries when that's where the field was originally discovered.
3. **Self-heals** when a stored locator no longer resolves (or none exists yet): re-
   crawls the current page/iframe/shadow-root, re-ranks candidates by label match, and
   on success writes a `HealingHistory` row *and* updates the Locator Repository entry
   (demoting the old locator to fallback, promoting the newly found one to priority).
4. **Maker-Checker**: `LoginStep`/`LogoutStep`/`SubmitForApprovalStep`/`ApproveStep`
   compose into a full login-as-maker → fill → submit-for-approval → login-as-checker
   → approve sequence, with no separate "maker-checker mode" — it's just ordinary
   steps.
5. **Continue / Stop on failure**: configurable per execution; `stop` skips every
   remaining feature file once one fails, `continue` keeps going.
6. Captures a before/after screenshot for every step, stored under
   `storage/exports/screenshots/{execution_id}/`.
7. Classifies every failure (rule-based: `locator_not_found` / `timeout` /
   `undefined_step` / `assertion` / `app_error`; optional LLM-written root cause when
   Azure OpenAI is configured) and stores it as a `Failure` row.
8. Generates an HTML report (with embedded screenshots) and a JSON report per
   execution, viewable from the Execution Center UI.

## What Module 3 core does (Phase 3)

1. Accepts locator repository files in **5 formats** — JSON, Excel (`.xlsx`), CSV,
   XML, YAML (`backend/app/agents/locator_file_parsers.py`) — using one canonical
   column schema that mirrors Module 1's own export, so export → hand-edit →
   re-upload is a real, working round trip.
2. **Version control per transaction number**: every upload creates a new
   `LocatorRepositoryVersion` (auto-incrementing, one active at a time). Versions are
   **layered, not all-or-nothing** — uploading a small file that only touches one
   field does not hide every other field from earlier versions; a field with no entry
   in the new version still resolves to its last applicable entry from an earlier one
   (this was a real bug caught via the dashboard UI walkthrough and fixed — see
   `locator_resolver.effective_entries_for_transaction`). "Rolling back" is just
   reactivating an older version.
3. **Layered execution priority chain**: for each field, the effective entry is the
   highest-versioned *uploaded* entry at or below the active version number; if none
   exists, the most recent crawl/healed entry; if neither exists, Phase 2's
   self-healing re-crawl-and-match fallback. Proved end-to-end: an uploaded file with
   one deliberately wrong locator is tried first (and fails), falls through to
   self-healing, and — because self-healing writes back to the repository — the
   uploaded entry is corrected in place for next time.
4. **Pre-execution Validation Agent**: cross-references every field a feature file's
   steps need against the effective repository, reporting missing fields, *raw*
   duplicate entries (same transaction+field+locator stored more than once, regardless
   of which version is active), syntactically invalid XPath/CSS locators (checked via
   `lxml.etree.XPath` / `cssselect`), an average confidence score, and one-line
   suggested fixes — before a single browser is launched.
5. **Locator Management Dashboard** (`/locators/manage`): upload widget, per-
   transaction version list with one-click rollback, an inline-editable entry table
   (priority/fallback locator + delete), and a validation panel.
6. CSV added as a third export format alongside JSON/XLSX.

## What Phase 3b adds

1. **Per-locator usage statistics** (`backend/app/agents/locator_usage_agent.py`):
   for every Locator Repository entry — total uses, pass/fail counts, last successful
   execution timestamp, and a heal count, computed purely from `ExecutionStep` and
   `HealingHistory` rows already captured in Phase 2/3 (no new tracking). A
   **stability score** (successful uses ÷ (uses + heals)) flags fields that look
   resolved but keep needing self-healing. Surfaced as extra columns in the Locator
   Management Dashboard.
2. **Repository merge**: select 2+ versions in the dashboard and merge them into one
   new version — on a field-name conflict, the entry from the higher source version
   number wins, while fields unique to either version both survive
   (`locator_repository_service.merge_versions`).
3. **PDF report**: `GET /execution/{id}/report?format=pdf` prints the existing HTML
   report to PDF via Playwright's Chromium — no new, often-fragile-on-Windows
   HTML-to-PDF library, just reusing a dependency already in this project.
4. **Execution video**: `GET /execution/{id}/video` stitches every step's
   before/after screenshot into an MP4 (`backend/app/services/video_service.py`).
   This is honestly a **screenshot timelapse, not continuous screen capture** —
   Selenium has no continuous-recording API, and building one (browser casting, OS-
   level screen capture) would be a substantial addition for a spec feature marked
   *optional*. It's a real, working MP4 of the execution's progression, just not
   real-time footage.
5. **Analytics dashboard** (`/analytics`): KPI cards (total executions, success rate,
   average duration, steps healed), a pass/fail pie chart, a failure-category bar
   chart, a daily execution-count line chart, and a "least stable locators" list —
   all aggregated live from `Execution`/`ExecutionStep`/`Failure`/`HealingHistory`,
   no separate analytics store.

## What Phase 4 adds

1. **Backend credential vault** (`backend/app/core/config.py` `Settings`, populated
   from `.env`): `default_username`/`default_password`,
   `maker_username`/`maker_password`, `checker_username`/`checker_password`, and
   `default_transaction_number`/`default_transaction_name`. The Execution Center form
   no longer has Login ID / Password fields at all — credentials are always resolved
   server-side. Transaction Number / Transaction Name remain on the frontend (the
   thing that actually changes per run) but now fall back to the backend defaults when
   left blank.
2. **Credential placeholder tokens inside feature files**: a feature file's own login
   step can reference `"makerID"` / `"makerPassword"` / `"checkerID"` /
   `"checkerPassword"` / `"username"` / `"password"` as literal text — exactly the
   convention the user's existing Java/Cucumber framework already uses (resolved there
   from a properties file). `step_executor._resolve_credential` resolves these
   case-insensitively from the vault right before login; anything that isn't a
   recognized placeholder is treated as a literal credential, so hand-typed feature
   files with real values still work unchanged.
3. **Step DSL aliases matching the user's real phrasing**
   (`backend/app/agents/feature_step_parser.py`), tried alongside (not replacing) the
   original DSL: `the user is logged into NBC using "X" and "Y"` (role inferred from
   whether `X` contains "checker"), `we search for the transaction "X"`,
   `we enter the(?: the) (.+) as "X"(?: in ... screen)?`, `we select the (.+) as "X"`,
   `click on the (.+) button`, `clicks? on logout button`, `authorize the
   transaction...`. Proved against the user's literal phrasing, including their
   original double-article typo ("we enter the the account as...").
4. **Fuzzy field-name resolution** (`backend/app/agents/self_healing_agent.py`'s
   `fuzzy_best_match`, used by both `locator_resolver.py` and self-healing): a step
   phrase like "the account" doesn't exact-match a Locator Repository field named
   "Account Number", so candidates are scored by **significant-word overlap first**
   (falling back to character-level `SequenceMatcher` only when no words overlap at
   all). Word-overlap-first was a deliberate fix to a real bug caught during this
   phase's own testing: plain character-similarity alone scored "Amount" higher than
   "Account Number" for the phrase "the account", which is backwards.
5. **Crawl logout bug fixed + rewritten safety-first recursive crawler**
   (`backend/app/agents/crawl_orchestrator.py`): the user reported the crawler
   ending up logged out right after entering a transaction number. Two contributing
   fixes: (a) `transaction_search_agent.py` now sends `Keys.ENTER` to the search field
   instead of calling `field.submit()`, which was bypassing the page's own JS
   handlers/validation; (b) the crawler no longer uses fixed "next"/"popup" hint
   lists — it now enumerates every clickable element on a screen and recurses into
   each one not yet visited, **except** anything matching a hard-coded destructive-
   action blacklist (`logout`, `log out`, `sign out`, `log off`, `submit`, `confirm`,
   `post`, `pay`, `transfer`, `delete`, `remove`, `approve`, `authorize`, `save`,
   `cancel`, `close`, `exit`, `finish`, `complete`, and no-space variants like
   `logoff`/`signout`) — those are recorded in the navigation graph as "discovered,
   not explored" rather than risking firing a real transaction on a live banking
   system. This was a deliberate, user-confirmed safety boundary, not an oversight.
6. **Sample data for crawling**: the Crawl page now accepts optional sample data (a
   JSON field-name → value map, typed directly or uploaded as a `.json` file). Before
   exploring a screen, the crawler fuzzy-matches sample-data keys against empty
   mandatory fields and fills them — this lets the crawler reach screens/actions that
   are gated behind having valid data in a field (a plain client-side JS gate is common
   on real banking screens), without that data ever being submitted anywhere.
7. **What "share the feature file / step definition / page object" maps to here**:
   this platform doesn't use hand-written Java Page Object / Step Definition classes
   per transaction. The **Locator Repository** (built by the crawler) is the page-
   object equivalent, and `step_executor.py` is one generic, transaction-agnostic
   step-definition layer that works for every screen. `storage/fixtures/feature_files/
   07_txn1060_real_style.feature` is the user's actual maker → withdraw → checker flow
   translated into the new aliased DSL, runnable today against the fixture app, proving
   the new phrasing and credential-placeholder resolution work end-to-end.

## Project layout

```
backend/                       FastAPI app, agents, services, API routes, pytest suite
backend/app/templates/          Jinja2 HTML report template
frontend/                       Next.js 15 UI
storage/fixtures/nbc_sim/       Local synthetic NBC-style test app (login, wizard, Maker-Checker approval)
storage/fixtures/feature_files/ Sample feature files in the step DSL, used for verification
storage/fixtures/locator_files/ Sample locator repository files (one per format), used for verification
storage/db/                     SQLite database
storage/exports/                JSON/Excel/CSV locator exports, screenshots, HTML/JSON execution reports
tools/msedgedriver/              Downloaded Edge WebDriver matching this machine's Edge version
```

### Plain JavaScript, not TypeScript

The frontend is plain JavaScript (`.js` files, including ones with JSX — the same
extension convention `create-next-app`'s JavaScript template uses) rather than
TypeScript, by request, for an office environment without TS tooling. Concretely:
`tsconfig.json` → `jsconfig.json` (same `@/*` path alias, just no type-checking
options), `next.config.ts` → `next.config.mjs`, and `typescript`/`@types/*` were
dropped from `package.json`. No backend or behavior changes — every component, page,
and the `lib/api.js` request layer are functionally identical to their former `.tsx`/
`.ts` versions, just with type annotations and `interface`/`type` declarations
stripped (types are erased at runtime anyway). Verified by a clean `npm run build`,
`npm run lint` (zero errors), and a Playwright walkthrough of every page confirming
no console/runtime errors and real backend data still renders correctly.

## Running it

1. **Backend** (from `backend/`):
   ```
   ../.venv/Scripts/python -m uvicorn main:app --reload --port 8000
   ```
2. **Fixture app** (from `storage/fixtures/nbc_sim/`) — only needed to try the platform
   without a real NBC environment:
   ```
   ../../../.venv/Scripts/python app.py
   ```
   Maker login: `tester` / `Passw0rd!`. Checker (approver) login: `approver` /
   `Approve123!`.
3. **Frontend** (from `frontend/`):
   ```
   npm run dev
   ```
   Then open http://localhost:3000 — **New Crawl**, **Locator Repository**,
   **Execution Center**, and **Manage Locators**.

## Configuration (`.env` at the project root)

See `.env.example`. Key settings:

- `AZURE_OPENAI_*` — optional. Leave blank to run fully on rule-based heuristics.
- `EDGE_DRIVER_PATH` — **set this if Selenium Manager's auto-resolved driver doesn't
  match your installed Edge version** (a `SessionNotCreatedException` mentioning
  "only supports Microsoft Edge version X" is the symptom — download the matching
  driver from `https://msedgedriver.microsoft.com/<your-edge-version>/edgedriver_win64.zip`
  and point this at the extracted `msedgedriver.exe`).
- `DEFAULT_HEADLESS` — `false` by default so you can watch automation happen live.
- `DEFAULT_USERNAME` / `DEFAULT_PASSWORD` — fallback login used by the Execution
  Center when a feature file has no login step of its own and no per-run override is
  given.
- `MAKER_USERNAME` / `MAKER_PASSWORD`, `CHECKER_USERNAME` / `CHECKER_PASSWORD` — the
  credential vault. Feature files can reference these by writing the literal tokens
  `"makerID"` / `"makerPassword"` / `"checkerID"` / `"checkerPassword"` in a login
  step instead of real values — resolved server-side at execution time, never sent to
  or stored on the frontend.
- `DEFAULT_TRANSACTION_NUMBER` / `DEFAULT_TRANSACTION_NAME` — fallback used when the
  Execution Center's Transaction Number / Transaction Name fields are left blank.

## Verification performed

**Phase 1 (Module 1):**
- 15 pytest tests pass, including a real (non-mocked) end-to-end test that drives a
  genuine Edge session against the fixture app.
- A real crawl discovers 3 pages, 1 popup, 1 iframe, 18 fields, and correctly flags 4
  mandatory fields — including fields nested inside an iframe and a Shadow DOM host.
- JSON/Excel exports verified by loading the actual output files.

**Phase 2 (Module 2 core):**
- 30 pytest tests pass total (15 new), including 4 non-mocked Edge integration tests
  (`backend/tests/test_execution_integration.py`).
- A real 16-step Maker-Checker feature file (`storage/fixtures/feature_files/01_happy_path_maker_checker.feature`)
  runs end-to-end: login as maker → search → fill fields inside the main page, an
  iframe, and a Shadow DOM host → advance a 3-step wizard → submit for approval →
  logout → login as checker → approve. Confirmed by directly checking the fixture
  app's pending-approvals list before/after: the transaction genuinely moved from
  `pending_approval` to `approved`.
- Self-healing proved for real: deliberately corrupted a stored locator's `id` in the
  database, re-ran a feature file referencing that field, and confirmed the engine
  re-discovered the correct element, wrote a `HealingHistory` row, and updated the
  Locator Repository entry (old locator demoted to fallback).
- Failure classification proved for real: a feature file referencing a nonexistent
  field produces a `Failure` row with `category="locator_not_found"` and a concrete
  suggested fix.
- Continue-on-failure vs. stop-on-failure proved across two feature files: `stop`
  marks the second file `skipped`; `continue` runs it (and it passes) regardless of
  the first file's failure.
- HTML and JSON execution reports verified by rendering and screenshotting the actual
  output (embeds real before/after screenshots, highlights healed steps).
- Playwright-driven screenshot walkthrough of the Execution Center UI (new-execution
  form with feature-file upload/reordering → live run status → step table with
  screenshot thumbnails) against real backend data.

**Phase 3 (Module 3 core):**
- 53 pytest tests pass total (23 new): one test per file-format parser (JSON, XLSX
  generated in-memory via openpyxl, CSV, XML, YAML), version creation/increment/
  rollback, validation report computation, and resolution precedence — including a
  regression test for the layered-versioning bug described below.
- Real upload verified for all 5 formats via the API against the running backend, not
  just pytest: each created the expected `LocatorRepositoryVersion` and entries with
  `source="upload"`.
- Real priority-chain proof: uploaded a locator file with one correct field and one
  deliberately wrong one (`Customer Name` pointed at a nonexistent id); ran a real Edge
  execution; confirmed the wrong uploaded locator was tried first (and failed), fell
  through to self-healing, healed correctly, and **wrote the fix back into the
  uploaded entry** (old locator demoted to fallback) — confirmed by re-running the
  same execution afterward with `healed_steps=0`, i.e. it now resolves directly.
- Real version rollback proof: uploaded a second, fully-correct version (became
  active); rolled back to the original (still self-healed-by-then) version via the
  activate endpoint; re-ran execution successfully.
- Real validation proof: a feature file referencing 5 fields against a repository
  missing one of them produced a report with exactly that one field in
  `missing_fields` and a non-zero average confidence for the rest.
- **A real bug was found via the Locator Management Dashboard UI walkthrough, not
  invented for the sake of finding one**: uploading a small CSV containing only one
  field ("Notify customer") deactivated the *entire* previous version for that
  transaction, which made every field that small file never mentioned (Customer Name,
  Account Number, Amount, Currency) silently unresolvable — the validation report
  showed "0/5 steps mapped" with everything flagged missing, even though those fields
  plainly had entries one version back. Fixed by making version resolution **layered**
  (`locator_resolver.effective_entries_for_transaction`): a field resolves to the
  highest-versioned uploaded entry at or below the currently-active version number,
  not strictly to the active version's own entries. Re-verified via the same dashboard
  screenshot afterward (now correctly "4/5 steps mapped", only the genuinely-missing
  field flagged) and locked in with a regression test.
- A second real bug was found the same way: `LocatorEntryResponse.crawl_run_id` was
  declared as a required string, but uploaded/healed entries legitimately have no
  `crawl_run_id` — the Locator Repository page (`/locators`) returned a 500 the moment
  any non-crawl entry existed. Fixed by making the field optional.
- Playwright-driven screenshot walkthrough of the Locator Management Dashboard
  (version list with rollback buttons → validation panel → inline-editable entry
  table) against real backend data, captured both before and after the layered-
  versioning fix to confirm the before/after behavior difference for real.

**Phase 3b (deferred polish):**
- 70 pytest tests pass total (17 new): usage-stats math, merge conflict resolution,
  analytics aggregation math (all unit-tested with hand-built data), plus a real
  (non-mocked) integration test that writes actual PNG screenshots to disk and
  invokes the real PDF/video generation code paths — not mocked stand-ins.
- Real usage stats cross-checked against direct SQLite queries on the dev database:
  the API's reported `heal_count`/`total_uses` for "Customer Name" matched exactly
  what a raw `SELECT COUNT(*)` against `execution_steps`/`healing_history` showed.
- Real merge proof: merged two real uploaded versions of transaction `1060` with an
  overlapping "Customer Name" field; confirmed the higher-version value won and the
  three non-conflicting fields (Account Number, Amount, Currency) all survived into
  the merged version.
- Real PDF proof: generated a PDF for a real (not synthetic) past execution; the file
  starts with the `%PDF-1.4` header and is ~280KB, not an empty/error stub.
- Real video proof: generated an MP4 for that same real execution; `imageio` reports
  exactly 12 frames (6 steps × before+after) at the expected ~18s duration — not just
  "a file exists."
- Real analytics proof: hit `/analytics/summary` against the accumulated dev database
  and got back the actual execution count, success rate, and the one real
  self-healing event recorded for "Customer Name" — matching what's actually in the
  database.
- Playwright-driven screenshot walkthrough of the new Analytics page (KPI cards, pie/
  bar/line charts with real data) and the updated Locator Management Dashboard
  (version checkboxes + "Merge Selected" + usage-stat columns) against real backend
  data.

**Execution Center login/transaction form fields:**
- 79 pytest tests pass total (9 new): setup-step-text generation (login requires
  both username *and* password or neither is injected; transaction number takes
  precedence over transaction name when both are given) and injection-position
  logic (`backend/app/agents/execution_setup.py`), plus a parse-order check
  confirming the injected lines actually become the first `LoginStep`/`SearchStep`.
- Real proof: ran a feature file containing *only* two `Fill` steps (no login/search
  lines at all) via the API with `username`/`password`/`transaction_number` set;
  confirmed all 4 resulting steps (the 2 auto-injected + the 2 original) passed.
- Playwright screenshot walkthrough of the new form fields and the resulting
  execution run, showing the auto-injected login/search steps in the step table.

**Phase 4 (credential vault, real-world DSL, safe recursive crawler):**
- 109 pytest tests pass total (30 new): credential-placeholder resolution, the new
  DSL alias patterns (including the user's literal "the the account" double-article
  phrasing), `fuzzy_best_match` word-overlap and character-fallback behavior,
  setup-step skip-if-already-present logic, and crawler blacklist/signature behavior
  (`backend/tests/test_credential_resolution.py`,
  `test_self_healing_agent.py`, `test_crawl_orchestrator_safety.py`, additions to
  `test_feature_step_parser.py` and `test_execution_setup.py`).
- **Real end-to-end proof, not just unit tests**: a full 15-step Maker-Checker feature
  file written in the user's exact production phrasing
  (`storage/fixtures/feature_files/07_txn1060_real_style.feature` — login via
  `"makerID"`/`"makerPassword"` tokens, `we enter the the account as "..."`,
  `we select the ... as "..."`, `click on the ... button`, `authorize the
  transaction`) ran against the fixture app with **no credentials or transaction
  number supplied on the request at all** — both resolved entirely from
  `MAKER_USERNAME`/`MAKER_PASSWORD`/`CHECKER_USERNAME`/`CHECKER_PASSWORD` — and
  completed with all 15 steps passed, including "the the account" fuzzy-resolving to
  `#account_number`, "branch code" resolving to a field inside an iframe, and
  "remarks" resolving to a field inside a Shadow DOM host.
- **A real double-login bug was found and fixed during this phase's own
  verification, not reported by the user**: when both a backend default login *and*
  the feature file's own login step were present, both fired — the second
  `perform_login()` call landed on a page with no real login form, silently grabbed
  the wrong field via a fallback, and corrupted the subsequent search step, while
  `step_executor.py` ignored `perform_login`'s failure return value and reported the
  step as passed anyway. Fixed by (a) having `step_executor.py` check the return
  value and raise on failure, and (b) having `execution_setup.build_setup_steps_text`
  parse each feature file's own text and skip injecting login/search if the file
  already defines them.
- **Real crawl proof that the reported logout bug is fixed**: added a real "Logout"
  link reachable from the post-search screen in the fixture app; confirmed via a
  real (non-mocked) Edge crawl that the link is discovered (appears in
  `navigation_graph` as blocked) but never clicked, and that the rest of the screen
  — including every mandatory field — is still crawled correctly either way.
- **Real sample-data-gated crawl proof**: the fixture app's "View Account Summary"
  button only navigates once Account Number has a value (a plain client-side JS
  gate). A real crawl with no sample data never reaches that screen; supplying
  `{"Account Number": "AC-99999"}` as sample data lets the crawler fill the field and
  discover the otherwise-unreachable "Account Status" field.
- **A real fuzzy-matching bug was caught and fixed before reaching the user**:
  scoring candidates by raw character-sequence similarity alone picked "Amount" over
  "Account Number" for the phrase "the account" (0.588 vs. 0.56) — exactly backwards.
  Fixed by checking significant-word overlap first and only falling back to
  character-level similarity when no words overlap at all; locked in with a
  regression test.
- **A second real gap was caught by the blacklist test itself during a final
  regression pass**: `logoff` (no space) wasn't matched by the `log off` blacklist
  entry. Added `logoff`/`signout` as explicit no-space variants.

## Known limitations (honest, not yet addressed)

- **No live NBC/UAT environment was reachable from this dev machine.** All
  verification used a local synthetic fixture app
  (`storage/fixtures/nbc_sim/app.py`), extended in Phase 2 with a Maker-Checker
  approval flow. Running against a real NBC application is the next real-world
  validation step.
- **"Healed" currently covers two distinct cases**: a field whose stored locator
  broke, *and* a field with no stored locator at all yet (e.g. right after wiping the
  Locator Repository). Both go through the same re-crawl-and-match fallback and are
  flagged `healed=true`, which is functionally correct (the field still gets filled)
  but is a slightly imprecise label — a future pass could distinguish "healed" from
  "freshly discovered."
- **Validation-message association is over-broad** on flatly-laid-out forms (no
  per-field wrapper element) — see Phase 1 notes; unchanged in Phase 2.
- **Wizard/popup/click navigation heuristics are keyword- and text-based** ("next"/
  "continue", "submit for approval", "approve", button text matching) — a real NBC
  screen with different wording may need the hint lists extended.
- **Self-healing is deterministic-by-default with an optional LLM explanation** (one
  sentence, informational only) — it does not yet rank multiple LLM-proposed
  alternative locators as the full spec describes; that's a Phase 2b enhancement.
- `maker_checker_agent.generate_maker_checker_feature_text` exists to generate a
  feature file from structured inputs, but the Execution Center UI doesn't yet have a
  "simple mode" form wired to it (Phase 4's credential vault covers *where
  credentials live*, not generating feature files from a form).
- **The crawler's destructive-action blacklist is keyword-based**
  (`crawl_orchestrator._BLOCKED_HINTS`), same category of limitation as the
  navigation hint lists below — a real NBC screen using different wording for a
  destructive action (a button labelled in a way that doesn't match any blacklisted
  keyword) would not be recognized as destructive and could be auto-clicked during a
  crawl. The list was built from the action words the user's own shared materials and
  this phase's testing surfaced; extending it for real NBC screens before a live
  crawl is recommended.
- **The 5 locator file formats use one canonical column schema** (documented in
  `locator_file_parsers.py`'s module docstring), not an attempt to auto-detect
  arbitrary third-party schemas — a file from a different tool would need its columns
  renamed to match first.
- Decimal sub-versions from the spec (1.0 → 1.1 → 2.0) are simplified to plain integers
  for this slice.
- **Execution video is a screenshot timelapse (each step's before/after frame held
  ~1.5s), not continuous real-time screen capture** — documented plainly above, not
  oversold. A continuous-recording feature would need browser-side casting or OS-level
  screen capture, neither of which exists in this stack today.
- **Visual/image-based element matching is a permanent non-goal**, not a deferred
  phase — no CV/image-matching library is in this stack, and the existing
  id/name/css/xpath + self-healing chain already covers the platform's real locator-
  resolution needs.
- Not yet built, and not currently planned: Docker/Render deployment (per explicit
  instruction to exclude it).
