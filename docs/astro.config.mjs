// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://pywire.dev',
	base: '/docs',
	integrations: [
		starlight({
			title: 'pywire',
			customCss: ['./src/styles/custom.css'],
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/pywire/pywire' },
				{ icon: 'discord', label: 'Discord', href: 'https://discord.gg/pywire' },
			],
			sidebar: [
				{
					label: 'Guides',
					items: [
						{ label: 'Getting Started', slug: 'guides/getting-started' },
						{ label: 'Walkthrough', slug: 'guides/walkthrough' },
					],
				},
				{
					label: 'Reference',
					autogenerate: { directory: 'reference' },
				},
				{
					label: 'Project',
					items: [
						{ label: 'Back to Website', link: 'https://pywire.dev', attrs: { target: '_self' } },
						{ label: 'Releases', link: 'https://github.com/pywire/pywire/releases' },
					],
				},
			],
		}),
	],
});
