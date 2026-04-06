import { describe, it, expect, vi } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import prettier from 'prettier'
import plugin from '../src/index.js'

vi.mock('../src/utils/ruff-formatter.js', () => ({
  formatPython: (code: string) => code,
  initializeRuff: () => Promise.resolve(),
}))

vi.mock('../src/utils/ruff-config.js', () => ({
  loadRuffConfig: () => ({}),
  resolveRuffFormatOptions: (_config: Record<string, unknown>) => _config,
}))

const fixturesDir = join(dirname(fileURLToPath(import.meta.url)), 'fixtures')

describe('prettier-plugin-pywire integration', () => {
  const inputs = readdirSync(fixturesDir).filter((file) => file.startsWith('input-'))

  for (const inputFile of inputs) {
    const expectedFile = inputFile.replace('input-', 'expected-')
    const inputPath = join(fixturesDir, inputFile)
    const expectedPath = join(fixturesDir, expectedFile)

    it(`formats ${inputFile}`, async () => {
      const input = readFileSync(inputPath, 'utf8')
      const expected = ensureTrailingNewline(readFileSync(expectedPath, 'utf8'))

      const output = await prettier.format(input, {
        parser: 'pywire',
        plugins: [plugin],
        filepath: inputPath,
      })

      expect(output).toBe(expected)
    })
  }
})

function ensureTrailingNewline(text: string): string {
  if (text.endsWith('\n')) {
    return text
  }
  return `${text}\n`
}
