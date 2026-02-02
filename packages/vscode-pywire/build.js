import esbuild from 'esbuild'
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
} from 'fs'
import { join, resolve } from 'path'

// Recursively find a file by name in a directory
function findFile(dir, filename, maxDepth = 10) {
  if (maxDepth <= 0 || !existsSync(dir)) return null
  try {
    for (const entry of readdirSync(dir)) {
      const fullPath = join(dir, entry)
      const stat = statSync(fullPath, { throwIfNoEntry: false })
      if (entry === filename && stat?.isFile()) return fullPath
      // Include .pnpm directory for pnpm package manager
      if (stat?.isDirectory() && (entry === '.pnpm' || !entry.startsWith('.'))) {
        const found = findFile(fullPath, filename, maxDepth - 1)
        if (found) return found
      }
    }
  } catch {
    /* ignore permission errors */
  }
  return null
}

const production = process.argv.includes('--production')
const watch = process.argv.includes('--watch')

const projectRoot = resolve('.')

async function main() {
  const ctx = await esbuild.context({
    entryPoints: ['src/extension.ts'],
    bundle: true,
    format: 'cjs',
    minify: production,
    sourcemap: !production,
    sourcesContent: false,
    platform: 'node',
    outfile: 'out/extension.cjs',
    mainFields: ['module', 'main'],
    loader: {
      '.wasm': 'file',
    },
    external: ['vscode', 'prettier', 'prettier-plugin-pywire'],
    logLevel: 'warning',
    plugins: [
      {
        name: 'esbuild-problem-matcher',
        setup(build) {
          build.onStart(() => {
            console.log('[watch] build started')
          })
          build.onEnd((result) => {
            result.errors.forEach(({ text, location }) => {
              console.error(`✘ [ERROR] ${text}`)
              console.error(`    ${location.file}:${location.line}:${location.column}:`)
            })
            console.log('[watch] build finished')

            // Copy lsp_launcher.py to out/ after successful build
            if (result.errors.length === 0) {
              try {
                const outDir = join(projectRoot, 'out')
                mkdirSync(outDir, { recursive: true })
                copyFileSync(
                  join(projectRoot, 'src/lsp_launcher.py'),
                  join(outDir, 'lsp_launcher.py')
                )
                console.log('Copied lsp_launcher.py to out/')
              } catch (e) {
                console.error('Failed to copy lsp_launcher.py:', e)
              }

              // Copy prettier modules to out/node_modules for runtime resolution
              try {
                const outNodeModulesDir = join(projectRoot, 'out', 'node_modules')
                // Clear old copies to avoid stale files
                if (existsSync(outNodeModulesDir)) {
                  rmSync(outNodeModulesDir, { recursive: true, force: true })
                }
                mkdirSync(outNodeModulesDir, { recursive: true })

                const modulesToCopy = ['prettier', 'prettier-plugin-pywire']
                let prettierPluginSourceDir = null
                for (const moduleName of modulesToCopy) {
                  const symlinkedPath = join(projectRoot, 'node_modules', moduleName)
                  if (!existsSync(symlinkedPath)) {
                    console.warn(`Module not found for bundling: ${moduleName}`)
                    continue
                  }
                  // Follow symlinks (pnpm uses symlinks)
                  const realSourceDir = realpathSync(symlinkedPath)
                  if (moduleName === 'prettier-plugin-pywire') {
                    prettierPluginSourceDir = realSourceDir
                  }
                  const targetDir = join(outNodeModulesDir, moduleName)
                  cpSync(realSourceDir, targetDir, { recursive: true, dereference: true })
                  console.log(`Copied ${moduleName} to out/node_modules/`)
                }

                // Copy ruff WASM file next to the plugin's CJS bundle
                // The CJS build uses import.meta.url shim which resolves to the CJS file location
                if (!prettierPluginSourceDir) {
                  throw new Error('prettier-plugin-pywire was not found for bundling')
                }
                const wasmDest = join(
                  outNodeModulesDir,
                  'prettier-plugin-pywire',
                  'dist',
                  'ruff_fmt_bg.wasm'
                )
                const wasmSearchRoots = [
                  prettierPluginSourceDir,
                  join(prettierPluginSourceDir, 'node_modules'),
                  join(projectRoot, 'node_modules'),
                ]
                let wasmSource = null
                for (const root of wasmSearchRoots) {
                  if (!root) continue
                  const found = findFile(root, 'ruff_fmt_bg.wasm')
                  if (!found) continue
                  wasmSource = found
                  break
                }
                if (!wasmSource) {
                  throw new Error(
                    'ruff_fmt_bg.wasm not found. Ensure @wasm-fmt/ruff_fmt is installed and its WASM artifact is present.'
                  )
                }
                copyFileSync(wasmSource, wasmDest)
                console.log(
                  'Copied ruff_fmt_bg.wasm to out/node_modules/prettier-plugin-pywire/dist/'
                )
              } catch (e) {
                console.error('Failed to copy node_modules:', e)
                process.exit(1)
              }
            }
          })
        },
      },
    ],
  })

  if (watch) {
    await ctx.watch()
  } else {
    await ctx.rebuild()
    await ctx.dispose()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
