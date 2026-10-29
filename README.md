# Culture Connect

**Different people. Shared passions. Real human connections.**
Built for the Qloo Agentic Hackathon 2026.

Culture Connect helps people who don't know each other form small groups and meet through a shared, inclusive activity. It's not tied to one use case. A retired chess player can be matched with a student who wants to learn chess. Neighbours can meet around a cause, sports fans across generations, people who want respectful political dialogue, people learning about the same health topic, artists and makers, and so on. **Qloo is at the centre**: every connection and every plan cites evidence that came from a real Qloo response or from what a participant typed in.

## How it works

| Step | What happens | Qloo routes |
|---|---|---|
| 1. Create group | The organizer adds synthetic participants. For each one: interests in any domain, the intent for each interest (*enjoys / can teach / wants to learn*), and consent. Also goals, duration, budget, setting and group size. | — |
| 2. Match to Qloo | Each typed interest is resolved to Qloo **entities**, **tags** and **audiences** (causes, politics, hobbies, life stage…). The organizer confirms the matches. | `GET /search`, `GET /v2/tags`, `GET /v2/audiences` |
| 3. Discover | For each person, Qloo runs taste analysis (`filter.type=urn:tag`) and makes cross-domain recommendations. The bridge engine counts overlaps it can trace back to their source, then clusters people into groups. | `GET /v2/insights` |
| 4. Plan | A bounded agent runs these steps in order: discover_culture → build_bridges → generate_event → review_event → revise_event. It queries Qloo with the whole group's signals (with **explainability** on) to find shared anchors (books, podcasts, films, artists) and nearby venues (`filter.location.query`). It drafts 2 concepts and cites evidence ids for every claim. | `GET /v2/insights` |
| 5. Review | The organizer changes constraints, rejects ideas or themes, or gives free-text feedback, and the agent revises the plan. A **no-Qloo baseline** runs on the same inputs and is shown side by side. | — |

### Bridge engine: a transparent heuristic
- Same confirmed Qloo ID: +3. Teach↔learn match: +5. Same typed label: +2.
- Shared Qloo taste tags: up to +2. Shared Qloo recommendations: up to +1.5.
- “Crossover” (my pick appears in your Qloo results): +1.5 each.
- Same area: +1.

This score is **not** a validated compatibility score, and Qloo is never claimed to measure interpersonal compatibility.

## Individuals & Circles (self-serve)

Alongside the organizer workflow, **anyone (18+) can join as an individual** and be matched into **Circles**: small, persistent groups built around a shared interest or issue. The interest can be anything from chess, cricket or Minecraft to climate action, diabetes or local politics.

**The journey:** Join → add your interests (type them, drag quick-pick bubbles, or bring a draft from the home-page Qloo playground) → confirm the Qloo matches → choose your privacy and consent settings → get **recommended Circles** with explanations → join, or create a new Circle → discuss → **plan an activity with the agent** → members vote → a host confirms → members RSVP.

