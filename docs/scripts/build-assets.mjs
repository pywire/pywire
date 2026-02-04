import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '../../..');
const DOCS_DIR = path.resolve(__dirname, '..');
const DOCS_PUBLIC_DIR = path.resolve(DOCS_DIR, 'public');
const CLIENT_DIR = path.resolve(ROOT_DIR, 'pywire/src/pywire/client');

function run(cmd, cwd) {
    console.log(`> ${cmd} (in ${cwd})`);
    execSync(cmd, { cwd, stdio: 'inherit' });
}

function bundleWorkers() {
    console.log('\n--- Bundling Workers ---');
    const workers = [
        { src: 'src/sw.ts', dest: 'public/sw.js' },
        { src: 'src/pywire-worker.ts', dest: 'public/pywire-worker.js' }
    ];

    for (const worker of workers) {
        const swSrc = path.resolve(DOCS_DIR, worker.src);
        const swDest = path.resolve(DOCS_DIR, worker.dest);
        run(`npx esbuild ${swSrc} --bundle --outfile=${swDest} --minify --platform=browser`, DOCS_DIR);
    }
}

async function main() {
    console.log('Building Assets for Docs...');

    // 0. Bundle Workers
    bundleWorkers();

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

    const clientDist = path.join(CLIENT_DIR, '../static');
    // note: client build outputs to ../static relative to src/pywire/client/build.mjs 
    // which is pywire/src/pywire/static
    // Let's verify where build.mjs puts it. 
    // build.mjs says: outfile: resolve(__dirname, '../static/pywire.core.min.js')
    // So it is in src/pywire/static.

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
    // Clean dist
    const distDir = path.join(ROOT_DIR, 'dist');
    // If we want to ensure a fresh build, we can clean, but uv handles it well.
    // fs.rmSync(distDir, { recursive: true, force: true });

    run('uv build', path.join(ROOT_DIR, 'pywire'));

    // Find the wheel
    const distFiles = fs.readdirSync(distDir);
    const wheelFiles = distFiles
        .filter(f => f.endsWith('.whl'))
        .map(f => ({ name: f, time: fs.statSync(path.join(distDir, f)).mtime.getTime() }))
        .sort((a, b) => b.time - a.time);

    const wheelFile = wheelFiles.length > 0 ? wheelFiles[0].name : null;

    if (!wheelFile) {
        console.error('No wheel file generated!');
        process.exit(1);
    }

    const publicDistDir = path.join(DOCS_PUBLIC_DIR, 'dist');
    fs.mkdirSync(publicDistDir, { recursive: true });

    // Clean old wheels in public/dist
    const oldWheels = fs.readdirSync(publicDistDir).filter(f => f.endsWith('.whl'));
    for (const old of oldWheels) {
        fs.unlinkSync(path.join(publicDistDir, old));
    }

    console.log(`Copying ${wheelFile} to ${publicDistDir}`);
    fs.copyFileSync(path.join(distDir, wheelFile), path.join(publicDistDir, wheelFile));

    // 3. Update pywire-worker.js with new wheel filename
    console.log('\n--- Updating Worker Config ---');
    const workerPath = path.join(DOCS_PUBLIC_DIR, 'pywire-worker.js');
    let workerContent = fs.readFileSync(workerPath, 'utf-8');

    // Regex to replace the wheel file name
    // Assuming line like: await micropip.install(`${baseUrl}dist/pywire-....whl`);
    const regex = /dist\/pywire-.*?\.whl/g;

    if (regex.test(workerContent)) {
        const newContent = workerContent.replace(regex, `dist/${wheelFile}`);
        fs.writeFileSync(workerPath, newContent);
        console.log(`Updated pywire-worker.js to use ${wheelFile}`);
    } else {
        console.warn('Could not find wheel path pattern in pywire-worker.js to update!');
    }
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
