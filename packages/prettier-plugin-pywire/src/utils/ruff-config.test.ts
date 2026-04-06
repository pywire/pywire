import { describe, it, expect, vi, beforeEach } from 'vitest'

const searchMock = vi.hoisted(() => vi.fn())

vi.mock('cosmiconfig', () => ({
  cosmiconfigSync: () => ({
    search: searchMock,
  }),
}))

import { loadRuffConfig, resolveRuffFormatOptions } from './ruff-config.js'

describe('loadRuffConfig', () => {
  beforeEach(() => {
    searchMock.mockReset()
  })

  it('returns empty object when no config found', () => {
    searchMock.mockReturnValue(null)
    expect(loadRuffConfig('/tmp/file.wire')).toEqual({})
  })

  it('extracts tool.ruff.format from pyproject.toml', () => {
    searchMock.mockReturnValue({
      filepath: '/tmp/pyproject.toml',
      config: {
        tool: {
          ruff: {
            line_length: 90,
            format: {
              quote_style: 'single',
            },
          },
        },
      },
    })

    expect(loadRuffConfig('/tmp/file.wire')).toEqual({
      line_length: 90,
      format: {
        quote_style: 'single',
      },
      quote_style: 'single',
    })
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
