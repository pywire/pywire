import { describe, it, expect } from 'vitest'
import { parsePywire } from './parser.js'

describe('parsePywire', () => {
  it('splits python header and html with --- fences', () => {
    const input = `---\nname = "World"\n---\n<div>{name}</div>\n`
    const result = parsePywire(input)

    expect(result.headerNodes).toHaveLength(1)
    expect(result.headerNodes[0]).toEqual({ type: 'Python', text: 'name = "World"' })
    expect(result.separator).toBe('---')
    expect(result.html).toBe('<div>{name}</div>\n')
  })

  it('groups directives separately from fenced python', () => {
    const input = `!path '/'\n\n---\nx = 1\n---\n<p>{x}</p>\n`
    const result = parsePywire(input)

    expect(result.headerNodes).toHaveLength(2)
    expect(result.headerNodes[0]).toEqual({ type: 'Directive', text: "!path '/'" })
    expect(result.headerNodes[1]).toEqual({ type: 'Python', text: 'x = 1' })
  })

  it('captures multiline directive blocks', () => {
    const input = `!path {\n  "main": "/"\n}\n\n---\nvalue = 2\n---\n<div></div>\n`
    const result = parsePywire(input)

    expect(result.headerNodes).toHaveLength(2)
    expect(result.headerNodes[0].type).toBe('Directive')
    expect(result.headerNodes[0].text).toContain('!path {')
    expect(result.headerNodes[0].text).toContain('"main": "/"')
    expect(result.headerNodes[1]).toEqual({ type: 'Python', text: 'value = 2' })
  })

  it('treats files without separator as html', () => {
    const input = '<div>Only html</div>\n'
    const result = parsePywire(input)

    expect(result.separator).toBeNull()
    expect(result.headerNodes).toHaveLength(0)
    expect(result.html).toBe(input)
  })

})

