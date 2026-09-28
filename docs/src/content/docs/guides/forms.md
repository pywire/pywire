---
title: Forms & Validation
description: Plain forms for raw form data, bound forms that take their rules from a Pydantic model, file uploads and multi-step wizards.
---

PyWire has two kinds of forms, and you pick per form:

- A **plain form** is ordinary HTML. `@submit` hands your handler the submitted fields and you do the rest.
- A **bound form** uses `$bind` to tie a `<form>` to a Pydantic model. The model writes the HTML attributes, the server validates every submit against the model, and your handler receives a validated model instance.

Both work with JavaScript on or off, and in every deployment mode. For a single input that just holds a value, such as a search box, [bind it to a wire](#binding-an-input-to-a-wire) instead.

## Plain forms

```pywire
---
message = wire("")

def handle_submit(data):
    message.value = f"Welcome, {data['name']}!"
---
<form @submit.prevent={handle_submit}>
    <input name="name" placeholder="Your name" />
    <button type="submit">Submit</button>
</form>

<p $if={message}>{message}</p>
```

The handler receives `FormEventData`, which reads like a dictionary of the submitted fields: `data["name"]`, `data.get("name")`, `"name" in data` and `dict(data)` all work. Repeated names (a group of checkboxes, a `<select multiple>`) hold lists. Nothing is validated for you.

## Binding an input to a wire

`$bind` on an `<input>`, `<select>` or `<textarea>` with a wire keeps the two in step: the element shows the wire's value, and editing the element writes the wire back.

```pywire
---
term = wire("")
limit = wire(10)
tags = wire([])

def results():
    return search(term.value, tags.value)[: limit.value]
---
<input type="search" $bind={term} placeholder="Search" />
<input type="number" $bind={limit} />
<label><input type="checkbox" value="docs" $bind={tags} /> Docs</label>
<label><input type="checkbox" value="blog" $bind={tags} /> Blog</label>

<ul>
    <li $for={item in results()}>{item.title}</li>
</ul>
```

The value is converted to the type the wire holds: a wire holding an `int` gets an `int`, a lone checkbox bound to a `bool` wire gets `True` or `False`, and checkboxes or a `<select multiple>` bound to a list wire get a list. Radios and a plain `<select>` set one value. Text boxes send after the user pauses typing ([the default `@input` debounce](/syntax/event-modifiers/#default-timing)); everything else sends on change.

Binding a wire needs no Pydantic, and nothing is validated. Use a bound form when the value has rules.

## Bound forms

Install the forms extra, which brings Pydantic v2:

```sh
pip install "pywire[forms]"
```

Define the model, create a form with `form(Model)`, and bind it:

```pywire
---
from pydantic import BaseModel, EmailStr, Field
from pywire import form

class Signup(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=50)
    age: int = Field(ge=13)

signup = form(Signup)
welcome = wire("")

async def create(data: Signup):
    welcome.value = f"Welcome, {data.name}!"
---
<form $bind={signup} @submit={create}>
    <label for={signup.email.html_id}>{signup.email.label}</label>
    <input $bind={signup.email} placeholder="you@example.com" />
    <p id={signup.email.error_id} $if={signup.email.error}>{signup.email.error}</p>

    <label for={signup.name.html_id}>{signup.name.label}</label>
    <input $bind={signup.name} />
    <p id={signup.name.error_id} $if={signup.name.error}>{signup.name.error}</p>

    <label for={signup.age.html_id}>{signup.age.label}</label>
    <input $bind={signup.age} />
    <p id={signup.age.error_id} $if={signup.age.error}>{signup.age.error}</p>

    <button type="submit">Sign up</button>
</form>

<p $if={welcome}>{welcome}</p>
```

The email input renders as:

```html
<input
  placeholder="you@example.com"
  name="email"
  id="signup-email"
  type="email"
  required
  value=""
/>
```

On submit, PyWire reads only the fields the model declares, validates them with `Signup.model_validate`, and then either calls `create` with the `Signup` instance or re-renders the form with what the user typed and an error on each failing field. An invalid field also gets `aria-invalid="true"` and `aria-describedby` pointing at its `error_id`.

`$bind` works on `<form>`, `<input>`, `<select>` and `<textarea>`. A plain `<form>` without `$bind` stays a plain form.

### The model is the contract

Attributes come from the model's JSON schema, so the browser checks the same rules the server enforces. Attributes you write by hand (`class`, `placeholder`, `autocomplete` and so on) are kept. A constraint written by hand that disagrees with the model (`minlength="5"` when the model says 2) is an error in debug mode and is overridden by the model in production, because the server would never enforce it.

| Model field                              | Rendered as                                                       |
| ---------------------------------------- | ----------------------------------------------------------------- |
| `str`, `Field(min_length=, max_length=)` | `type="text"`, `minlength`, `maxlength`                           |
| `Field(pattern=r"^...$")`                | `pattern` (only anchored patterns the browser reads the same)     |
| `EmailStr`, `HttpUrl`, `SecretStr`       | `type="email"`, `type="url"`, `type="password"`                   |
| `int`, `float`, `Decimal` with `ge`/`le` | `type="number"`, `min`, `max`, `step`                             |
| `date`, `datetime`, `time`               | `type="date"`, `type="datetime-local"`, `type="time"`             |
| `bool`                                   | a checkbox; `Literal[True]` is a box that must be ticked          |
| `Literal[...]` or an `Enum`              | a `<select>` or radios, with the options from the model           |
| `list[Literal[...]]`                     | checkboxes or a `<select multiple>`                               |
| `Upload`, `list[Upload]`                 | `type="file"` (and `multiple`); see [File uploads](#file-uploads) |
| No default, not `Optional`               | `required`                                                        |

Labels come from `Field(title=...)`, or the field name in sentence case (`first_name` becomes "First name"). `Field(description=...)` is available as `field.help`.

### Empty inputs

Browsers send an empty string for an empty box. A bound form reads it the way people mean it:

- A required field left empty is missing, so it fails with "This field is required".
- An `Optional` field left empty is `None`.
- A text field with a default keeps the empty string; any other field with a default gets its default.
- An unticked checkbox is `False`.

### Choices

A `Literal` or `Enum` field is a choice. Bind it on a `<select>` and leave the options out to have PyWire write them from the model, or write your own `<option>`s:

```pywire
<select $bind={signup.plan}></select>

<label><input type="radio" value="free" $bind={signup.plan} /> Free</label>
<label><input type="radio" value="pro" $bind={signup.plan} /> Pro</label>
```

Radios and checkboxes for a choice need a `value=` naming the option they stand for. A value the model doesn't allow is refused by the server whatever the HTML says.

### Errors and messages

Each field has `error` (the first message, or `None`) and `errors` (a list of `FieldError` with `code`, `message` and the Pydantic `type`). Codes follow the browser's `ValidityState` names: `valueMissing`, `tooShort`, `tooLong`, `rangeUnderflow`, `rangeOverflow`, `stepMismatch`, `patternMismatch`, `typeMismatch`, `badInput` and `customError`, plus `fileTooLarge`, `fileType` and `tooManyFiles` for [uploads](#file-uploads).

Messages are written for people ("Use at least 2 characters", "Must be 13 or more"). Override them by code, or by field and code:

```python
signup = form(
    Signup,
    messages={
        "valueMissing": "Please fill this in",
        "age.rangeUnderflow": "You must be at least {ge}",
    },
)
```

A `ValueError` raised in a `field_validator` becomes that field's message. An error from a `model_validator` is a form-level error on `signup.error`.

Messages that name a limit read it from the rule, so `{ge}` above becomes `13`. The placeholders are the constraint names: `min_length`, `max_length`, `ge`, `le`, `gt`, `lt` and `multiple_of`, and for files `max_size`, `accept` and `max_files`.

### Live validation

With JavaScript on, a bound form checks each field as the user goes, not only on submit:

- A text field is checked when the user leaves it. Once it shows an error, it is checked again as they type (after the usual pause), so the message clears as soon as the value is right.
- Checkboxes, radios and selects are checked when they change, and a file input once its file is uploaded.
- Only fields the user has been through show errors. A form-level error from a `model_validator` waits for a submit.

Each check runs the whole model on the server, so a rule that reads `context=` or compares two fields behaves exactly as it will on submit. Turn it off per form with `form(Model, validate="submit")`.

While a submit is in flight the form is marked `aria-busy="true"` and a second submit is ignored. When the answer comes back with errors, focus moves to the first invalid field. Without JavaScript, that field renders with `autofocus` instead.

Your handler can reject a valid submit too. Setting an error marks the form invalid and re-renders it:

```python
async def create(data: Signup):
    if await users.exists(data.email):
        signup.email.error = "That email is already registered"
        return
    await users.create(data)
```

### Rules that depend on server state

Pass `context=` (a mapping, or a callable that returns one) and read it in validators through `ValidationInfo.context`:

```python
class Booking(BaseModel):
    seats: int = Field(ge=1)

    @field_validator("seats")
    @classmethod
    def within(cls, v: int, info: ValidationInfo) -> int:
        if v > info.context["left"]:
            raise ValueError(f"Only {info.context['left']} seats left")
        return v

booking = form(Booking, context=lambda: {"left": seats_left()})
```

### Edit forms

Prefill from a model instance or a mapping, and go back to it with `reset()`:

```python
profile = form(Profile, initial=current_user.profile)

def on_load():
    profile.load(fetch_profile())  # replace the initial values
```

A field rendered `disabled` or `readonly` is owned by the server: on submit it keeps the value the server rendered, whatever the request says. A field marked `SkipJsonSchema` never renders and is never read from the request, which suits values like `owner_id` that only the server sets.

### Nested models and lists

Nested models use dotted names, and list rows use their index:

```pywire
<input $bind={order.address.street} />

<div $for={row in order.items}>
    <input $bind={row.name} />
    <input $bind={row.qty} />
</div>
```

These post as `address.street`, `items.0.name` and `items.0.qty`. The server stops reading rows past the model's `max_length` and reports the excess, so a client can't send a thousand of them.

To let people add and remove rows, spread `add_button` onto a button for the list and `remove_button` onto one in each row:

```pywire
<form $bind={order} @submit={create}>
    <fieldset $for={row in order.items}>
        <input $bind={row.name} />
        <input $bind={row.qty} />
        <button {**row.remove_button}>Remove</button>
    </fieldset>
    <button {**order.items.add_button}>Add item</button>
    <button type="submit">Place order</button>
</form>
```

Both are submit buttons with `formnovalidate`, so they work without JavaScript and never trip the browser's checks. They post what has been typed so far; the server adds an empty row, or removes that row and moves the rows after it (with their errors) up by one. Nothing is validated and the handler isn't called. Adding stops at the list's `max_length`.

### File uploads

Type a field as `Upload` (or `list[Upload]` for several files), and describe what it accepts with `UploadField`:

```pywire
---
from typing import Annotated
from pydantic import BaseModel
from pywire import form
from pywire.forms import Upload, UploadField
from pywire.storage import LocalStore

avatars = LocalStore("var/avatars")
documents = LocalStore("var/documents")

class Profile(BaseModel):
    name: str
    avatar: Annotated[Upload, UploadField(accept="image/*", max_size="2 MB")]
    papers: Annotated[
        list[Upload], UploadField(accept=".pdf", max_size="10 MB", max_files=5)
    ] = []

profile = form(Profile)

async def save(data: Profile):
    key = await data.avatar.save(avatars)  # a random key, e.g. "3f9c...a1.png"
    await set_avatar(data.name, key)
    for paper in data.papers:
        await paper.save(documents)
---
<form $bind={profile} @submit={save}>
    <input $bind={profile.name} />
    <input $bind={profile.avatar} />
    <progress data-pw-progress-for={profile.avatar.html_id} max="1" value="0"></progress>
    <p id={profile.avatar.error_id} $if={profile.avatar.error}>{profile.avatar.error}</p>
    <input $bind={profile.papers} />
    <p id={profile.papers.error_id} $if={profile.papers.error}>{profile.papers.error}</p>
    <button type="submit">Save</button>
</form>
```

`UploadField` renders `accept`, and the server checks every rule on the file it received:

| Option      | Meaning                                                                                | Error code     |
| ----------- | -------------------------------------------------------------------------------------- | -------------- |
| `accept`    | Types and extensions, as in HTML: `"image/*"`, `"image/png"`, `".pdf, .docx"`          | `fileType`     |
| `max_size`  | Bytes, or a string like `"500 KB"`, `"2 MB"` or `"1 MiB"` (KB is 1000 bytes, KiB 1024) | `fileTooLarge` |
| `max_files` | The most files a `list[Upload]` takes                                                  | `tooManyFiles` |

`accept` is checked against the declared content type and the filename, as the browser does. It says nothing about what the bytes really are, so check the content yourself before you trust it (for example, open an image with Pillow).

With JavaScript on, a file is uploaded as soon as it is picked, while the user fills in the rest. The browser checks `accept`, `max_size` and `max_files` first and shows the same message the server would. A `<progress data-pw-progress-for="...">` naming the input's id fills as the file goes up, and the input carries `data-pw-uploading` and `aria-busy` meanwhile so you can style it. Submitting waits for uploads still running. Without JavaScript, the files are posted with the form.

The handler receives each file as an `Upload`:

| Member                     | Description                                                                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `filename`, `content_type` | What the browser said. Treat both as hints.                                                                                                 |
| `extension`                | The filename's extension, lowercased (`".png"`), or `""`                                                                                    |
| `size`                     | Counted from the bytes the server received                                                                                                  |
| `await read()`             | The whole file as `bytes`                                                                                                                   |
| `stream()`                 | The file in chunks: `async for chunk in upload.stream()`                                                                                    |
| `await save(to, key=None)` | Copy it into a `FileStore` and return the key: a random one with the file's extension, unless you pass `key`. `to` can also be a file path. |

The browser's filename is never used as a key or path unless you pass it yourself. A file value can only come from an upload: a string posted under a file field's name is ignored. Files larger than `PyWire(max_upload_size=...)` (10 MB by default) are refused with a 413, whatever the model says.

### Where files are kept

Uploads wait in a staging area until a handler takes them, and expire after an hour. By default that is a folder in the system's temp directory. Every process that serves the app must see the same staging area, so with several workers, or in stateless mode behind a load balancer, give PyWire a shared store:

```python
from pywire import PyWire
from pywire.storage import ObjectStore

app = PyWire(upload_store=ObjectStore.from_url("s3://my-bucket/staging"))
```

`pywire.storage` has one interface, `FileStore`, and three stores:

- `LocalStore(root)` keeps files on disk under `root`.
- `MemoryStore()` keeps them in memory, for tests.
- `ObjectStore.from_url(url, **options)` talks to S3 and S3-compatible stores such as Cloudflare R2 (`s3://`), Google Cloud Storage (`gs://`) and Azure Blob Storage (`az://`). It is built on [obstore](https://developmentseed.org/obstore/), whose options (`region`, `endpoint`, credentials) it passes through; without them it reads the provider's usual environment variables. Install it with `pip install "pywire[storage]"`.

Every store has `await put(key, data)`, `await get(key)`, `stream(key)`, `await exists(key)`, `await delete(key)` and `await list(prefix)`. Keys are `/`-separated names like `"avatars/42.png"`. Swapping one store for another changes nothing else, so you can use `LocalStore` in development and `ObjectStore` in production for your own files too.

### Field names that clash with members

Form members (`value`, `valid`, `error`, `errors`, `dirty`, `submitted`, `fields`, `model`, `load`, `reset`, and the wizard's `step`, `steps`, `on_first_step`, `on_last_step`, `back_button`) and field members (`label`, `help`, `required`, `options`, `value`, `raw`, `error`, `errors`, `attrs`, `fields`, `html_name`, `html_id`, `error_id`, `add_button`, `remove_button`) win over model field names. Reach a field whose name clashes through `fields` or by subscript:

```pywire
<input $bind={product.fields.label} />
<input $bind={product["value"]} />
```

## Multi-step forms

`wizard(Model)` fills a model one step at a time. Each field of the model is a step, and each step is a model of its own:

```pywire
---
from pydantic import BaseModel, EmailStr, Field, SecretStr
from pywire import wizard

class Account(BaseModel):
    email: EmailStr

class About(BaseModel):
    name: str = Field(min_length=2)

class Finish(BaseModel):
    password: SecretStr = Field(min_length=12)

class Signup(BaseModel):
    account: Account
    about: About
    finish: Finish

signup = wizard(Signup)

async def create(data: Signup):
    await users.create(data)
    navigate("/welcome")
---
<form $bind={signup} @submit={create}>
    <ol>
        <li $for={step in signup.steps}>{step.label}</li>
    </ol>

    <input $if={signup.step == "account"} $bind={signup.account.email} />
    <input $if={signup.step == "about"} $bind={signup.about.name} />
    <input $if={signup.step == "finish"} $bind={signup.finish.password} />
    <p $for={message in signup.errors.values()}>{message}</p>
    <p $if={signup.error}>{signup.error}</p>

    <button $if={not signup.on_first_step} {**signup.back_button}>Back</button>
    <button type="submit">{"Create account" if signup.on_last_step else "Next"}</button>
</form>
```

Submitting a step validates that step only and moves to the next. The last step validates the whole model and calls the handler with it, so a `model_validator` that compares fields on different steps runs there; if a field on an earlier step fails, the wizard goes back to that step. `back_button` goes back a step without validating and keeps what was typed.

A wizard works with JavaScript off and in stateless mode. What earlier steps held travels with the form in a hidden input, signed so it can't be altered; processes that serve the same app must share `PyWire(secret_key=...)` to accept each other's forms. It is signed, not encrypted, so the browser can read it, and secret fields such as passwords are never carried: put them on the last step. Files picked on earlier steps travel as upload references and reach the handler as `Upload`s.

| Wizard member          | Description                                          |
| ---------------------- | ---------------------------------------------------- |
| `wizard.step`          | The current step: the name of its field on the model |
| `wizard.steps`         | Every step in order, as fields (`.label` names each) |
| `wizard.on_first_step` | `True` on the first step                             |
| `wizard.on_last_step`  | `True` on the last step                              |
| `wizard.back_button`   | Attributes for a button that goes back a step        |
| `wizard.reset()`       | Back to the first step and the initial values        |

Everything else works as on a form: `wizard.<step>.<field>`, `error`, `errors`, live validation (which only shows the current step's errors), `initial=` and `context=`.

## How submits work in each mode

A bound form always renders `method="post"` and a hidden field naming its submit handler, so the same form works everywhere:

| Mode                                              | What happens on submit                                                                                                           |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Interactive (WebSocket)                           | The client sends the fields as an event, with files already uploaded; errors or the handler's changes arrive as a normal update. |
| Non-interactive (`interactive_server_mode=False`) | The client posts the form with `fetch` and morphs the response in, so there is no "confirm resubmission" prompt.                 |
| Stateless                                         | The fields, errors and submit state travel in the signed snapshot like any other page state.                                     |
| No JavaScript, or `!no_interactive`               | The browser posts the form. An invalid submit returns the page with status 422; a handler that calls `navigate()` returns a 303. |

The values and errors come from the submitted fields themselves, so a no-JavaScript submit in stateless mode re-renders correctly even without a snapshot. Files take one path in every mode: they are staged in [the upload store](#where-files-are-kept) as they arrive, and the handler reads them from there.

## What the server enforces

- Only the generated submit handler can be reached from a request. Your handler is called with a validated model and is never directly dispatchable.
- Only fields in the model's schema are read. Extra fields, even on a model with `extra="allow"`, never reach it.
- Native form posts from another site are refused with a 403 (checked with `Sec-Fetch-Site` and `Origin`).
- Secrets (`SecretStr`, password inputs) are never echoed back into the page or kept in a snapshot.
- An upload reference only resolves to a file this app staged in the last hour. File sizes are counted on the server, and every `UploadField` rule is checked again after the upload.
- List fields are capped, and add and remove buttons only act on lists the model declares.
- Wizard state that doesn't carry this app's signature is ignored.

## Form reference

`form(Model, *, initial=None, context=None, messages=None, id=None, validate="blur")` returns a `Form[Model]`. `id` sets the DOM id prefix; it defaults to the form's variable name. `validate="submit"` turns off [live validation](#live-validation). `wizard(Model, ...)` takes the same options and returns a `Wizard[Model]`.

| Form member      | Description                                                     |
| ---------------- | --------------------------------------------------------------- |
| `form.<field>`   | The `BoundField` for a model field                              |
| `form.fields`    | All top-level fields, in model order; also `form.fields.<name>` |
| `form.value`     | The validated model after a valid submit, else `None`           |
| `form.valid`     | `True` when there are no errors                                 |
| `form.submitted` | `True` once the form has been submitted                         |
| `form.dirty`     | `True` when the submitted values differ from the initial ones   |
| `form.error`     | The form-level error; settable                                  |
| `form.errors`    | Every field error as `{dotted path: message}`                   |
| `form.load(obj)` | Replace the initial values and reset                            |
| `form.reset()`   | Back to the initial values, with no errors                      |

| Field member          | Description                                                   |
| --------------------- | ------------------------------------------------------------- |
| `field.value`         | The value as the model's type when it parses, else `None`     |
| `field.raw`           | What the user typed, as the browser sent it                   |
| `field.error`         | The first error message, or `None`; settable                  |
| `field.errors`        | The list of `FieldError`s                                     |
| `field.label`         | From `Field(title=)` or the field name                        |
| `field.help`          | From `Field(description=)`                                    |
| `field.required`      | Whether the field must be filled in                           |
| `field.options`       | The choices of a `Literal` or `Enum` field (`value`, `label`) |
| `field.html_name`     | The posted name, like `address.street`                        |
| `field.html_id`       | The DOM id, like `signup-address-street`                      |
| `field.error_id`      | The id to give the error message element                      |
| `field.attrs`         | The generated attributes, e.g. to spread onto a component     |
| `field.fields`        | The sub-fields of a nested model                              |
| `field.add_button`    | For a list field: attributes for a button that adds a row     |
| `field.remove_button` | For a list row: attributes for a button that removes it       |

## Editor support

The language server checks field paths against the model. `signup.emial` is reported as an unknown attribute of `Signup`, and `signup.age.value` is typed `int | None`.
