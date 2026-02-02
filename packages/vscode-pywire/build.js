import esbuild from 'esbuild'
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  realpathSync,
  rmSync,
} from 'fs'
import { createRequire } from 'module'
import { dirname, join, resolve } from 'path'

const require = createRequire(import.meta.url)

// Resolve a package's directory using Node's module resolution (works with pnpm symlinks)
function resolvePackageDir(packageName) {
  try {
    // Resolve the package's main entry point and get its directory
    const entryPath = require.resolve(packageName)
    // Walk up to find the package root (directory containing package.json)
    let dir = dirname(entryPath)
    while (dir !== dirname(dir)) {
      if (existsSync(join(dir, 'package.json'))) {
        return dir
      }
      dir = dirname(dir)
    }
  } catch {
    /* package not found */
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
                for (const moduleName of modulesToCopy) {
                  const symlinkedPath = join(projectRoot, 'node_modules', moduleName)
                  if (!existsSync(symlinkedPath)) {
                    console.warn(`Module not found for bundling: ${moduleName}`)
                    continue
                  }
                  // Follow symlinks (pnpm uses symlinks)
                  const realSourceDir = realpathSync(symlinkedPath)
                  const targetDir = join(outNodeModulesDir, moduleName)
                  cpSync(realSourceDir, targetDir, { recursive: true, dereference: true })
                  console.log(`Copied ${moduleName} to out/node_modules/`)
                }

                // Copy ruff WASM file next to the plugin's CJS bundle
                // Use Node's module resolution to find the package (works reliably with pnpm)
                const wasmDest = join(
                  outNodeModulesDir,
                  'prettier-plugin-pywire',
                  'dist',
                  'ruff_fmt_bg.wasm'
                )
                const ruffPkgDir = resolvePackageDir('@wasm-fmt/ruff_fmt')
                if (!ruffPkgDir) {
                  throw new Error(
                    '@wasm-fmt/ruff_fmt package not found. Ensure it is installed.'
                  )
                }
                const wasmSource = join(ruffPkgDir, 'ruff_fmt_bg.wasm')
                if (!existsSync(wasmSource)) {
                  throw new Error(
                    `ruff_fmt_bg.wasm not found at ${wasmSource}. The @wasm-fmt/ruff_fmt package may be corrupted.`
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
