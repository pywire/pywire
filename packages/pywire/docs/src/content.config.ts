import { defineCollection, z } from 'astro:content'
import { docsLoader } from '@astrojs/starlight/loaders'
import { docsSchema } from '@astrojs/starlight/schema'

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        // Tutorial specific fields
        files: z.array(z.object({
          path: z.string(),
          initial: z.string(),
          solution: z.string().optional(),
          editable: z.boolean().default(true),
          deletable: z.boolean().default(false),
        })).optional(),
        behaviors: z.object({
          canAddFiles: z.record(z.literal(true)).optional(),
          canDeleteFiles: z.array(z.string()).optional(),
          restrictedPaths: z.array(z.string()).optional(),
        }).optional(),
        successCriteria: z.array(z.object({
          type: z.enum(['file_exists', 'file_contains', 'browser_route_text', 'browser_element', 'custom']),
          target: z.string().optional(),
          pattern: z.string().optional(),
          route: z.string().optional(),
          description: z.string().optional(),
        })).optional(),
        pagesDir: z.string().optional(),
        initialRoute: z.string().default('/'),
        hints: z.array(z.string()).optional(),
      }),
    }),
  }),
}
