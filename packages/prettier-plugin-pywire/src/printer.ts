import type { HeaderNode, ParsedDocument } from './parser.js'
import { loadRuffConfig, resolveRuffFormatOptions } from './utils/ruff-config.js'
import { formatPython } from './utils/ruff-formatter.js'

type PrettierOptions = {
  filepath?: string
  printWidth?: number
  tabWidth?: number
  useTabs?: boolean
  singleQuote?: boolean
  endOfLine?: 'lf' | 'crlf' | 'cr'
  plugins?: unknown[]
}

export function printPywire(
  path: { getValue: () => ParsedDocument },
  options: PrettierOptions
): string {
  const document = path.getValue()

  const directiveNodes = document.headerNodes.filter((n) => n.type === 'Directive')
  const pythonNodes = document.headerNodes.filter((n) => n.type === 'Python')

  const parts: string[] = []

  // Directives section
  if (directiveNodes.length > 0) {
    const formattedDirectives = formatDirectives(directiveNodes, options)
    parts.push(formattedDirectives.trimEnd())
  }

  // Python section (fenced with ---)
  if (pythonNodes.length > 0) {
    if (parts.length > 0) {
      parts.push('') // blank line between directives and fence
    }
    parts.push('---')

    const pythonText = formatPythonNodes(pythonNodes, options)
    parts.push(pythonText.trimEnd())

    parts.push('---')
  }

  // HTML template section
  const htmlText = document.html
  if (htmlText.trim().length > 0) {
    if (parts.length > 0) {
      parts.push('') // blank line before HTML
    }
    parts.push(htmlText.trim())
  }

  const joined = parts.join('\n')
  return ensureFinalNewline(joined, options.endOfLine ?? 'lf')
}

function formatPythonNodes(nodes: HeaderNode[], options: PrettierOptions): string {
  if (nodes.length === 0) {
    return ''
  }

  const filePath = options.filepath ?? process.cwd()
  const ruffConfig = resolveRuffFormatOptions(loadRuffConfig(filePath), {
    printWidth: options.printWidth,
    tabWidth: options.tabWidth,
    useTabs: options.useTabs,
    singleQuote: options.singleQuote,
  })

  return nodes
    .map((node) => {
      if (node.text.trim().length === 0) {
        return node.text
      }
      return formatPython(node.text, ruffConfig)
    })
    .join('\n')
}

function formatDirectives(nodes: HeaderNode[], options: PrettierOptions): string {
  const filePath = options.filepath ?? process.cwd()
  const ruffConfig = resolveRuffFormatOptions(loadRuffConfig(filePath), {
    printWidth: options.printWidth,
    tabWidth: options.tabWidth,
    useTabs: options.useTabs,
    singleQuote: options.singleQuote,
  })

  return nodes
    .map((node) => {
      const line = node.text.trim()
      if (line.startsWith('!path') || line.startsWith('!layout')) {
        const name = line.startsWith('!path') ? '!path' : '!layout'
        const arg = line.slice(name.length).trim()
        if (arg.length === 0) return line

        // Wrap as an assignment to force Ruff to format it as an expression
        const wrapped = `_ = ${arg}`
        const formatted = formatPython(wrapped, ruffConfig).trim()

        if (formatted.startsWith('_ = ')) {
          return `${name} ${formatted.slice(4)}`
        }
        return line // Fallback if formatting fails or returns unexpected structure
      }
      return node.text
    })
    .join('\n')
}

function ensureFinalNewline(text: string, endOfLine: 'lf' | 'crlf' | 'cr'): string {
  const lineEnding = endOfLine === 'crlf' ? '\r\n' : endOfLine === 'cr' ? '\r' : '\n'
  const normalized = text.replace(/\r?\n/g, lineEnding)
  return normalized.endsWith(lineEnding) ? normalized : normalized + lineEnding
}
