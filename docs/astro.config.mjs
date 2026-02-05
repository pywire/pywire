// @ts-check
import { defineConfig } from 'astro/config'
import starlight from '@astrojs/starlight'
import react from '@astrojs/react'
import tailwind from '@astrojs/tailwind'
import fs from 'node:fs'

// https://astro.build/config
export default defineConfig({
  site: 'https://pywire.dev',
  base: '/docs',
  vite: {
    ssr: {
      noExternal: ['monaco-editor'],
    },
  },
  integrations: [
    tailwind({ applyBaseStyles: false }), // Don't override Starlight's base styles
    react(),
    starlight({
      title: 'pywire',
      customCss: ['./src/styles/custom.css'],
      components: {
        Head: './src/components/Head.astro',
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/pywire/pywire' },
        { icon: 'discord', label: 'Discord', href: 'https://discord.gg/pywire' },
      ],
      expressiveCode: {
        shiki: {
          langs: [
            {
              ...JSON.parse(fs.readFileSync('./public/grammars/pywire.tmLanguage.json', 'utf-8')),
              name: 'pywire'
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
          ],
        },
        {
          label: 'Tutorial',
          autogenerate: { directory: 'tutorial' },
        },
        {
          label: 'Core Concepts',
          items: [
            { label: 'The .wire File', slug: 'concepts/wire-file' },
            { label: 'Reactivity & State', slug: 'concepts/reactivity' },
            { label: 'Server-Side Events', slug: 'concepts/events' },
          ],
        },
        {
          label: 'Template Syntax',
          items: [
            { label: 'Interpolation & Attributes', slug: 'syntax/templating' },
            { label: 'Control Flow ($if, $for)', slug: 'syntax/control-flow' },
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
            { label: 'Tutorial Architecture', slug: 'guides/tutorial-architecture' },
          ],
        },
        {
          label: 'Ecosystem',
          items: [
            { label: 'Editor Setup', slug: 'guides/editor-setup' },
            { label: 'CLI Reference', slug: 'guides/cli' },
            { label: 'Deployment', slug: 'guides/deployment' },
            { label: 'Testing', slug: 'guides/testing' },
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
