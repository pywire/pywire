// @ts-check
import { defineConfig } from 'astro/config'
import starlight from '@astrojs/starlight'
import react from '@astrojs/react'
import tailwind from '@astrojs/tailwind'
import favicons from 'astro-favicons'
import starlightLlmsTxt from 'starlight-llms-txt'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))

// https://astro.build/config
export default defineConfig({
  site: 'https://pywire.dev/',
  base: '/docs',
  vite: {
    ssr: {
      noExternal: ['monaco-editor'],
    },
    optimizeDeps: {
      include: ['react', 'react-dom', 'react-dom/client'],
    },
  },
  integrations: [
    tailwind({ applyBaseStyles: false }), // Don't override Starlight's base styles
    react(),
    favicons({
      name: 'PyWire Docs',
      short_name: 'PyWire',
      themes: ['#1e1e2e', '#eff1f5'],
      output: { assetsPrefix: '/docs/' }, // match site base
    }),
    starlight({
      title: 'pywire',
      customCss: ['./src/styles/custom.css'],
      plugins: [starlightLlmsTxt()],
      editLink: {
        baseUrl: 'https://github.com/pywire/pywire/edit/main/docs/',
      },
      components: {
        Head: resolve(__dirname, './src/components/Head.astro'),
        SiteTitle: resolve(__dirname, './src/components/SiteTitle.astro'),
        SocialIcons: resolve(__dirname, './src/components/SocialIcons.astro'),
        ThemeSelect: resolve(__dirname, './src/components/ThemeSelect.astro'),
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/pywire/pywire' },
        { icon: 'discord', label: 'Discord', href: '#' },
      ],
      expressiveCode: {
        themes: ['catppuccin-latte', 'catppuccin-mocha'],
        // Keep official Catppuccin token colors verbatim (matches Monaco
        // editor in the interactive tutorial). EC's default 5.5 auto-bumps
        // low-contrast tokens which mutates the theme.
        minSyntaxHighlightingColorContrast: 0,
        styleOverrides: {
          borderRadius: '12px',
          codeFontFamily:
            'JetBrains Mono, Fira Code, ui-monospace, SFMono-Regular, Menlo, monospace',
          codeFontSize: '0.85rem',
          frames: {
            // Box-shadow handled per-mode in custom.css; cancel EC default.
            frameBoxShadowCssValue: 'none',
          },
        },
        shiki: {
          langs: [
            {
              ...JSON.parse(fs.readFileSync('./public/grammars/pywire.tmLanguage.json', 'utf-8')),
              name: 'pywire',
            },
          ],
        },
      },
      sidebar: [
        {
          label: 'Start Here',
          items: [
            { label: 'Quickstart', slug: 'guides/quickstart' },
            { label: 'Introduction', slug: 'guides/introduction' },
            { label: 'Your First Component', slug: 'guides/your-first-component' },
            { label: 'Interactive Tutorial', link: 'tutorial/' },
            { label: 'Changelog', slug: 'changelog' },
          ],
        },
        {
          label: 'Core Concepts',
          items: [
            { label: 'The .wire File', slug: 'concepts/wire-file' },
            { label: 'Reactivity & State', slug: 'concepts/reactivity' },
            { label: 'Server-Side Events', slug: 'concepts/events' },
            { label: 'Components', slug: 'concepts/components' },
            { label: 'Producers', slug: 'concepts/producer' },
          ],
        },
        {
          label: 'Template Syntax',
          items: [
            { label: 'Interpolation & Attributes', slug: 'syntax/templating' },
            { label: 'Control Flow ($if, $for)', slug: 'syntax/control-flow' },
            { label: 'Control Flow Blocks', slug: 'syntax/blocks' },
            { label: 'Event Modifiers', slug: 'syntax/event-modifiers' },
          ],
        },
        {
          label: 'Architecture',
          items: [
            { label: 'App Initialization', slug: 'guides/app-initialization' },
            { label: 'Routing', slug: 'guides/routing' },
            { label: 'Layouts', slug: 'guides/layouts' },
            { label: 'Forms & Validation', slug: 'guides/forms' },
            { label: 'Middleware', slug: 'guides/middleware' },
            { label: 'Framework Integration', slug: 'guides/framework-integration' },
          ],
        },
        {
          label: 'Authentication',
          items: [
            { label: 'Overview', slug: 'guides/authentication' },
            { label: 'OIDC Providers', slug: 'guides/authentication/providers' },
            { label: 'Local IdP & Persistence', slug: 'guides/authentication/local-idp' },
            { label: 'Live Auth Updates', slug: 'guides/authentication/live-auth' },
          ],
        },
        {
          label: 'Ecosystem',
          items: [
            { label: 'Editor Setup', slug: 'guides/editor-setup' },
            { label: 'CLI Reference', slug: 'guides/cli' },
            { label: 'Deployment', slug: 'guides/deployment' },
            { label: 'Horizontal Scaling', slug: 'guides/scaling' },
          ],
        },
        {
          label: 'Reference',
          autogenerate: { directory: 'reference' },
        },
      ],
    }),
  ],
})
