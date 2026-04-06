import { describe, it, expect, vi, beforeEach } from 'vitest'

const formatMock = vi.hoisted(() => vi.fn())
const initMock = vi.hoisted(() => vi.fn())

vi.mock('@wasm-fmt/ruff_fmt', () => ({
  format: (...args: unknown[]) => formatMock(...args),
  default: () => initMock(),
}))

import { formatPython, initializeRuff } from './ruff-formatter.js'
import { beforeAll } from 'vitest'

describe('formatPython', () => {
  beforeAll(async () => {
    await initializeRuff()
  })

  beforeEach(() => {
    formatMock.mockReset()
    initMock.mockReset()
  })

  it('formats python when formatter is available', () => {
    formatMock.mockReturnValue('formatted')
    const result = formatPython('x=1', {})

    expect(result).toBe('formatted')
    expect(formatMock).toHaveBeenCalledWith('x=1', undefined, {})
  })

  it('returns original code when formatter throws', () => {
    formatMock.mockImplementation(() => {
      throw new Error('boom')
    })

    const result = formatPython('x=1', {})
    expect(result).toBe('x=1')
  })
})