| Area | What it does |
|---|---|
| Qloo | Interests are resolved with the existing `/search`, `/v2/tags` and `/v2/audiences` calls. The server re-checks every submitted Qloo ID against a resolution it performed itself; IDs it didn't see are dropped. IDs, labels and retrieval timestamps are stored. Taste insights (`/v2/insights`, `filter.type=urn:tag` + recommendations) are cached per user for 24 h. |
| Matching | Deterministic. **Hard constraints first:** adults only, capacity, blocks, excluded topics, accessibility commitments, meeting mode, area and language. Only then are Circles ranked by declared matches (same Qloo ID or label), Qloo-derived links (a Circle's topic appears in your Qloo taste results), intent and area. Each reason is labelled *Declared*, *Qloo-derived* or *Preference*. There are no percentages. |
| Circles | Public Circles are discoverable. Private Circles are invite-code plus host approval. Each topic/area pair can have one active public Circle (enforced by a unique index). Health and political Circles get pinned notices. Community guidelines, reporting, blocking, moderators and host transfer are included. |
| Discussion | Posts and one level of replies, paginated. Edit or delete your own posts; moderators can hide or delete. Duplicate posts and rate limits are checked server-side. |
| Events | Reuses `planner.run_agent`, fed only Circle-approved data. It produces 2 options, each with a constraint checklist computed in application code, evidence references and open questions. Members vote on options and times. Only a host or moderator can confirm, and confirmation re-validates the hard constraints. RSVPs open after confirmation and are capped at the event's capacity. Nothing is booked or sent automatically. |

**Identity.** The project had no auth. Each individual gets a random 256-bit bearer token (only its SHA-256 hash is stored). The browser keeps the token and the person can export it as a private **recovery key**. This is pseudonymous: there's no email verification. Swap `backend/auth.py` for a real identity provider before running it as a public production service.

**Deletion policy.** `DELETE /api/me` removes the profile, interests, Qloo mappings, taste cache, memberships, votes, RSVPs and blocks. Posts are erased (body removed, author detached) so threads keep a placeholder. Hosted Circles pass to a moderator or the longest-standing member, or are archived if empty. Withdrawing discovery consent deletes the cached Qloo taste profile.

### Database migrations
SQLite with reversible SQL files in `backend/migrations` (`NNNN_name.up.sql` / `.down.sql`). They are applied automatically at startup.
```
python -m backend.db status      # applied versions
python -m backend.db up          # apply pending
python -m backend.db down 0002   # roll back 0003 and 0002 (Circles); organizer data untouched
```

### Circle API (all authorization is enforced server-side; send `Authorization: Bearer <token>`)
`POST/GET/PUT/DELETE /api/me`, `PUT /api/me/consent`, `GET /api/me/circles|events|blocks`, `POST /api/me/blocks`,
`GET /api/circles/recommendations`, `GET|POST /api/circles`, `GET|PATCH /api/circles/{id}` (`?invite=` for private), `POST /api/circles/{id}/join|leave`,
`GET /api/circles/{id}/members`, `POST /api/circles/{id}/members/{user}`, `GET|POST /api/circles/{id}/posts`, `PATCH|DELETE /api/circles/{id}/posts/{pid}`,
`POST /api/circles/{id}/posts/{pid}/hide`, `GET|POST /api/circles/{id}/reports`, `POST /api/circles/{id}/reports/{rid}/resolve`,
`GET|POST /api/circles/{id}/events`, `GET /api/circle-events/{eid}`, `POST /api/circle-events/{eid}/vote|confirm|cancel|rsvp`.

### Verify end to end
1. Home → drag *Jazz* into Qloo → **Add to my draft profile** (no account or Circle is created).
2. **Join** → add *Chess* (intent *Can teach*), alias, area, 18+, consent → save your recovery key.
3. **Circles** → there's no match yet → **Create "Chess" Circle** (minimum 2).
4. In a second browser/incognito window: Join with *chess* (*Want to learn*), same area → the Chess Circle is recommended with a *Declared* reason → **Join**.
5. Post and reply in **Discussion**. Under **Events**, propose a 90-minute, 20-USD activity with 2 time options → vote.
6. As the host: confirm option + time → RSVP **Going**. Check **My Circles**.
7. Create a *Diabetes* Circle → the health topic type is suggested → a pinned "not medical advice" notice appears.

### Tests
`python -m pytest -q tests`: 22 tests covering the bridge engine, organizer workflow regression, onboarding/consent, Qloo ID verification and failure, playground-creates-nothing, matching (declared vs Qloo, hard constraints), creation dedupe and race, capacity/duplicate membership, private-Circle authorization, discussion CRUD, reporting/blocking, event proposal/vote/confirm/RSVP, constraint enforcement, account deletion and migration rollback. Qloo is faked in tests (no network).

## Run it locally (Windows)

```bat
cd C:\Users\11991\Desktop\QLOO
run.bat
```

`run.bat` creates `.venv`, installs the requirements, runs the Qloo smoke test (Checkpoint 1) and then serves the app at **http://localhost:8000**.

Manual setup:
```powershell
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\qloo_smoke_test.py      # every endpoint should print OK
python -m uvicorn backend.main:app --port 8000 --reload
```
Tests: `python -m pytest -q tests`

## Configuration (`.env`, server only)
| Variable | Purpose |
|---|---|
| `QLOO_API_KEY` | Hackathon key (sent only as the `X-Api-Key` header, from the backend) |
| `QLOO_BASE_URL` | `https://hackathon.api.qloo.com` |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | Optional: `openai` (or any OpenAI-compatible endpoint), `anthropic` or `gemini`. With `none`, a transparent rule-based planner is used. |
| `DISCOVERY_TYPES` | Qloo output categories used for group anchors |
| `CORS_ORIGINS` | Allowed frontend origins in deployment |

## Architecture
```
Browser (frontend/: vanilla JS SPA)  ->  FastAPI backend (backend/)  ->  Qloo Hackathon API
                                         ├─ qloo_client.py   key, retries, cache, audit log (no secrets)
                                         ├─ qloo_service.py  resolve / taste profile / group anchors
                                         ├─ bridges.py       pairwise evidence + grouping
                                         ├─ planner.py       bounded agent, review, auto-fix, revise
                                         ├─ llm.py           optional LLM adapter
                                         └─ store.py         SQLite (synthetic demo data)
```
API: `POST /api/interests/resolve`, `/api/discovery/run`, `/api/bridges/build`, `/api/events/generate`, `/api/events/revise`, `/api/events/approve`, `/api/events/compare`, `GET /api/health`, `/api/qloo/check`, `/api/audit`, `/api/programs/{id}/export`.

The **Qloo calls** drawer in the UI shows every real request the backend made, so judges can trace any piece of evidence back to the call that produced it.

## Privacy and safety
- Use synthetic profiles for demos. Only interests that people volunteer are collected. Nothing is inferred about health, loneliness or personality.
- Participants who haven't given consent are excluded from matching.
- Contact sharing is opt-in only.
- When minors are present, the plan adds safeguarding requirements (an authorized organization, guardian consent, the two-adult rule).
- Sensitive topics add a facilitator and a note that nothing in the session is medical or legal advice.
- The app never messages participants, books venues or publishes photos. The organizer approves everything.

## Deploying
Host the backend on any Python host, such as Render, Railway, Fly or Azure App Service. The start command is `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. Set `QLOO_API_KEY` as a secret on the host, and set `CORS_ORIGINS` to your public URL. The frontend is served by the same app.

## Known limitations
- Response normalization handles the documented Qloo shapes. If the hackathon key exposes a different shape for a route, adjust `backend/qloo_service.py`.
- `/v2/audiences` has no free-text filter, so the app pages each audience parent type once and matches names locally.
- Cost estimates are format defaults that the organizer should verify.
- Rate limiting is in-process (per server instance). Self-serve identity is pseudonymous (token-based).
- Circle discussion is not real-time; refresh or post to see new messages.

License: MIT
