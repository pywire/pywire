import esbuild from 'esbuild'
import {
  copyFileSync,
  cpSync,
  createWriteStream,
  existsSync,
  mkdirSync,
  realpathSync,
  rmSync,
  statSync,
} from 'fs'
import https from 'https'
import { createRequire } from 'module'
import { dirname, join, resolve } from 'path'

const require = createRequire(import.meta.url)

// Find the WASM file, trying local resolution first, then downloading from unpkg
async function findOrDownloadWasm(destPath) {
  // Try to find locally via require.resolve
  try {
    const entryPath = require.resolve('@wasm-fmt/ruff_fmt')
    let dir = dirname(entryPath)
    while (dir !== dirname(dir)) {
      if (existsSync(join(dir, 'package.json'))) {
        const wasmPath = join(dir, 'ruff_fmt_bg.wasm')
        // Check file actually exists and has content (not a broken symlink)
        try {
          const stats = statSync(wasmPath)
          if (stats.isFile() && stats.size > 0) {
            console.log(`Found ruff_fmt_bg.wasm locally at ${wasmPath}`)
            copyFileSync(wasmPath, destPath)
            return
          }
        } catch {
          // File doesn't exist or is broken symlink
        }
        break
      }
      dir = dirname(dir)
    }
  } catch {
    // Package not resolvable
  }

  // Fallback: download from unpkg
  console.log('WASM not found locally, downloading from unpkg...')
  const url = 'https://unpkg.com/@wasm-fmt/ruff_fmt@0.9.7/ruff_fmt_bg.wasm'
  await new Promise((resolve, reject) => {
    const file = createWriteStream(destPath)
    https
      .get(url, (response) => {
        if (response.statusCode === 302 || response.statusCode === 301) {
          // Follow redirect
          https
            .get(response.headers.location, (res) => {
              res.pipe(file)
              file.on('finish', () => {
                file.close()
                resolve()
              })
            })
            .on('error', reject)
        } else if (response.statusCode === 200) {
          response.pipe(file)
          file.on('finish', () => {
            file.close()
            resolve()
          })
        } else {
          reject(new Error(`Failed to download WASM: HTTP ${response.statusCode}`))
        }
      })
      .on('error', reject)
  })
  console.log('Downloaded ruff_fmt_bg.wasm from unpkg')
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
          build.onEnd(async (result) => {
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
                const pluginDistDir = join(outNodeModulesDir, 'prettier-plugin-pywire', 'dist')
                mkdirSync(pluginDistDir, { recursive: true })
                const wasmDest = join(pluginDistDir, 'ruff_fmt_bg.wasm')
                await findOrDownloadWasm(wasmDest)
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
