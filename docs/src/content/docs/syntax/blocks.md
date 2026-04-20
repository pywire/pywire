---
title: Control Flow Blocks
description: Rendering logic using {$if}, {$for}, {$await}, {$try}, {$snippet}, {$render}, and {$head} blocks.
---

PyWire provides a structured block syntax to handle dynamic rendering logic directly in your HTML. These blocks allow you to condition, loop, wait, catch errors, and reuse markup fragments — without writing complex Python logic inside your elements.

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

## Snippets (`{$snippet}`)

---

Snippets define **reusable, named markup fragments**. They're first-class values — you can invoke them multiple times, pass them across components as props, or leave them as defaults for consumers to override.

### Syntax

```pywire
{$snippet name(param1, param2)}
    <!-- body with access to self, enclosing locals, and params -->
{/snippet}
```

Parameters are optional. Parameters-less form: `{$snippet name}`.

### Examples

**Simple inline reuse:**

```pywire
{$snippet chip(label)}
    <span class="chip">{label}</span>
{/snippet}

{$render chip("draft")}
{$render chip("pending")}
{$render chip("published")}
```

**Slot-style: let parents override a section with a fallback:**

```pywire
<!-- components/card.wire -->
<div class="card">
    <header>{$render header}Untitled{/render}</header>
    {$render children}
</div>
```

```pywire
<!-- parent usage -->
<Card>
    {$snippet header}Product Details{/snippet}
    <p>...</p>
</Card>
```

## Rendering Snippets (`{$render}`)

---

`{$render name(...)}` invokes a snippet. Two forms:

- **Self-closing:** `{$render header(user)}` — calls the snippet, errors if it isn't defined.
- **Paired:** `{$render header}<default/>{/render}` — the body is a fallback used when the snippet isn't supplied.

The protected `children` snippet holds whatever markup a parent wrote between the component's tags:

```pywire
<!-- components/button.wire -->
<button class="btn" {**attrs}>
    {$render children}
</button>
```

## Head Teleport (`{$head}`)

---

The `{$head}` block teleports its contents into the document `<head>`, regardless of where in the render tree it appears. Contributions from pages, layouts, and components all merge.

### Syntax

```pywire
{$head}
    <!-- any HTML; goes into the root page's <head> -->
{/head}
```

### Examples

**Per-page `<title>` and meta tags:**

```pywire
<!-- pages/post.wire -->
{$head}
    <title>{post.title} — My Blog</title>
    <meta name="description" content={post.excerpt}>
    <link rel="canonical" href={post.url}>
{/head}

<article>{post.body}</article>
```

### Merge rules

- **Title:** the last `<title>` contributed by the render tree wins. Earlier titles are stripped.
- **Everything else:** preserved in authored order. If a page contributes `<meta charset>` before `<title>`, the charset stays first.

This makes layouts hands-off — they don't need to know which pages want a particular meta tag.
