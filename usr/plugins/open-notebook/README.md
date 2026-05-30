# Open Notebook Plugin for Agent Zero

A knowledge management plugin that integrates [Open Notebook](https://github.com/lfnovo/open-notebook) into Agent Zero's WebUI, providing notebooks, source management, name-based fuzzy lookup, notes, and podcast generation — all from a sidebar panel.

## Features

### Notebooks
- Browse notebooks and inspect notebook details
- Name-based source and note lookup
- Notebook-scoped workflows for browsing, adding, and querying content

### Sources
- Import by **URL**, **text**, or **local file path**
- View processing status with colored badges
- Retry failed source processing
- Delete sources from the panel

#### Supported Local File Types
When using the `opennotebook_sources:add` tool, local files with the following extensions are automatically detected, read, and uploaded as text:

| Category | Extensions |
|----------|------------|
| Documents | `.pdf`, `.doc`, `.docx`, `.odt`, `.rtf`, `.epub` |
| Text & Web | `.txt`, `.md`, `.html`, `.htm` |
| Data | `.csv` |

**Behavior:**
- Content is read from the local filesystem and uploaded to the Open Notebook backend.
- The title defaults to the filename if one is not provided.
- Errors (e.g., permission denied, file not found) return actionable guidance.

### AI Chat
- **Notebook chat** — session-based conversations scoped to a notebook
- **Source chat** — chat about a specific source (SSE streaming)
- Rename and delete chat sessions
- Copy AI responses to clipboard

### Notes
- Full CRUD: create, read, edit, delete
- Inline editing with save/cancel

### Podcasts
- Generate podcasts per notebook with profile selection
- Episode and speaker profile dropdowns (auto-selected)
- Job polling with progress status
- Audio playback with play/pause controls

### UI/UX
- Theme-adaptive via Agent Zero CSS variables
- Chat-shift panel pushes main chat left (like Honcho)
- Resizable panel (300-800px) with double-click reset
- Mobile responsive with overlay mode
- Text selection, copy buttons, Escape to close
- Empty states for all tabs
- "Send to Chat" bridges plugin results to Agent Zero chat

## Architecture

```
Agent Zero WebUI
├── Sidebar Extension Point
│   └── open-notebook-sidebar.html  (Alpine.js templates)
├── Page Head Extension Point
│   └── open-notebook-head.html     (CSS styles)
└── Plugin Static Files
    ├── webui/open-notebook-store.js (Alpine.js store)
    └── extensions/webui/
        ├── sidebar-end/             (HTML + store source)
        └── page-head/               (CSS source)

Open Notebook API (port 5055)
├── /api/notebooks       (CRUD)
├── /api/sources         (import, delete, insights, status, retry)
├── /api/notes           (CRUD)
├── /api/chat/*          (session-based notebook chat)
├── /api/sources/{id}/chat/*  (source-scoped chat)
└── /api/podcasts/*      (generate, episodes, audio)
```

## File Structure

```
/a0/usr/plugins/open-notebook/
├── README.md
├── plugin.yaml
├── webui/
│   └── open-notebook-store.js       (Alpine.js store, served to browser)
├── extensions/
│   └── webui/
│       ├── sidebar-end/
│       │   ├── open-notebook-sidebar.html  (HTML templates)
│       │   └── open-notebook-store.js      (store source, must stay in sync)
│       └── page-head/
│           └── open-notebook-head.html     (CSS styles)
├── tools/
│   ├── open_notebook_browse.py      (notebook/source browsing)
│   ├── open_notebook_podcast.py     (podcast generation)
│   └── opennotebook_query.py        (name-based lookup)
└── requirements.txt
```

## Prerequisites

- **Agent Zero** running with WebUI enabled
- **Open Notebook** backend on port 5055
- **Open Notebook** UI on port 8502 (optional, for standalone use)

## Installation

1. Place this folder at `/a0/usr/plugins/open-notebook` inside the Agent Zero installation.
2. Ensure `plugin.yaml` and the bundled webui assets are present.
3. Restart or reload Agent Zero so the plugin can be discovered.
4. Confirm the Open Notebook backend is reachable on port 5055 (or set `OPEN_NOTEBOOK_API_URL`).


## Connection & Configuration

The WebUI dynamically discovers the backend at runtime. Python tools use the plugin `api_url` setting (with environment override support) as the backend default.

| Environment | Method | URL |
|---|---|---|
| Browser (local) | Direct connect | `http://localhost:5055` |
| Browser (remote) | A0 proxy | `/api/plugins/open-notebook/proxy` |
| Docker (server-side) | Direct | `http://host.docker.internal:5055` |

### Detection Flow (on page load)
1. If local: try direct `localhost:5055` connection
2. Fall back to A0 proxy mode (routes through `/api/plugins/open-notebook/proxy`)

## Service Worker Caching

The A0 WebUI includes a Service Worker (`/sw.js`) that caches static assets for faster repeat page loads.

| Asset Type | Strategy | Behavior |
|---|---|---|
| Vendor JS/CSS/fonts | Stale-While-Revalidate | Instant from cache, background update |
| HTML pages | Network-First | Always fresh, cache fallback |
| API/WebSocket | Network-Only | Never cached |
| CDN (Bootstrap) | Cache-First | Cached with no-cors |

Pre-cached on install: ~25 critical assets (ace.js, katex, fonts, CSS, etc.)
Cache version: `a0-static-v1` — bump in `/a0/webui/sw.js` to bust cache.

## API Endpoints

### Notebooks
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/notebooks` | List all |
| POST | `/api/notebooks` | Create |
| PUT | `/api/notebooks/{id}` | Rename |
| DELETE | `/api/notebooks/{id}` | Delete |

### Sources
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/sources?notebook_id={id}` | List for notebook |
| POST | `/api/sources/json` | Add URL/text |
| POST | `/api/sources` | Upload file |
| DELETE | `/api/sources/{id}` | Delete |
| GET | `/api/sources/{id}/status` | Processing status |
| POST | `/api/sources/{id}/retry` | Retry failed |
| GET/POST | `/api/sources/{id}/insights` | AI insights |

### Notes
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/notes?notebook_id={id}` | List |
| POST | `/api/notes` | Create |
| PUT | `/api/notes/{id}` | Update |
| DELETE | `/api/notes/{id}` | Delete |

### Chat
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/chat/sessions` | Create session |
| POST | `/api/chat/context` | Build context |
| POST | `/api/chat/execute` | Execute (JSON) |
| PUT | `/api/chat/sessions/{id}` | Rename |
| DELETE | `/api/chat/sessions/{id}` | Delete |

### Source Chat
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/sources/{id}/chat/sessions` | Create session |
| POST | `/api/sources/{id}/chat/sessions/{sid}/messages` | Send (SSE) |

### Podcasts
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/podcasts/episodes` | List episodes |
| POST | `/api/podcasts/generate` | Generate |
| GET | `/api/podcasts/jobs/{id}` | Job status |
| GET | `/api/podcasts/episodes/{id}/audio` | Stream audio |

## Panel Layout

```
+--------------------------------------------+
| Agent Zero Top Bar (0-60px)                |
+----------+------------+--------------------+
| Left     |  Chat      | [Back] Title [X]   |
| Sidebar  |  Window    |                    |
| 250px    | (shifted)  | [Tab Content]      |
|          |            |                    |
|          |            | <-- Resizable 300-800 -->|
+----------+------------+--------------------+
```

**Tabs:** Sources | Notes | Chat | Podcasts

## Development Notes

### Dual-Path Deployment

The store must exist at two paths and stay in sync:
- `extensions/webui/sidebar-end/open-notebook-store.js` (source)
- `webui/open-notebook-store.js` (served to browser)


### Connection Detection
The store uses `isLocalAccess()` to check if the browser is on localhost. Remote browsers never attempt direct `localhost:5055` connections, avoiding `ERR_CONNECTION_REFUSED` errors. All fetches go through `smartFetch()` which automatically waits for connection detection to complete before making requests.

### Store Sync
Both store copies must stay in sync:
- `webui/open-notebook-store.js` (served to browser)
- `extensions/webui/sidebar-end/open-notebook-store.js` (source)

After any change: `cp extensions/.../store.js webui/store.js`

### Alpine.js: x-show vs display:flex

`x-show` overrides `display: flex` with `display: block`. Use `:style` bindings for flex containers:

```html
<!-- BAD -->
<div x-show="condition" class="on-tab-pane--chat">

<!-- GOOD -->
<div class="on-tab-pane--chat"
     :style="condition ? 'display:flex' : 'display:none'">
```

### SSE vs JSON
- **Notebook chat** returns JSON
- **Source chat** returns SSE (Server-Sent Events)

Use `String.fromCharCode(10)` for newline splitting in SSE parsing.

### Podcast Profiles
- API expects profile **names** (e.g. `tech_discussion`), not IDs
- `solo_expert` speaker profile filtered (invalid TTS config)
- Profiles auto-selected on first available

## Stats

| Metric | Value |
|---|---|
| Plugin Files | 3 core (store, HTML, CSS) + SW |
| Store Lines | ~1,600 |
| SW Lines | ~390 |
| Store Methods | 30+ |
| API Endpoints | 25+ |
| CSS Classes | 60+ |
| Pre-cached Assets | ~25 |
| Connection Modes | 2 (direct, proxy) |
