export interface ChangeLogEntry {
  version: string
  date: string
  title?: string
  description?: string
  features?: string[]
  fixes?: string[]
  improvements?: string[]
}

export const changelogData: ChangeLogEntry[] = [
  {
    version: '0.1.9',
    date: '2026-02-08',
    title: 'Stability & Developer Experience',
    description:
      'A focused update improving the development server, expanding directive support, and fixing cross-platform issues.',
    features: [
      "Introduced the `$permanent` directive (alias for `data-pywire-permanent`). Elements marked with this tag are preserved during Morphdom updates, making them ideal for integrating third-party libraries (maps, video players) that shouldn't be re-initialized on every server roundtrip.",
      'Added the `$reload` directive. Links decorated with this attribute will bypass the Single Page Application (SPA) routing and force a full browser page reload, useful for auth resets or escaping the app shell.',
      'Smart port selection: The development server now automatically hunts for an available port if the default is occupied, preventing startup failures when running multiple instances.',
    ],
    fixes: [
      'Resolved encoding issues with rendering rocket emojis in the CLI TUI on Windows terminals.',
      'Fixed `sdist` generation on Windows 11 to ensure consistent package distribution across all platforms.',
    ],
  },
  {
    version: '0.1.8',
    date: '2026-01-20',
    title: 'Reactivity & Syntax Refinements',
    description: 'Major improvements to the template syntax and rendering engine efficiency.',
    features: [
      'Introduced dedicated control flow blocks: `<$if>`, `<$show>`, and `<$for>`. These provide a cleaner, tag-based alternative to attribute-based directives for handling template logic.',
      'Added support for attribute shorthand syntax. You can now write `<div {class}>` instead of `<div class={class}>`, reducing boilerplate when variable names match attribute names.',
    ],
    improvements: [
      'Overhauled the update strategy to strictly perform partial DOM updates. The framework no longer tracks or attempts to update non-reactive variables after the initial server-side render, significantly reducing overhead.',
    ],
  },
]
