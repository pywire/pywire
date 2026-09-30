# pywire examples

Small but complete apps. Each one is a uv workspace member with its own tests, and its README lists the features it uses and the things that surprised us while building it.

| Example | What it shows |
| --- | --- |
| [taskboard](taskboard) | FastAPI and pywire in one app: a JSON API and live pages over one service layer, SQLAlchemy, pywire-auth, forms and a wizard, uploads, shared state per board, a raw WebSocket for live cursors. Start here for a real app. |
| [realtime](realtime) | State shared between everyone on the server: a poll, presence, chat, a server clock, and what races look like and how to avoid them. |
| [form-builder](form-builder) | AI in a real app: an open model writes a form, Jev decides its field types, and pywire builds a Pydantic model and a live form from it at runtime. Stateless by default, with `@poll` progress, rate limits and a safe whitelist of field types. |
| [edge-stateless](edge-stateless) | Stateless mode: the page state travels with the browser in a signed snapshot, so any worker (or a serverless function) can answer. |

```sh
uv sync --all-packages          # from the repo root
cd examples/taskboard && uv run pytest
examples/scripts/check           # format, lint, pywire check and tests for all of them
```

## demo.pywire.dev

The stateless examples run at demo.pywire.dev/<name>, with a landing page from [demo-site](demo-site). The [Deploy Examples](../.github/workflows/deploy-examples.yml) workflow redeploys them from `main` whenever an example or pywire itself changes, so the demos always run the latest code. Each deployed example has its own `wrangler.toml` for its code and vars. The Workers themselves, their routes and DNS are in pywire/pywire.dev's Terraform. To run one in Cloudflare's local runtime:

```sh
cd examples/form-builder
PYWIRE_SECRET_KEY=... PYWIRE_BASE_PATH=/form-builder uv run pywire build --platform cloudflare-edge
UV_NO_EDITABLE=1 uv run --with workers-py pywrangler dev   # secrets from .dev.vars
```

Secrets are set once per Worker, after Terraform has created it, and never by the workflow:

```sh
npx wrangler secret put PYWIRE_SECRET_KEY --name pywire-demo-edge-stateless
npx wrangler secret put PYWIRE_SECRET_KEY --name pywire-demo-form-builder
npx wrangler secret put PYWIRE_SECRET_KEY --name pywire-demo-realtime
npx wrangler secret put OPENROUTER_API_KEY --name pywire-demo-form-builder
npx wrangler secret put TYPESAFE_API_KEY --name pywire-demo-form-builder
```

realtime runs on one Cloudflare Durable Object for every visitor (`PYWIRE_PLACEMENT = "global"`), so everyone shares the poll and the chat. taskboard needs a database, so it isn't on the demo site yet.

For the practices these examples follow, see [Building real apps](https://pywire.dev/docs/guides/best-practices/).

<!-- SUPPORT_MESSAGE_TEMPLATE_START -->
## ❤️ Support pywire

If pywire is helping you build, consider supporting the project. Donations cover documentation hosting, CI/CD runners, and the caffeine required for development.

[![GitHub Sponsor](https://img.shields.io/badge/Sponsor-pywire-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/pywire)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-reecelikesramen-ff5e5b?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/reecelikesramen)

### Why sponsor?
* 🚀 Faster development of the core framework.
* 📖 Better docs and community examples.
* 🔧 Integration research.
<!-- SUPPORT_MESSAGE_TEMPLATE_END -->
