import * as fs from 'fs'
import * as path from 'path'
import { parse as parseToml } from '@iarna/toml'

export type RuffFormatConfig = Record<string, unknown>

type Table = Record<string, unknown>

function readToml(file: string): Table | null {
  let content: string
  try {
    content = fs.readFileSync(file, 'utf8')
  } catch {
    return null
  }
  try {
    return parseToml(content) as Table
  } catch {
    return null
  }
}

function asTable(value: unknown): Table {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Table) : {}
}

// Ruff's own settings with its [format] section laid over them.
function flatten(ruff: Table): RuffFormatConfig {
  return { ...ruff, ...asTable(ruff.format) }
}

/**
 * The Ruff settings that apply to `filePath`, found the way Ruff finds them:
 * the closest directory with a `.ruff.toml`, `ruff.toml`, or a
 * `pyproject.toml` that has a `[tool.ruff]` table.
 *
 * Only these TOML files are read. Nothing is executed, so formatting a file
 * in an untrusted checkout can't run code from it.
 */
export function loadRuffConfig(filePath?: string | null): RuffFormatConfig {
  const start = path.resolve(filePath ?? process.cwd())
  let dir = fs.existsSync(start) && fs.statSync(start).isDirectory() ? start : path.dirname(start)
  for (;;) {
    for (const name of ['.ruff.toml', 'ruff.toml']) {
      const config = readToml(path.join(dir, name))
      if (config) return flatten(config)
    }
    const pyproject = readToml(path.join(dir, 'pyproject.toml'))
    const ruff = pyproject && asTable(pyproject.tool).ruff
    if (ruff) return flatten(asTable(ruff))
    const parent = path.dirname(dir)
    if (parent === dir) return {}
    dir = parent
  }
}

export function resolveRuffFormatOptions(
  config: RuffFormatConfig,
  prettierOptions: {
    printWidth?: number
    tabWidth?: number
    useTabs?: boolean
    singleQuote?: boolean
  }
): RuffFormatConfig {
  const lineLength =
    pickConfigValue(config, ['line_length', 'line-length', 'lineLength']) ??
    prettierOptions.printWidth
  const indentStyle =
    pickConfigValue(config, ['indent_style', 'indent-style', 'indentStyle']) ??
    (prettierOptions.useTabs ? 'tab' : 'space')
  const indentWidth =
    pickConfigValue(config, ['indent_width', 'indent-width', 'indentWidth']) ??
    prettierOptions.tabWidth
  const quoteStyle =
    pickConfigValue(config, ['quote_style', 'quote-style', 'quoteStyle']) ??
    (prettierOptions.singleQuote ? 'single' : 'double')

  const resolved: RuffFormatConfig = {}
  if (lineLength !== undefined) {
    resolved.line_length = lineLength
  }
  if (indentStyle !== undefined) {
    resolved.indent_style = indentStyle
  }
  if (indentWidth !== undefined) {
    resolved.indent_width = indentWidth
  }
  if (quoteStyle !== undefined) {
    resolved.quote_style = quoteStyle
  }

  return {
    ...config,
    ...resolved,
  }
}

function pickConfigValue(config: RuffFormatConfig, keys: string[]): unknown | undefined {
  for (const key of keys) {
    if (key in config) {
      return config[key]
    }
  }
  return undefined
}
