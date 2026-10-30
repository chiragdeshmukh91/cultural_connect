# Culture Connect

**Different people. Shared passions. Real human connections.**
Qloo-powered Circles that turn shared taste into real meetups — built for the Qloo Agentic Hackathon 2026.

- **Live app:** `https://<YOUR-DEPLOYED-URL>` *(placeholder until deployed)*
- **Full feature & workflow description:** [docs/FEATURE_WALKTHROUGH.md](docs/FEATURE_WALKTHROUGH.md)
- **Judge guide:** [docs/JUDGE_TESTING_GUIDE.md](docs/JUDGE_TESTING_GUIDE.md)
- **Submission docs:** [docs/](docs/)

## 1. Overview
Culture Connect is a culturally intelligent community discovery and coordination platform. Members describe what they enjoy; Qloo turns that into taste signals; the app recommends small local **Circles** and real activities with the reason for each; and supervised agents help hosts and organisations form groups, plan activities, collect votes and RSVPs, and follow up.

## 2. Problem
People who share a cultural taste — jazz, poetry, film, street food, chess — often live in the same city without ever meeting. Event listings rank by popularity or keywords, so related tastes are missed. Organisers guess what a group will enjoy and chase availability and RSVPs by hand.

## 3. Solution
- **Members** get taste-based recommendations of Circles and activities, explained with labelled reasons (**You said**, **Qloo**, **App**).
- **Hosts and organisations** publish multiple activities, track RSVPs, attendance and feedback, and let planning agents draft options from Qloo cultural anchors and Qloo places near the Circle.
- **Everything is traceable:** each Qloo request appears in the in-app **Qloo calls** drawer; each agent step is logged with its data sources.

## 4. Key features
| Area | Features |
|---|---|
| Cultural discovery | Free-text interests resolved to Qloo entities, tags and audiences; server-side verification of Qloo ids; *Discover something new* from Qloo Insights |
| Personalised recommendations | Discovery workflow after sign-up; Circles and events ranked with Qloo-supported reasons; outage-safe (*degraded* mode) |
| Circle matching | Same-Qloo-id and Qloo-Insights matching, intent fit (teach ↔ learn), area, hard constraints first |
| Organisation management | Owner/staff roles, team invites, admin verification, dashboard |
| Multiple activities | Draft → publish → update with reason → cancel → complete; capacity, deadline, cost, accessibility, safety |
| Agentic planning and coordination | Circle formation by invitation, activity planning, voting, approval or auto-publish, reminders, follow-up |
| Invitations and RSVP | Agent invitations (accept / decline), Circle join requests, event RSVP with capacity, attendance |
| Feedback and personalisation | Save / dismiss recommendations, event feedback that excludes poorly rated formats |
| Photos | Upload a profile picture, Circle photo, event photo and organisation logo (PNG/JPEG/WebP/GIF, type checked from the file bytes, 3 MB max) |
| Privacy and user controls | Discovery consent, show-area and share-interests toggles, blocking, account deletion, invitations show counts only |

## 5. Screenshots
Captured from the deployed app — see [docs/SCREENSHOT_CHECKLIST.md](docs/SCREENSHOT_CHECKLIST.md). *(To be added in `docs/screenshots/`.)*

