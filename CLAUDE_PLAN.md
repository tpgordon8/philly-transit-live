# Septer — Claude execution plan

Paste the **Mission brief** into Claude to start. Everything below it is the
plan Claude's agents must follow. Human owner: repo owner (@tpgordon8).
Repo: `tpgordon8/philly-transit-live` (GitHub Pages, `main` branch, root).
Live URL: https://tpgordon8.github.io/philly-transit-live/

---

## MISSION BRIEF (paste into Claude)

You are running a multi-agent build on the repo `tpgordon8/philly-transit-live`,
a single-page SEPTA live transit tracker served via GitHub Pages. You have
already built this app and its Cloudflare Worker proxy, so you know the
codebase. Implement the improvement plan in the file `CLAUDE_PLAN.md` at the
repo root (create it from the full text I provide after this brief).

Agent structure — set this up first, before any feature work. Use your
subagents for all three roles:
1. **Architect agent** — owns the plan, decomposes tasks, reviews every change,
   runs the verification checklist, and is the SOLE gatekeeper for pushing to
   `main` and publishing. Nothing ships without the architect's explicit
   approval. The architect never approves its own work unreviewed: the QA
   subagent must sign off on test evidence first.
2. **Developer subagents** — one per task, working on feature branches named
   `feat/<task-slug>`. They implement, self-test, and hand their branch to the
   architect with test evidence attached. They never push to `main` directly.
3. **QA subagent** — executes the test checklist for each completed branch,
   reports pass/fail to the architect with evidence (screenshots, console
   logs, network traces).

Workflow per task: architect assigns → developer subagent implements on a
branch → hands branch + test evidence to architect → QA subagent runs the
checklist → architect reviews the diff + QA report → architect merges to
`main` and pushes → architect verifies on the LIVE Pages URL → architect
marks the task done. If live verification fails, the architect reopens the
task; the fix goes through the same pipeline.

---

## 0. PHASE 0 — Architect audit (do this first)

- Read the entire `index.html` and the Cloudflare Worker source
  (`septa-proxy.tpgordon8.workers.dev`).
- Write `ARCHITECTURE.md` in the repo documenting: data flow
  (page → worker → SEPTA), caching behavior, the ghost-bus filter rules,
  marker rendering, refresh loop, and localStorage schema.
- Confirm the deployment pipeline: push to `main` → GitHub Pages rebuild →
  live URL. Record how long a deploy takes.
- Deliverable: `ARCHITECTURE.md` + a task breakdown with estimates, approved
  by the architect before Phase 1 starts.

## SYSTEM FACTS (non-negotiable, bake into every task)

- SEPTA endpoints (via the worker proxy only): `TransitView/index.php?route=`
  (buses/trolleys), `TrainView/index.php` (Regional Rail), `Alerts/index.php`.
  The worker allowlists endpoints — adding a new SEPTA endpoint requires a
  worker change, which the architect must approve and deploy first.
- `api.septa.org` sends no CORS headers. The page must NEVER call SEPTA
  directly; all traffic goes through the worker.
- GHOST-BUS FILTER (all must hold, else drop the vehicle):
  - Require a real, non-empty vehicle ID and vehicle label.
  - Drop records with `VehicleID: "None"` or empty, and `late: 998`
    (schedule-only records masquerading with fresh timestamps).
  - `late: 999` means "no delay data" — display "Delay data unavailable",
    never "999 minutes late".
  - Buses with no heading get a gray "?" direction badge, not a guessed
    direction.
  - `TrainView` provides no timestamps, so the freshness rule cannot apply to
    rail — say so on train detail cards instead of filtering them.
- On proxy/API failure: show the honest "Live data unavailable" state.
  NEVER invent, interpolate-as-fact, or guess vehicle positions.
- Refresh vehicle positions every 15 seconds in place. Never remount the map
  or reset the user's zoom/pan on refresh.
- Free-tier budget: keep the worker under 100,000 requests/day. Cache SEPTA
  responses for a few seconds; batch route requests where possible.
- The page is public. Never hardcode a home address or personal data into the
  repo. Personal state lives in `localStorage` only.

## PHASE 1 — Client-only wins (low risk)

### Task 1.1 — "My routes" preset
- Let the user star routes; store in `localStorage`.
- On load, if starred routes exist, default the map filter to them (with a
  clear "showing my routes / show all" toggle).
- Acceptance: starring survives reload; toggle works; empty state (no stars)
  shows all routes as today.

### Task 1.2 — Shareable stop links
- Every stop gets a linkable URL (e.g. `#stop=<id>`); opening the link centers
  the map on that stop and opens its board (see Phase 2 for the board; in
  Phase 1 the link may open the stop's vehicle list).
- Add a "copy link" button on stops.
- Acceptance: pasting the link in a fresh browser reproduces the same stop
  view; links never contain personal data.

## PHASE 2 — Stop board view

### Task 2.1 — Stop board
- Tapping a stop opens a board listing the next arrivals with live ETAs
  computed from current vehicle positions, headings, and distances
  (no invented times — if a prediction can't be computed, say so).
- Board shows route badge, direction badge, destination, and minutes away.
- Acceptance: ETAs update on the 15-second refresh; stale predictions are
  removed, never left frozen.

## PHASE 3 — "Leave now" alerts (needs backend work)

### Task 3.1 — Alert engine (Cloudflare Worker)
- Add a Worker scheduled trigger (cron, every 1–2 minutes) that checks saved
  alert rules against live SEPTA data and writes "leave now" states to Worker
  KV. Architect must confirm this stays within free-tier limits.
- Rules are created in the page UI ("alert me when route 57 is < 8 min from
  stop X") and stored per-browser; the worker evaluates them.
- Acceptance: KV contains fresh evaluations; worker logs show no errors;
  daily request count stays far under the free cap.

### Task 3.2 — In-page notifications
- While the page is open, poll the worker's alert states and fire a "Leave
  now — the 57 is 6 minutes from your stop" banner + `Notification` API
  prompt (with permission request UX that explains why).
- Acceptance: alert fires within one refresh cycle of the condition becoming
  true; no alert fires on stale data; dismissing works.

### Task 3.3 (stretch) — True push notifications
- Only after 3.2 is live and verified: add Push API + VAPID subscriptions so
  alerts arrive with the page closed. Architect decides if the complexity is
  worth it; default is to defer.

## GATEKEEPER CHECKLIST (architect runs this on the LIVE URL before marking
any task done)

- [ ] Page loads with no console errors.
- [ ] Status reads "Live"; vehicle markers render with route + direction
      badges; counts are sane (tens of vehicles, not zero, not thousands).
- [ ] No ghost buses: spot-check 5 markers against raw SEPTA data — every
      shown vehicle has a real vehicle ID.
- [ ] 15-second refresh moves markers in place; zoom/pan untouched.
- [ ] Proxy failure simulation (worker paused) shows the honest unavailable
      state — no fake positions.
- [ ] New feature works per its acceptance criteria, on desktop and mobile
      viewports.
- [ ] No personal data in the repo; `localStorage` only.
- [ ] No regressions in existing features (search, saved places, Get Me Home,
      alerts panel).

## COMMUNICATION

- Developer subagents report blockers to the architect, not to the human,
  unless blocked > 1 hour or needing credentials/access — then the architect
  summarizes ONE clear question for the human.
- The human gets a short status per completed task: what shipped, the live
  link to verify, and anything needing her eyes on her phone (location
  button, notifications permission, etc.).
- Rename the plan file to `CLAUDE_PLAN.md` (not `CLAUDE_PLAN.md`) when you
  create it in the repo.
