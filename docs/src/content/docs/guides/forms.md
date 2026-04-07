---
title: Forms & Validation
description: Handling user input and validation cleanly.
---

PyWire provides a powerful, schema-less approach to form validation that leverages standard HTML attributes and Python logic.

## Automatic Validation Schema

When you use the `@submit` event on a `<form>`, PyWire automatically scans the form's input fields (`required`, `min`, `max`, `pattern`, `type`) and builds a validation schema on the server.

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

## Reactive Validation Attributes

You can bind validation attributes dynamically.

```html
<!-- Field is required only if 'is_company' checkbox is checked -->
<input name="company_name" required="{is_company.value}" />
```
