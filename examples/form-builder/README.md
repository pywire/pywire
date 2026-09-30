# Form builder

Describe a form in a sentence and get a working one. Two kinds of AI do different jobs:

- **OpenRouter** runs a chat model that writes: the title, and each field's name, label, help text and options. It tries a list of models in order: a free stealth model, two free open models, then DeepSeek V4 Flash as a cheap paid fallback.
- **Jev**, TypeSafe's System One API, decides: it takes state plus typed questions and returns probabilities instead of text. It checks the request and picks each field's type and whether it's required.

pywire turns the result into a real bound form. You can fill it in and send it, and the server validates it against a Pydantic model built for that form.

```sh
cd examples/form-builder
cp .env.example .env       # add OPENROUTER_API_KEY, TYPESAFE_API_KEY, PYWIRE_SECRET_KEY
uv run pywire dev
uv run pytest              # fake OpenRouter and Jev, both modes
```

It runs stateless by default, so it deploys to Cloudflare Python Workers. `STATELESS=0` runs the same page over a WebSocket.

## Files

| File | What it shows |
| --- | --- |
| `src/formbuilder/spec.py` | The form spec, the whitelist of field kinds, caps and cleanup, and building the Pydantic model with `create_model` |
| `src/formbuilder/ai.py` | Small httpx clients for OpenRouter (JSON schema output, model fallbacks) and Jev (typed questions) |
| `src/formbuilder/pipeline.py` | The run as a step machine: one model call per step |
| `src/formbuilder/limits.py` | Per-visitor and per-IP rate limits, and the visitor cookie middleware |
| `src/pages/index.wire` | `@poll` driving the steps, a `@derived` bound form built from the spec, `{$for}` over `form.fields` |
| `tests/` | Every page test runs twice: stateless POSTs with a signed snapshot, and a live WebSocket session |

## How a build runs

1. **Check the request** (Jev): is it a form request, would it ask for secrets, is it abusive?
2. **Write the fields** (OpenRouter): JSON that must match a strict schema.
3. **Decide each field's type** (Jev): a choice between eleven kinds (short text, email, date, pick one, and so on) and a yes/no on required, for every field, in one call. Each answer carries a confidence, and the page marks the ones under 60%.
4. **Validate the form** (code): cap everything, refuse sensitive fields, and send choice fields without options back for one **Write missing options** step (gpt-oss-20b). Anything still without options becomes short text.

The run is plain data in a wire. The steps list has an `@poll` element that calls `step()` every 150 ms while the run has work left; each call does one step and returns. In stateless mode that means every request finishes after one model call, and any isolate can take the next step because the run travels in the signed snapshot. When the run finishes, the polled element is no longer rendered and the polling stops.

## Why this is safe to put on the internet

- **The model picks from a menu.** A field's type is one of the kinds in `spec.KINDS`, each mapped to a fixed Pydantic type. Model output is never run as code, and there's no free-form regex: phone numbers use one fixed pattern.
- **Everything is capped.** At most 12 fields and 12 options each, with length limits on every string. Field names are slugged and kept off Python keywords and model attributes.
- **No phishing kits.** Jev's check and a list in code both refuse forms that ask for passwords, card or bank details, or ID numbers.
- **Nothing is stored.** A sent form is validated and shown back to you.
- **The keys can't be drained.** Each build, refine or sample fill costs one unit from a per-visitor bucket (cookie) and a per-IP bucket. When OpenRouter or Jev say the usage is used up, or refuse the key, visitors see one message: the demo's author is out of usage for now, try again later.

## Things to know

- **A form built at runtime works like any other.** `form(create_model(...))` in a `@derived` gets rebuilt when the spec wire changes. The model needs a fixed name, because pywire signs a form's posted state with it.
- **In stateless mode a derived form isn't in the snapshot.** Each submit and each live check posts every field, so values and errors come back correctly. What's lost between requests is which fields you've already left, so a live check shows errors for the field you just left, not the earlier ones.
- **`MemoryLimiter` is per process.** On Cloudflare each isolate has its own memory, so a deploy there needs a limiter backed by a Durable Object or KV with the same `take()` method.
- **Set `CLIENT_IP_HEADER` only behind a proxy you trust.** Otherwise anyone can send the header and pick their own IP bucket.
- **OpenRouter's free models** allow 20 requests a minute, and 50 a day per account (1,000 once the account has bought $10 of credits). When a free model is limited or retired, the request moves on to the next model in `WRITER_MODELS`. A build makes at most two OpenRouter calls and two Jev calls. Free models only answer if the account allows free endpoints that may train on inputs.