## 6. Architecture
```
Browser (vanilla JS SPA)  →  FastAPI backend  →  Qloo Hackathon API
                              ├─ auth.py            accounts, sessions, rate limits
                              ├─ circles*.py        profiles, Circles, recommendations
                              ├─ platform_*.py      organisations, events, RSVP, chat, notifications
                              ├─ agents*.py, jobs.py  persistent agent workflows + worker
                              ├─ planner.py, bridges.py  evidence-cited plans, bridge scoring
                              ├─ qloo_service.py, qloo_client.py  Qloo calls, cache, retries, audit
                              └─ llm.py (optional), mailer.py (optional), geo.py (optional)
                                       ↓
                                 SQLite (migrations 0001–0007)
```
Details and Mermaid diagrams: [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

## 7. Qloo integration
| Endpoint | Used for |
|---|---|
| `GET /search` | Interest → Qloo entities |
| `GET /v2/tags` | Interest → Qloo tags |
| `GET /v2/audiences` | Audience catalogue, matched by name |
| `GET /v2/insights` | Taste tags (`urn:tag`), cross-domain recommendations, group anchors with explainability, places near an area |

Qloo influences ranking directly: the same Qloo id as a Circle's topic counts +3, a Circle topic returned by the member's Qloo Insights counts +1.5 (max 3), and Qloo-matched events get a Qloo reason. Full request/response details: [docs/QLOO_INTEGRATION.md](docs/QLOO_INTEGRATION.md).

## 8. Agent workflows
| Trigger | Workflow | Human checkpoint |
|---|---|---|
| Profile saved with consent | `discovery`: resolve → Qloo insights → match Circles → match events → rank → store | — (read-only recommendations) |
| No Circle fits an interest | `circle_formation`: hard constraints → points → invite | People accept or decline; Circles form only from acceptances |
| Circle reaches minimum size / **Plan now** | `event_planning`: Qloo anchors + places → 2–3 options → venue and schedule checks → draft | Members vote |
| Vote deadline or all voted | `coordinate_proposal`: tally → publish or ask the host | Host approves (default policy) |
| Every 30 s sweep | `event_followup`: reminders, low-RSVP nudge, completion, feedback | — |

Runs are persisted (`agent_runs`, `agent_steps`) with idempotency keys, retries and resumable steps, and shown in the **Agent Activity Centre** (`#/agent`) with pause / resume / retry / cancel.

## 9. Technology stack
Python 3.10+ · FastAPI · Uvicorn · Pydantic v2 · Requests · SQLite · vanilla JavaScript, HTML, CSS · Qloo Hackathon API · optional LLM (OpenAI-compatible, Anthropic, Gemini) · optional SMTP · optional OpenStreetMap / Nominatim · pytest · Render.

## 10. Folder structure
```
backend/            FastAPI app, services, agents, migrations/
frontend/           index.html, app.js, circles.js, platform.js, agents.js, workspace.js, theme.js, fx.js, styles.css, assets/
scripts/            qloo_smoke_test.py, agent_live_check.py, seed_demo.py
tests/              pytest suite (48 tests; Qloo, email and geocoder faked)
docs/               submission documentation
render.yaml         Render Blueprint
run.bat / run.sh    local start scripts
```

## 11. Prerequisites
Python 3.10 or newer, Git, and a Qloo hackathon API key. No Node.js or frontend build is needed.

## 12. Environment configuration
Copy `.env.example` to `.env` in the project root and set at least `QLOO_API_KEY`. The `.env` file is git-ignored; never commit it.

| Variable | Required | Purpose |
|---|---|---|
| `QLOO_API_KEY` | yes | Sent only from the backend as `X-Api-Key` |
| `QLOO_BASE_URL` | yes | `https://hackathon.api.qloo.com` |
| `APP_BASE_URL`, `CORS_ORIGINS` | in production | Public URL (email links) and allowed origins |
| `DB_PATH` | optional | SQLite file (default `data/culture_connect.db`) |
| `UPLOAD_DIR`, `UPLOAD_MAX_BYTES` | optional | Uploaded photos (default `uploads/` next to the database; 3 MB max). Keep it on the same persistent disk |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | optional | `none` (default, rule-based) / `openai` / `anthropic` / `gemini` |
| `DISCOVERY_TYPES` | optional | Qloo output categories for insights |
| `SMTP_*`, `ADMIN_EMAILS`, `GEOCODER`, `NOMINATIM_EMAIL`, `SESSION_DAYS` | optional | Email, organisation verification admins, address search, session length |
| `AGENT_WORKER`, `AGENT_VOTE_HOURS`, `AGENT_MIN_CIRCLE`, `AGENT_SWEEP_SECONDS` | optional | Background agents (defaults 1 / 48 / 3 / 30) |

## 13. Installation
```bash
git clone https://github.com/chiragdeshmukh91/cultural_connect.git
cd cultural_connect
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # Windows: copy .env.example .env  — then edit QLOO_API_KEY
```

## 14. Local development
Windows: double-click or run `run.bat` (creates `.venv` if missing, installs requirements, runs the Qloo smoke test, starts the server).
macOS/Linux/WSL: `./run.sh`.
Manual: `python -m uvicorn backend.main:app --port 8000 --reload`, then open http://localhost:8000.

## 15. Database setup and migrations
SQLite migrations in `backend/migrations` are applied automatically at startup. Manual control:
```bash
python -m backend.db status
python -m backend.db up
python -m backend.db down 0006     # undo every applied migration >= 0006 (newest first)
```

## 16–17. Frontend and backend startup
One process serves both: the FastAPI app serves the API under `/api/*` and the static frontend from `frontend/`. There is no separate frontend server.

## 18. Qloo API configuration
Set `QLOO_API_KEY` and `QLOO_BASE_URL` in `.env`, then verify:
```bash
python scripts/qloo_smoke_test.py               # each endpoint prints OK
python scripts/agent_live_check.py "jazz" "Pune"  # fields the agents use
```
With the server running, `GET /api/health` and `GET /api/qloo/check` confirm the configuration (the key is never returned).

## 19. LLM configuration
Optional. Leave `LLM_PROVIDER=none` for the transparent rule-based planner, or set `LLM_PROVIDER`, `LLM_API_KEY` and `LLM_MODEL` (and `LLM_BASE_URL` for OpenAI-compatible endpoints). The LLM only drafts plan text from evidence the backend supplies; permissions, matching and persistence stay in code.

## 20. Deployment
`render.yaml` is a Render Blueprint (one web service, `--workers 1`, persistent disk for SQLite). Step-by-step: [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md).

## 21. Tests
```bash
python -m pytest -q tests
```
50 tests covering accounts, organisations, events and RSVP, Circles, chat, place polls, discovery, agent workflows and the organiser programme. Qloo, email and geocoding are faked, so the suite runs offline.

## 22. Demo accounts and testing
Dedicated demo accounts (Sanika — member, Chirag — organiser) are created on a deployment with:
```bash
python scripts/seed_demo.py --base https://<YOUR-DEPLOYED-URL> --password "<strong demo password>"
```
Credentials go in the Devpost testing-instructions field, not in this repository. Scenarios: [docs/JUDGE_TESTING_GUIDE.md](docs/JUDGE_TESTING_GUIDE.md).

## 23. Known limitations
No chat assistant UI, no external event or booking provider, chat polls every 5 s, SQLite + single worker, results depend on live Qloo data. Full list: [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## 24. Future improvements
Verified external event sources, real-time chat, multilingual interest matching, organisation analytics on which cultural themes bring people back, and a shared store for rate limits to run several instances.

## 25. Team
| Member | Role |
|---|---|
| Chirag Deshmukh | Technical Lead — architecture, backend, Qloo integration, agents |
| Sanika Satpute | Full-stack Developer — frontend/UI, product research, testing, docs and pitch |

Details: [docs/TEAM_CONTRIBUTIONS.md](docs/TEAM_CONTRIBUTIONS.md).

## 26. Licence
MIT — see [LICENSE](LICENSE).

## Privacy and safety
Only interests people volunteer are collected; nothing is inferred about health, personality or loneliness. Qloo receives interest text and Qloo ids (plus a Circle's or programme's area for venue search) — never names, emails, bios, budgets, availability or accessibility needs. Discovery needs consent; contact sharing is opt-in; invitations show counts, not identities; hosts approve publication by default. Passwords are hashed with scrypt; sessions are stored as hashes; the app never books venues and never invents venues, dates or attendee counts.
