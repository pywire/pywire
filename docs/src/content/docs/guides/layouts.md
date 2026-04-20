---
title: Layouts
description: Reusing UI structures with layouts.
---

Layouts allow you to wrap multiple pages in a consistent UI structure (like headers, footers, and sidebars). A layout is a regular `.wire` file that uses `{$render children}` to indicate where page content should be injected.

## Creating a Layout

```pywire
<!-- A basic app shell layout -->
---
year = 2026
---
<nav>
    <a href="/">Home</a>
    <a href="/about">About</a>
    <a href="/contact">Contact</a>
</nav>

<main>
    {$render children}
</main>

<footer>&copy; {year} My App</footer>

<style scoped>
    nav {
        display: flex;
        gap: 1rem;
        padding: 1rem;
        border-bottom: 1px solid #e2e8f0;
    }
    main { padding: 2rem; }
    footer { padding: 1rem; color: #94a3b8; }
</style>
```

Layouts are full `.wire` components — they can have Python blocks, reactive state, scoped styles, and event handlers just like any other component.

## Using Layouts

How you apply layouts depends on your routing strategy.

### Path-Based Routing (default)

Create a file named `__layout__.wire` in any directory inside your `pages/` folder. It automatically wraps all pages in that directory and its subdirectories.

```text
pages/
├── __layout__.wire        # Applies to ALL pages
├── index.wire
├── about.wire
└── dashboard/
    ├── __layout__.wire    # Applies to all dashboard pages
    ├── index.wire
    └── settings.wire
```

The root `__layout__.wire` wraps every page. The `dashboard/__layout__.wire` wraps only pages inside `dashboard/`, and is itself nested inside the root layout.

### Explicit Routing

When using explicit routing (`path_based_routing=False`), layouts are applied with the `!layout` directive. The layout file can have any name and live anywhere in your project.

```pywire
!path "/my-page"
!layout "layouts/app_shell.wire"

<h1>This page uses the app shell layout</h1>
```

## Nested Layouts

Layouts compose naturally. When a subdirectory has its own `__layout__.wire`, it nests inside the parent layout:

**`pages/__layout__.wire`** (outer):

```pywire
<div class="app">
    <header>My App</header>
    {$render children}
</div>
```

**`pages/dashboard/__layout__.wire`** (inner):

```pywire
<div class="dashboard">
    <aside>Dashboard Sidebar</aside>
    <div class="content">
        {$render children}
    </div>
</div>
```

Visiting `/dashboard/settings` renders: outer layout → inner layout → `settings.wire` content.

## Layouts with State

Layouts can hold reactive state that persists as users navigate between pages wrapped by that layout. This is useful for things like sidebar toggle state, notification counts, or theme preferences.

```pywire
<!-- pages/__layout__.wire -->
---
sidebar_open = wire(True)

def toggle_sidebar():
    sidebar_open.value = not sidebar_open
---
<div class="app-shell">
    <button @click={toggle_sidebar}>Toggle Sidebar</button>
    <aside $show={sidebar_open}>
        <nav>
            <a href="/">Home</a>
            <a href="/settings">Settings</a>
        </nav>
    </aside>
    <main>
        {$render children}
    </main>
</div>
```

## Layout with Context

Layouts are a natural place to provide context to all child pages using `!provide`:

```pywire
<!-- pages/__layout__.wire -->
!provide { 'THEME': theme }

---
theme = wire("light")
---
<div class={f"app theme-{theme}"}>
    {$render children}
</div>
```

Any page or component can then inject the theme with `!inject { theme: 'THEME' }`. See [Context & Injection](/docs/concepts/context) for details.

## Named Snippets and `{$head}`

`{$render children}` is shorthand for the implicit `children` prop every component receives. Layouts can also define or receive **named snippets** for slots like titles or sidebars.

**Page defines, layout renders:**

```pywire
<!-- pages/about.wire -->
!layout "layouts/app_shell.wire"

{$snippet title}About — My App{/snippet}

<h1>About</h1>
<p>Content goes here.</p>
```

```pywire
<!-- layouts/app_shell.wire -->
<title>{$render title}My App{/render}</title>
<main>
    {$render children}
</main>
```

The paired form `{$render title}...{/render}` uses the body as a fallback when the page doesn't provide that snippet.

**Teleporting into `<head>`:** Pages and components can contribute directly to the document `<head>` with `{$head}...{/head}`:

```pywire
<!-- pages/post.wire -->
{$head}
    <title>{post.title}</title>
    <meta name="description" content={post.excerpt}>
{/head}

<article>...</article>
```

Contributions from every level of the render tree merge into the root `<head>`. The last `<title>` wins; non-title content retains author order.
