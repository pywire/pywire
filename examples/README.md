# pywire examples

Small but complete apps. Each one is a uv workspace member with its own tests, and its README lists the features it uses and the things that surprised us while building it.

| Example | What it shows |
| --- | --- |
| [taskboard](taskboard) | FastAPI and pywire in one app: a JSON API and live pages over one service layer, SQLAlchemy, pywire-auth, forms and a wizard, uploads, shared state per board, a raw WebSocket for live cursors. Start here for a real app. |
| [realtime](realtime) | State shared between everyone on the server: a poll, presence, chat, a server clock, and what races look like and how to avoid them. |
| [edge-stateless](edge-stateless) | Stateless mode: the page state travels with the browser in a signed snapshot, so any worker (or a serverless function) can answer. |

```sh
uv sync --all-packages          # from the repo root
cd examples/taskboard && uv run pytest
examples/scripts/check           # format, lint, pywire check and tests for all of them
```

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
