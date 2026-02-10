---
title: Control Flow Blocks
description: Rendering logic using {$if}, {$for}, {$await}, and {$try} blocks.
---

PyWire provides a structured block syntax to handle dynamic rendering logic directly in your HTML. These blocks allow you to condition, loop, wait, and catch errors without writing complex Python logic inside your elements.

## Syntax Overview

---

All blocks follow a consistent pattern using the brace-dollar sigil `{$...}`.

- **Opener:**`{$keyword expression}` (e.g., `{$if user.is_admin}`)

- **Branches:**`{$keyword}` (e.g., `{$else}`)

- **Closer:**`{/keyword}` (e.g., `{/if}`)

## Conditionals (`{$if}`)

---

The `{$if}` block renders content based on the truthiness of a Python expression. It supports `elif` and `else` branches.

### Syntax

```pywire
{$if condition}
    <!-- Rendered if condition is Truthy -->
{$elif other_condition}
    <!-- Rendered if first condition is False and this is Truthy -->
{$else}
    <!-- Rendered if all above are False -->
{/if}
```

### Examples

**Basic Visibility:**

```pywire
{$if is_logged_in}
    <UserProfile user={user} />
{$else}
    <LoginButton />
{/if}
```

**Complex Logic:** You can use standard Python operators (`and`, `or`, `not`, `in`) inside the block.

```pywire
{$if user.role == "admin" and len(notifications) > 0}
    <AdminAlerts />
{/if}
```

## Loops (`{$for}`)

---

The `{$for}` block iterates over any Python iterable (list, tuple, dictionary, generator).

### Syntax

```pywire
{$for target in iterable, key=unique_id}
    <!-- Rendered for each item -->
{$else}
    <!-- Rendered if the iterable is empty -->
{/for}
```

### The `key` Argument

Providing a `key` is **strongly recommended**. It allows PyWire to track identity across re-renders, ensuring that state (like focus or input text) is preserved when the list order changes.

- **Syntax:**`key=<expression>` (comma separated from the loop).

### Examples

**List Iteration:**

```pywire
<ul>
    {$for todo in todos, key=todo.id}
        <li class={todo.status}>
            {todo.text}
        </li>
    {$else}
        <li>No todos yet!</li>
    {/for}
</ul>
```

**Dictionary Iteration:**

```pywire
<dl>
    {$for key, value in config.items(), key=key}
        <dt>{key}</dt>
        <dd>{value}</dd>
    {/for}
</dl>
```

## Async Data (`{$await}`)

---

The `{$await}` block handles Python **Awaitables** (coroutines, Tasks, Futures). It manages the three states of an async operation: **Pending**, **Resolved**, and **Rejected**.

### Syntax

```pywire
{$await awaitable_expression}
    <!-- 1. PENDING: Rendered immediately while waiting -->
{$then result_name}
    <!-- 2. RESOLVED: Rendered when the task finishes -->
{$catch error_name}
    <!-- 3. REJECTED: Rendered if an exception is raised -->
{/await}
```

### Examples

**Fetching Data:**

```pywire
{$await db.get_user(user_id)}
    <div class="skeleton">Loading profile...</div>

{$then user}
    <h1>{user.name}</h1>
    <p>{user.bio}</p>

{$catch e}
    <div class="error">
        Could not load user: {str(e)}
    </div>
{/await}
```

**Fire-and-Forget:** You can omit the variable names if you don't need the result value.

```pywire
{$await log_view_event()}
    <!-- No pending UI needed -->
{$then}
    <small>View logged.</small>
{/await}
```

## Error Boundaries (`{$try}`)

---

The `{$try}` block creates a safety zone. If an exception occurs while rendering the content inside (including inside child components), the `{$except}` block is rendered instead of crashing the page.

### Syntax

```pywire
{$try}
    <!-- Safe Zone -->
{$except ExceptionType as e}
    <!-- Error Handler -->
{$else}
    <!-- Optional: Runs if no error -->
{$finally}
    <!-- Optional: Runs always -->
{/try}
```

### Examples

**Unsafe User Content:** Useful when rendering content that might fail validation or parsing.

```pywire
{$try}
    {$html render_markdown(user_bio)}
{$except ValueError}
    <p class="warning">Invalid markdown formatting.</p>
{$except Exception}
    <p class="error">Unknown error rendering bio.</p>
{/try}
```
