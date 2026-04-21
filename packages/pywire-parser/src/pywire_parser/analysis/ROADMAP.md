# PyWire analysis — roadmap

This engine is intentionally scoped small for its first iteration. v1 ships
three real rules plus stubs — the goal is to land the infrastructure in the
right place and prove one concrete detection per rule category.

## v1 (landed)

| Code  | Severity | What it catches                                                |
|-------|----------|----------------------------------------------------------------|
| PW001 | warning  | `wire()` assigned a non-serializable literal / known class    |
| PW002 | error    | wire write inside a `derived()` body                           |
| PW003 | info     | redundant `.value` in template interpolation (`{x.value}`)     |

## Stubbed (registered, NotImplementedError in check)

| Code  | Planned rule                                                           |
|-------|------------------------------------------------------------------------|
| PW004 | subscripting a `WirePrimitive` (must use `.value[...]`)                |
| PW005 | `wire_list + other` — returns a plain list, loses reactivity          |
| PW006 | store interpolated into template without `.value`                      |
| PW007 | `derived += x` — `Derived` has no `__iadd__`                           |
| PW008 | calling a `Derived` — no `__call__`                                    |
| PW009 | `effect(...)` result discarded — cannot dispose                        |
| PW010 | `ref.value` / `ref.data` accessed on unbound `HTMLElement`             |

## Future iterations

### Type-flow analysis

Most real-world footguns — especially `wire(None)` later reassigned to a
class instance — need dataflow to catch. Options:

1. **Hand-rolled narrow type tracker** — walk the AST recording per-name
   types through simple assignments, handler calls, and return values.
   Fast, limited to module-local flow.
2. **Integrate `ty`** — once `ty` exposes a stable programmatic API, use it
   to resolve types of wire targets. Deferred until upstream stabilises.
3. **Pyright / pyright-python** — external process; heavy, but mature.

Leaning toward option 1 for medium-term coverage, option 2 once viable.

### Cross-file rules

Today rules run per-file. A project-wide pass would enable:

- Detecting page imports of non-page-safe modules (Redis clients etc.)
- Layout / error-page presence checks (the v1 `validate_project` logic)
- Unused wire / derived declarations across a router

### LSP integration

`pywire-language-server` will consume `analyze(parsed, path)` and map each
`Diagnostic` to `lsp.Diagnostic`, wiring codes through `code` /
`codeDescription` so VS Code can link to rule docs.

### Runtime alignment

`pywire.runtime.session_serializer._is_serializable` already emits a
runtime warning on non-serializable wire values. Align the text to quote
the rule code (`PW001`) so users see the same identifier in both places.

### `--fix` support

`Diagnostic.fix` is a free-form hint today. Add a `Fix` dataclass with
`(edit_range, replacement_text)` so `pywire check --fix` and LSP code
actions share the same representation. Rules that know the canonical
rewrite (PW003 is a good candidate — drop `.value`) can produce fixes
first.
