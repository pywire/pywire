import { describe, it, expect, vi } from 'vitest'
import { printPywire } from './printer.js'
import { parsePywire } from './parser.js'

vi.mock('./utils/ruff-formatter.js', () => ({
  formatPython: (code: string) =>
    code.startsWith('_ = ') ? `_ = FORMATTED_${code.slice(4).trim()}` : `FORMATTED_${code.trim()}`,
}))

vi.mock('./utils/ruff-config.js', () => ({
  loadRuffConfig: () => ({}),
  resolveRuffFormatOptions: () => ({}),
}))

describe('printPywire', () => {
  it('formats python header and html with --- fences', () => {
    const input = `---\nx=1\n---\n<div><span>{x}</span></div>\n`
    const doc = parsePywire(input)
    const output = printPywire({ getValue: () => doc }, { printWidth: 80 })

    expect(output).toContain('---')
    expect(output).toContain('FORMATTED_x=1')
    expect(output).toContain('<div>')
    expect(output).toContain('<span>{x}</span>')
  })

  it('preserves interpolations while formatting html', () => {
    const input = `<div>{f"Hi {name}"}</div>\n`
    const doc = parsePywire(input)
    const output = printPywire({ getValue: () => doc }, { printWidth: 80 })

    expect(output).toContain('{f"Hi {name}"}')
  })

  it('formats directives with Ruff', () => {
    const input = `!path {"a": 1}\n!layout "base.wire"\n---html---\n`
    const doc = parsePywire(input)
    const output = printPywire({ getValue: () => doc }, { printWidth: 80 })

    // Our mock: formatPython: (code: string) => `FORMATTED(${code.trim()})`
    // Input to formatPython: `_ = {"a": 1}`
    // Output from formatPython: `FORMATTED(_ = {"a": 1})`
    // printer.ts does formatted.slice(4) -> "TTED(_ = {"a": 1})"

    expect(output).toContain('!path')
    expect(output).toContain('!layout')
    expect(output).toContain('FORMATTED_{"a": 1}')
    expect(output).toContain('FORMATTED_"base.wire"')
  })
})
