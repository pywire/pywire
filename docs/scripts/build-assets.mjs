import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../..');
const DOCS_DIR = path.resolve(__dirname, '..');
const DOCS_PUBLIC_DIR = path.resolve(DOCS_DIR, 'public');
const CLIENT_DIR = path.resolve(REPO_ROOT, 'src/pywire/client');

function run(cmd, cwd) {
    console.log(`> ${cmd} (in ${cwd})`);
    execSync(cmd, { cwd, stdio: 'inherit' });
}

function bundleWorkers(wheelFile = "unknown") {
    console.log('\n--- Bundling Workers ---');
    const workers = [
        { src: 'src/sw.ts', dest: 'public/sw.js' },
        { src: 'src/pywire-worker.ts', dest: 'public/pywire-worker.js' }
    ];

    for (const worker of workers) {
        const swSrc = path.resolve(DOCS_DIR, worker.src);
        const swDest = path.resolve(DOCS_DIR, worker.dest);
        const define = `--define:__PYWIRE_WHEEL_NAME__='"${wheelFile}"'`;
        run(`npx esbuild ${swSrc} --bundle --outfile=${swDest} --minify --platform=browser ${define}`, DOCS_DIR);
    }
}

async function main() {
    console.log('Building Assets for Docs...');

    // 1. Build Client
    console.log('\n--- Building Client ---');
    // Ensure we have deps
    if (!fs.existsSync(path.join(CLIENT_DIR, 'node_modules'))) {
        run('pnpm install', CLIENT_DIR);
    }
    run('pnpm build', CLIENT_DIR);

    // Copy built client files
    const staticDest = path.join(DOCS_PUBLIC_DIR, '_pywire/static');
    fs.mkdirSync(staticDest, { recursive: true });

    const clientSrcDir = path.resolve(CLIENT_DIR, '../static');
    if (fs.existsSync(clientSrcDir)) {
        const files = fs.readdirSync(clientSrcDir);
        for (const file of files) {
            if (file.endsWith('.js') || file.endsWith('.js.map')) {
                console.log(`Copying ${file} to ${staticDest}`);
                fs.copyFileSync(path.join(clientSrcDir, file), path.join(staticDest, file));
            }
        }
    } else {
        console.error(`Client build directory not found: ${clientSrcDir}`);
        process.exit(1);
    }

    // 2. Build Python Wheel
    console.log('\n--- Building Python Wheel ---');
    const publicDistDir = path.join(DOCS_PUBLIC_DIR, 'dist');

    // Clean old wheels in public/dist
    if (fs.existsSync(publicDistDir)) {
        console.log(`Cleaning ${publicDistDir}...`);
        const oldWheels = fs.readdirSync(publicDistDir).filter(f => f.endsWith('.whl'));
        for (const old of oldWheels) {
            fs.unlinkSync(path.join(publicDistDir, old));
        }
    } else {
        fs.mkdirSync(publicDistDir, { recursive: true });
    }

    // Build directly to public/dist
    run(`uv build --wheel --out-dir ${publicDistDir}`, REPO_ROOT);

    // Find the wheel
    const distFiles = fs.readdirSync(publicDistDir);
    const wheelFiles = distFiles
        .filter(f => f.endsWith('.whl'))
        .map(f => ({ name: f, time: fs.statSync(path.join(publicDistDir, f)).mtime.getTime() }))
        .sort((a, b) => b.time - a.time);

    const wheelFile = wheelFiles.length > 0 ? wheelFiles[0].name : null;

    if (!wheelFile) {
        console.error('No wheel file generated!');
        process.exit(1);
    }

    console.log(`Generated wheel: ${wheelFile}`);

    // 3. Bundle Workers (now that we have the wheel filename)
    bundleWorkers(wheelFile);
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
