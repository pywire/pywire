---
title: Forms & Validation
description: Plain forms for raw form data, and bound forms that take their rules from a Pydantic model.
---

PyWire has two kinds of forms, and you pick per form:

- A **plain form** is ordinary HTML. `@submit` hands your handler the submitted fields and you do the rest.
- A **bound form** uses `$bind` to tie a `<form>` to a Pydantic model. The model writes the HTML attributes, the server validates every submit against the model, and your handler receives a validated model instance.

Both work with JavaScript on or off, and in every deployment mode.

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

| Model field                              | Rendered as                                                   |
| ---------------------------------------- | ------------------------------------------------------------- |
| `str`, `Field(min_length=, max_length=)` | `type="text"`, `minlength`, `maxlength`                       |
| `Field(pattern=r"^...$")`                | `pattern` (only anchored patterns the browser reads the same) |
| `EmailStr`, `HttpUrl`, `SecretStr`       | `type="email"`, `type="url"`, `type="password"`               |
| `int`, `float`, `Decimal` with `ge`/`le` | `type="number"`, `min`, `max`, `step`                         |
| `date`, `datetime`, `time`               | `type="date"`, `type="datetime-local"`, `type="time"`         |
| `bool`                                   | a checkbox; `Literal[True]` is a box that must be ticked      |
| `Literal[...]` or an `Enum`              | a `<select>` or radios, with the options from the model       |
| `list[Literal[...]]`                     | checkboxes or a `<select multiple>`                           |
| `FileUpload`, `list[FileUpload]`         | `type="file"` (and `multiple`); the form becomes multipart    |
| No default, not `Optional`               | `required`                                                    |

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

Each field has `error` (the first message, or `None`) and `errors` (a list of `FieldError` with `code`, `message` and the Pydantic `type`). Codes follow the browser's `ValidityState` names: `valueMissing`, `tooShort`, `tooLong`, `rangeUnderflow`, `rangeOverflow`, `stepMismatch`, `patternMismatch`, `typeMismatch`, `badInput` and `customError`.

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

A submit only reads the fields the page rendered with `$bind`. A field the page has not rendered, because the template leaves it out or an `$if` around it has stayed false, keeps its initial value (or the model default), whatever the request says. So an edit form can leave `id`, `owner_id` or `role` out of the template, and the handler still gets them from `initial`. A field rendered `disabled` or `readonly` is owned by the server the same way: on submit it keeps the value the server rendered.

### Nested models and lists

Nested models use dotted names, and list rows use their index:

```pywire
<input $bind={order.address.street} />

<div $for={row in order.items}>
    <input $bind={row.name} />
    <input $bind={row.qty} />
</div>
```

These post as `address.street`, `items.0.name` and `items.0.qty`. Only the rows the page rendered are read, so a client can't add rows by posting them, and the server reports rows past the model's `max_length`. Adding and removing rows from the page arrives in a later release.

### File fields

A `FileUpload` field turns the form into a multipart form. The handler gets the file's name, content type, size and bytes:

```python
from pywire.forms import FileUpload

class Avatar(BaseModel):
    image: FileUpload
    caption: str = ""
```

`size` is counted from the bytes the server received. Files larger than `PyWire(max_upload_size=...)` (10 MB by default) are refused with a 413. A file value can only come from an actual upload: a string posted under a file field's name is ignored.

### Field names that clash with members

Form members (`value`, `valid`, `error`, `errors`, `dirty`, `submitted`, `fields`, `model`, `load`, `reset`) and field members (`label`, `help`, `required`, `options`, `value`, `raw`, `error`, `errors`, `attrs`, `fields`, `html_name`, `html_id`, `error_id`) win over model field names. Reach a field whose name clashes through `fields` or by subscript:

```pywire
<input $bind={product.fields.label} />
<input $bind={product["value"]} />
```

## How submits work in each mode

A bound form always renders `method="post"` and a hidden field naming its submit handler, so the same form works everywhere:

| Mode                                              | What happens on submit                                                                                                           |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Interactive (WebSocket)                           | The client sends the fields as an event; errors or the handler's changes arrive as a normal update.                              |
| Non-interactive (`interactive_server_mode=False`) | The client posts the form with `fetch` and morphs the response in, so there is no "confirm resubmission" prompt.                 |
| Stateless                                         | The fields, errors and submit state travel in the signed snapshot like any other page state.                                     |
| No JavaScript, or `!no_interactive`               | The browser posts the form. An invalid submit returns the page with status 422; a handler that calls `navigate()` returns a 303. |

The values and errors come from the submitted fields themselves, so a no-JavaScript submit in stateless mode re-renders correctly even without a snapshot.

In non-interactive mode the session keeps page state, forms included, for the last page served only. Leaving `/signup` for another page and coming back starts the form fresh.

## What the server enforces

- Only the generated submit handler can be reached from a request. Your handler is called with a validated model and is never directly dispatchable.
- Only fields the page rendered with `$bind` are read. Other model fields keep their initial or default value, and names outside the model never reach it, even on a model with `extra="allow"`.
- Native form posts from another site are refused with a 403 (checked with `Sec-Fetch-Site` and `Origin`). A post runs the page's `@before_load` hooks and auth checks first, exactly like a GET, and nothing is dispatched if they stop the page.
- Secrets (`SecretStr`, password inputs) are never echoed back into the page or kept in a snapshot.
- Upload ids are checked, file sizes are counted on the server, and list fields are capped. A native post's body is limited to 1 MB of fields plus 10 files of `max_upload_size` each, counted as it arrives.

## Form reference

`form(Model, *, initial=None, context=None, messages=None, id=None)` returns a `Form[Model]`. `id` sets the DOM id prefix; it defaults to the form's variable name.

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

| Field member      | Description                                                   |
| ----------------- | ------------------------------------------------------------- |
| `field.value`     | The value as the model's type when it parses, else `None`     |
| `field.raw`       | What the user typed, as the browser sent it                   |
| `field.error`     | The first error message, or `None`; settable                  |
| `field.errors`    | The list of `FieldError`s                                     |
| `field.label`     | From `Field(title=)` or the field name                        |
| `field.help`      | From `Field(description=)`                                    |
| `field.required`  | Whether the field must be filled in                           |
| `field.options`   | The choices of a `Literal` or `Enum` field (`value`, `label`) |
| `field.html_name` | The posted name, like `address.street`                        |
| `field.html_id`   | The DOM id, like `signup-address-street`                      |
| `field.error_id`  | The id to give the error message element                      |
| `field.attrs`     | The generated attributes, e.g. to spread onto a component     |
| `field.fields`    | The sub-fields of a nested model                              |

## Editor support

The language server checks field paths against the model. `signup.emial` is reported as an unknown attribute of `Signup`, and `signup.age.value` is typed `int | None`.
