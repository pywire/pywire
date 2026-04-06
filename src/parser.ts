const fenceSeparatorRegex = /^\s*---\s*$/
const directiveStartRegex = /^\s*!/

export type HeaderNode = { type: 'Directive'; text: string } | { type: 'Python'; text: string }

export type ParsedDocument = {
  type: 'Document'
  start: number
  end: number
  headerNodes: HeaderNode[]
  separator: string | null
  html: string
}

export type SplitSections = {
  directives: string
  separator: string | null
  python: string
  html: string
}

/**
 * Split a .wire file into its sections:
 *   1. Directives (optional) — lines starting with !
 *   2. Fenced Python (optional) — between --- separators
 *   3. Template HTML
 */
export function splitPywireSections(text: string): SplitSections {
  const lines = text.split(/\r?\n/)

  // Find all --- fence lines
  const fenceIndices: number[] = []
  for (let i = 0; i < lines.length; i++) {
    if (fenceSeparatorRegex.test(lines[i])) {
      fenceIndices.push(i)
    }
  }

  // Two or more fences — content between first two fences is Python
  if (fenceIndices.length >= 2) {
    const openFence = fenceIndices[0]
    const closeFence = fenceIndices[1]

    return {
      directives: lines.slice(0, openFence).join('\n'),
      separator: '---', // Normalize to three dashes
      python: lines.slice(openFence + 1, closeFence).join('\n'),
      html: lines.slice(closeFence + 1).join('\n'),
    }
  }

  // No valid fences or malformed — everything is either directives + html or just html
  // If fenceIndices.length === 1, we still fall back to this to avoid corrupting python blocks
  // Check if the first non-empty, non-directive line looks like html or python
  // If there are no directives at all, everything is html
  const hasDirectives = lines.some((line) => directiveStartRegex.test(line.trim()))

  if (!hasDirectives) {
    return {
      directives: '',
      separator: null,
      python: '',
      html: text,
    }
  }

  // Has directives but no fence — split at first non-directive, non-empty line
  // that isn't part of a block directive
  let directiveEnd = 0
  let braceDepth = 0
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    braceDepth += countBraces(lines[i])

    if (braceDepth > 0) {
      directiveEnd = i + 1
      continue
    }

    if (directiveStartRegex.test(trimmed)) {
      directiveEnd = i + 1
      continue
    }

    if (trimmed.length === 0 && directiveEnd === i) {
      directiveEnd = i + 1
      continue
    }

    if (directiveEnd > 0 && trimmed.length > 0 && !directiveStartRegex.test(trimmed)) {
      break
    }
  }

  return {
    directives: lines.slice(0, directiveEnd).join('\n'),
    separator: null,
    python: '',
    html: lines.slice(directiveEnd).join('\n'),
  }
}

export function parsePywire(text: string): ParsedDocument {
  const sections = splitPywireSections(text)

  const headerNodes: HeaderNode[] = []

  // Parse directives
  if (sections.directives.trim().length > 0) {
    const directiveNodes = parseDirectives(sections.directives.split('\n'))
    headerNodes.push(...directiveNodes)
  }

  // Parse python
  if (sections.python.trim().length > 0) {
    headerNodes.push({ type: 'Python', text: sections.python })
  }

  return {
    type: 'Document',
    start: 0,
    end: text.length,
    headerNodes,
    separator: sections.separator,
    html: sections.html,
  }
}

function parseDirectives(lines: string[]): HeaderNode[] {
  const nodes: HeaderNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    const trimmed = line.trim()

    if (trimmed.length === 0) {
      index++
      continue
    }

    if (!directiveStartRegex.test(trimmed)) {
      // Non-directive, non-empty line in directives section — skip
      index++
      continue
    }

    const directiveLines: string[] = [line]
    let braceDepth = countBraces(line)
    index++

    while (braceDepth > 0 && index < lines.length) {
      const nextLine = lines[index]
      directiveLines.push(nextLine)
      braceDepth += countBraces(nextLine)
      index++
    }

    nodes.push({ type: 'Directive', text: directiveLines.join('\n') })
  }

  return nodes
}

function countBraces(line: string): number {
  const openCount = line.match(/{/g)?.length ?? 0
  const closeCount = line.match(/}/g)?.length ?? 0
  return openCount - closeCount
}
