# User Management Plugin for Agent Zero

Multi-user authentication, chat isolation, and token usage tracking with PostgreSQL.

## Features

- **PostgreSQL Database** — Store users, sessions, and token usage
- **Multi-user Auth** — Replace single login with per-user accounts
- **Chat Isolation** — Tag each context with `user_id`, filter in UI
- **Token Tracker** — Hook into LLM calls, log input/output tokens per user
- **Admin Panel** — WebUI modal to view usage stats + export
- **Session Manager** — Track active sessions per user with expiry
- **API Key Store** — Generate & store per-user API keys in PostgreSQL for automation
- **API Auth Middleware** — Validate incoming API key, resolve to user_id
- **POST /api/chat Endpoint** — Accept external messages via API key for automations
- **Rate Limiter** — Throttle API requests per key to prevent abuse

## Installation

Install via the Agent Zero Plugin Hub, or clone into your `usr/plugins/` directory:

```bash
git clone https://github.com/kgobakis/a0-user-management.git usr/plugins/user_management
```

## Configuration

Configure PostgreSQL connection and user settings in the Agent Zero settings panel under **External** settings.

## License

MIT
