import type { Plugin } from 'prettier'
import { parsePywire, splitPywireSections, SplitSections } from './parser.js'
import { printPywire } from './printer.js'
import { formatHtmlWithPrettier } from './utils/html-format.js'
import { initializeRuff } from './utils/ruff-formatter.js'

const plugin: Plugin = {
  languages: [
    {
      name: 'PyWire',
      parsers: ['pywire'],
      extensions: ['.wire'],
    },
  ],
  parsers: {
    pywire: {
      parse: (text: string) => parsePywire(text),
      preprocess: async (text: string, options) => {
        const ruffPromise = initializeRuff()
        const sections = splitPywireSections(text)
        const componentNames = extractComponentNames(sections)
        const formattedHtml = await formatHtmlWithPrettier(sections.html, options, componentNames)

        const parts: string[] = []

        // Directives
        if (sections.directives.trim().length > 0) {
          parts.push(sections.directives.trimEnd())
        }

        // Python fence
        if (sections.separator && sections.python.trim().length > 0) {
          if (parts.length > 0) {
            parts.push('')
          }
          parts.push('---')
          parts.push(sections.python.trimEnd())
          parts.push('---')
        }

        // HTML template
        if (formattedHtml.trim().length > 0) {
          if (parts.length > 0) {
            parts.push('')
          }
          parts.push(formattedHtml.trim())
        }

        await ruffPromise
        return parts.join('\n')
      },
      astFormat: 'pywire-ast',
      locStart: (node: { start?: number }) => node.start ?? 0,
      locEnd: (node: { end?: number }) => node.end ?? 0,
    },
  },
  printers: {
    'pywire-ast': {
      print: (path: { getValue: () => ReturnType<typeof parsePywire> }, options: unknown) =>
        printPywire(path, options as Parameters<typeof printPywire>[1]),
    },
  },
}

function extractComponentNames(sections: SplitSections): string[] {
  const names = new Set<string>()

  // Directives: !import Name from ... or !import { Name1, Name2 } from ...
  const importDirectiveRegex = /!import\s+({[^}]+}|[a-zA-Z_]\w*)/g
  let match
  while ((match = importDirectiveRegex.exec(sections.directives)) !== null) {
    const list = match[1]
    if (list.startsWith('{')) {
      const braceContent = list.slice(1, -1)
      braceContent.split(',').forEach((n) => {
        const name = n.trim().split(/\s+as\s+/).pop()?.trim()
        if (name && /^[a-zA-Z_]\w*$/.test(name)) {
          names.add(name)
        }
      })
    } else {
      names.add(list)
    }
  }

  // Python: from ... import Name, Name2 or from ... import (Name, Name2)
  // Handles multiline, parentheses, aliases, and multiple names.
  const pythonImportRegex =
    /(?:(?<!\w)import\s+([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*)*)|from\s+[\w.]+\s+import\s+(?:\(([\s\S]*?)\)|([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*(?:\s+as\s+[a-zA-Z_]\w*)?)*)))/g

  while ((match = pythonImportRegex.exec(sections.python)) !== null) {
    const importList = match[1] || match[2] || match[3]
    if (importList) {
      importList.split(',').forEach((n) => {
        const name = n.trim().split(/\s+as\s+/).pop()?.trim()
        if (name && /^[a-zA-Z_]\w*$/.test(name)) {
          names.add(name)
        }
      })
    }
  }

  // Backup heuristic: Any tag starting with an uppercase letter in the HTML
  // is likely a component and should be preserved.
  const uppercaseTagRegex = /<([A-Z]\w*)/g
  let tagMatch
  while ((tagMatch = uppercaseTagRegex.exec(sections.html)) !== null) {
    names.add(tagMatch[1])
  }

  return Array.from(names)
}

export default plugin
