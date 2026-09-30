import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'
import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { loadRuffConfig, resolveRuffFormatOptions } from './ruff-config.js'

describe('loadRuffConfig', () => {
  let root: string

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'ruff-config-'))
  })

  afterEach(() => {
    fs.rmSync(root, { recursive: true, force: true })
  })

  function write(rel: string, content: string): void {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true })
    fs.writeFileSync(path.join(root, rel), content)
  }

  it('returns empty object when no config found', () => {
    expect(loadRuffConfig(path.join(root, 'file.wire'))).toEqual({})
  })

  it('extracts tool.ruff.format from pyproject.toml', () => {
    write(
      'pyproject.toml',
      '[tool.ruff]\nline_length = 90\n[tool.ruff.format]\nquote_style = "single"\n'
    )

    expect(loadRuffConfig(path.join(root, 'src', 'file.wire'))).toEqual({
      line_length: 90,
      format: {
        quote_style: 'single',
      },
      quote_style: 'single',
    })
  })

  it('skips a pyproject.toml without [tool.ruff] and prefers ruff.toml', () => {
    write('ruff.toml', 'line-length = 70\n')
    write('app/pyproject.toml', '[project]\nname = "x"\n')
    expect(loadRuffConfig(path.join(root, 'app', 'page.wire'))).toEqual({ 'line-length': 70 })
    write('app/.ruff.toml', 'line-length = 60\n')
    expect(loadRuffConfig(path.join(root, 'app', 'page.wire'))).toEqual({ 'line-length': 60 })
  })

  it('never runs JavaScript config files from the project', () => {
    const marker = path.join(root, 'ran')
    const js = `require('fs').writeFileSync(${JSON.stringify(marker)}, 'x')\n`
    write('.config/config.js', js)
    write('.config/config.cjs', js)
    write('ruff.config.js', js)
    loadRuffConfig(path.join(root, 'page.wire'))
    expect(fs.existsSync(marker)).toBe(false)
  })
})

describe('resolveRuffFormatOptions', () => {
  it('maps prettier options when config is missing', () => {
    const resolved = resolveRuffFormatOptions(
      {},
      {
        printWidth: 100,
        tabWidth: 4,
        useTabs: false,
        singleQuote: true,
      }
    )

    expect(resolved).toMatchObject({
      line_length: 100,
      indent_width: 4,
      indent_style: 'space',
      quote_style: 'single',
    })
  })

  it('prefers config values over prettier options', () => {
    const resolved = resolveRuffFormatOptions(
      { line_length: 80, indent_style: 'tab' },
      { printWidth: 120, useTabs: false }
    )

    expect(resolved).toMatchObject({
      line_length: 80,
      indent_style: 'tab',
    })
  })
})
