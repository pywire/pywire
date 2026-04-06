import prettier from 'prettier'

type PrettierLikeOptions = Record<string, unknown> & {
  plugins?: unknown[]
}

// Matches PyWire expression attributes: @event={...}, attr={...}, {shorthand}, and {**spread}
const PYWIRE_ATTR_REGEX =
  /([@\w.-]+=\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\{\*\*[^{}]*\}|(?<![\w.-])\{[a-zA-Z_]\w*\}(?![\w.-])|__pywire_spread__="\{.*\}")/g
// Matches text interpolations and block directives starting with $ or /: {$var}, {$if ...}, {/if}, etc.
// Handles one level of nested braces (e.g. {$func({...})})
const PYWIRE_BRACE_REGEX = /\{([$/][^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g

type Placeholder = {
  placeholder: string
  original: string
}
function protectPywireExpressions(
  html: string,
  componentNames: string[] = []
): {
  protected: string
  placeholders: Placeholder[]
} {
  const placeholders: Placeholder[] = []
  let counter = 0
  let result = html.replace(PYWIRE_ATTR_REGEX, (match) => {
    const placeholder = `__PYWIRE_ATTR_${counter++}__`
    if (match.startsWith('{**')) {
      // Spread attribute: {**props} -> data-pw-spread="..."
      const replacement = `data-pw-spread="${placeholder}"`
      placeholders.push({ placeholder, original: match })
      return replacement
    }

    const eqIndex = match.indexOf('=')
    if (eqIndex > 0) {
      const attrName = match.substring(0, eqIndex)
      const replacement = `${attrName}="${placeholder}"`
      placeholders.push({ placeholder, original: match })
      return replacement
    }

    return match
  })

  // Protect text interpolations and block directives: {$if ...}, {expr}, etc.
  result = result.replace(PYWIRE_BRACE_REGEX, (match) => {
    const placeholder = `__PYWIRE_INTERP_${counter++}__`
    placeholders.push({ placeholder, original: match })
    return placeholder
  })

  // Protect component tags from being lowercased by Prettier's HTML parser
  if (componentNames.length > 0) {
    const nameToPlaceholder = new Map<string, string>()
    const componentRegex = new RegExp(`<(/)?(${componentNames.join('|')})(?=[\\s/>])`, 'g')
    result = result.replace(componentRegex, (match, closing, name) => {
      let placeholder = nameToPlaceholder.get(name)
      if (!placeholder) {
        placeholder = `pw-tag-${counter++}`
        nameToPlaceholder.set(name, placeholder)
        placeholders.push({ placeholder, original: name })
      }
      return `<${closing || ''}${placeholder}`
    })
  }

  return { protected: result, placeholders }
}

function restorePywireExpressions(html: string, placeholders: Placeholder[]): string {
  let result = html
  for (const { placeholder, original } of placeholders) {
    if (placeholder.startsWith('__PYWIRE_ATTR_')) {
      // Handle attribute placeholders (wrapped in quotes by HTML formatter)
      const attrPattern = new RegExp(`[\\w@:.-]+=["']?${placeholder}["']?`, 'g')
      result = result.replace(attrPattern, original)
    } else if (placeholder.startsWith('pw-tag-')) {
      // Handle tag name placeholders (Prettier might lowercase them, though pw-tag- is already lower)
      const tagPattern = new RegExp(placeholder, 'g')
      result = result.replace(tagPattern, original)
    } else {
      // Handle text placeholders
      result = result.replace(new RegExp(placeholder, 'g'), original)
    }
  }
  return result
}

export async function formatHtmlWithPrettier(
  html: string,
  options: PrettierLikeOptions,
  componentNames: string[] = []
): Promise<string> {
  if (html.trim().length === 0) {
    return html
  }

  const { plugins: _plugins, ...prettierOptions } = options
  void _plugins

  // Protect PyWire expressions before HTML formatting
  const { protected: protectedHtml, placeholders } = protectPywireExpressions(html, componentNames)

  const formatted = await prettier.format(protectedHtml, {
    ...prettierOptions,
    parser: 'html',
  })

  // Restore PyWire expressions after formatting
  return restorePywireExpressions(formatted, placeholders)
}
