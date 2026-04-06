import { cosmiconfigSync } from 'cosmiconfig'
import { parse as parseToml } from '@iarna/toml'

export type RuffFormatConfig = Record<string, unknown>

const explorer = cosmiconfigSync('ruff', {
  searchPlaces: ['pyproject.toml', 'ruff.toml', '.ruff.toml'],
  loaders: {
    '.toml': (filepath, content) => parseToml(content),
  },
})

export function loadRuffConfig(filePath?: string | null): RuffFormatConfig {
  const result = explorer.search(filePath ?? process.cwd())
  if (!result || !result.config) {
    return {}
  }

  if (result.filepath.endsWith('pyproject.toml')) {
    const toolConfig = (result.config as Record<string, unknown>).tool ?? {}
    const ruffConfig = (toolConfig as Record<string, unknown>).ruff ?? {}
    const formatConfig = (ruffConfig as Record<string, unknown>).format ?? {}

    return {
      ...(ruffConfig as Record<string, unknown>),
      ...(formatConfig as Record<string, unknown>),
    }
  }

  return result.config as Record<string, unknown>
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
