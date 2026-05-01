---
title: Forms & Validation
description: Handling user input and validation cleanly.
---

PyWire provides a powerful, schema-less approach to form validation that leverages standard HTML attributes and Python logic.

## Basic Form Handling

Use the `@submit` event on a `<form>` to handle form submissions. The handler receives the form data as a dictionary.

```pywire
---
message = wire("")

def handle_submit(data):
    message.value = f"Welcome, {data['name']}!"
---
<form @submit.prevent={handle_submit}>
    <input name="name" type="text" placeholder="Your name" />
    <button type="submit">Submit</button>
</form>

<p $if={message}>{message}</p>
```

## Automatic Validation Schema

When you use the `@submit` event on a `<form>`, PyWire automatically scans the form's input fields (`required`, `min`, `max`, `pattern`, `type`, `minlength`, `maxlength`) and builds a validation schema on the server.

You don't need to define a Pydantic model manually (though you can). The HTML _is_ the schema.

```pywire
---
from pywire import ref
from pywire.components import Form
form_ref = ref()

def handle_submit(data):
    # data is a dictionary of the form inputs
    print("Form valid:", data)
---
<Form @submit={handle_submit} $ref={form_ref}>
    <div>
        <label>Username</label>
        <input name="username" required minlength="3">
        <span class="error" $if={form_ref.errors.username}>
            {form_ref.errors.username.message}
        </span>
    </div>

    <div>
        <label>Age</label>
        <input name="age" type="number" min="18">
        <span class="error" $if={form_ref.errors.age}>
            {form_ref.errors.age.message}
        </span>
    </div>

    <button type="submit">Register</button>
</Form>
```

### How it Works

1. **Extraction**: The compiler sees `@submit`. It parses all child `<input>` tags.
2. **Rules**: It sees `name="username" required`. It adds a rule: `username` must be present.
3. **Execution**: When the form submits, PyWire intercepts the event.
4. **Validation**: Before calling `handle_submit`, PyWire validates the incoming data against the extracted rules.
5. **Routing**:
   - **Valid**: Calls `handle_submit(data)`.
   - **Invalid**: Intercepted before calling `handle_submit` and populates `form_ref.errors`.

## Validation Attributes

The following HTML validation attributes are supported:

| Attribute         | Description                        |
| ----------------- | ---------------------------------- |
| `required`        | Field must have a value            |
| `minlength="N"`   | Minimum character count            |
| `maxlength="N"`   | Maximum character count            |
| `min="N"`         | Minimum numeric value              |
| `max="N"`         | Maximum numeric value              |
| `step="N"`        | Numeric step interval              |
| `pattern="regex"` | Value must match the regex pattern |
| `type="email"`    | Must be a valid email format       |
| `type="number"`   | Must be a valid number             |

## Displaying Errors

When validation fails, errors are available on the form ref's `errors` namespace. Each field's error has a `.message` property.

```pywire
<span class="error" $if={form_ref.errors.email}>
    {form_ref.errors.email.message}
</span>
```

## Reactive Validation Attributes

You can bind validation attributes dynamically.

```pywire
<!-- Field is required only if 'is_company' checkbox is checked -->
<input name="company_name" required={is_company} />
```

## Pydantic Model Integration

For complex validation, you can pass a Pydantic model to the `Form` component:

```pywire
---
from pywire import ref
from pywire.components import Form
from pydantic import BaseModel

class UserForm(BaseModel):
    name: str
    email: str
    age: int

form_ref = ref()

def on_submit(data):
    user = UserForm(**data)
    print(f"Valid user: {user.name}")
---
<Form model={UserForm} @submit={on_submit} $ref={form_ref}>
    <input name="name" />
    <input name="email" type="email" />
    <input name="age" type="number" />
    <button type="submit">Create User</button>
</Form>
```

When a Pydantic model is provided, validation rules are extracted from the model's field definitions in addition to the HTML attributes.
