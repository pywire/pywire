/// <reference lib="webworker" />

// Import type-only since we use importScripts for the actual library
import type { PyodideInterface } from 'pyodide';

declare global {
    function loadPyodide(options?: any): Promise<PyodideInterface>;
    function importScripts(...urls: string[]): void;
}

importScripts("https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js");

let pyodide: PyodideInterface | null = null;

async function loadPywire(baseUrl: string) {
    console.log("[Worker] Starting loadPywire with baseUrl:", baseUrl);
    postMessage({ type: "STDOUT", message: "Loading Pyodide runtime..." });

    pyodide = await loadPyodide();
    console.log("[Worker] Pyodide loaded successfully");

    // Mount IDBFS for persistent packages
    const PERSISTENT_DIR = "/home/pyodide/persistent";
    try {
        // Ensure path exists
        const parts = PERSISTENT_DIR.split('/').filter(Boolean);
        let currentPath = '';
        for (const part of parts) {
            currentPath += `/${part}`;
            try {
                if (!pyodide.FS.analyzePath(currentPath).exists) {
                    pyodide.FS.mkdir(currentPath);
                }
            } catch (e) {
                // Ignore if it exists (Errno 17) or other minor errors
            }
        }

        pyodide.FS.mount((pyodide.FS as any).filesystems.IDBFS, {}, PERSISTENT_DIR);
        console.log("[Worker] IDBFS mounted");

        // Sync from IndexedDB to memory
        await new Promise<void>((resolve, reject) => {
            pyodide!.FS.syncfs(true, (err: any) => {
                if (err) {
                    console.error("[Worker] Error syncing IDBFS (read):", err);
                    reject(err);
                } else {
                    console.log("[Worker] IDBFS synced from IndexedDB");
                    resolve();
                }
            });
        });
    } catch (e) {
        console.error("[Worker] Failed to mount IDBFS:", e);
    }

    postMessage({ type: "STDOUT", message: "Pyodide loaded. Checking cache..." });

    try {
        // Add persistent path to sys.path immediately
        const sitePackages = `${PERSISTENT_DIR}/site-packages`;
        await pyodide.runPythonAsync(`
import sys, os, importlib
PERSISTENT_SITE_PACKAGES = "${sitePackages}"
print(f"[Python] Checking {PERSISTENT_SITE_PACKAGES}...")
if not os.path.exists(PERSISTENT_SITE_PACKAGES):
    os.makedirs(PERSISTENT_SITE_PACKAGES, exist_ok=True)
    print(f"[Python] Created {PERSISTENT_SITE_PACKAGES}")
if PERSISTENT_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, PERSISTENT_SITE_PACKAGES)
    print(f"[Python] Inserted into sys.path: {PERSISTENT_SITE_PACKAGES}")
importlib.invalidate_caches()
`);

        // Check if packages are already installed in IDBFS
        // Check if packages are already installed in IDBFS AND pywire is importable
        const markerFile = `${PERSISTENT_DIR}/INSTALLED_MARKER`;
        const checkResult = await pyodide.runPythonAsync(`
import os, sys, importlib
marker_exists = os.path.exists("${markerFile}")
pywire_exists = False
if marker_exists:
    try:
        import pywire
        pywire_exists = True
    except ImportError:
        pass
(marker_exists and pywire_exists)
`);

        if (checkResult) {
            console.log("[Worker] Packages found and verified in IDBFS cache. Skipping installation.");
            postMessage({ type: "STDOUT", message: "Packages loaded from cache." });
        } else {
            console.log("[Worker] First run: Installing packages...");
            postMessage({ type: "STDOUT", message: "Installing core packages (first time)..." });

            await pyodide.loadPackage(["micropip", "lxml", "ssl", "pydantic", "anyio"]);
            console.log("[Worker] Core packages loaded");

            const micropip = pyodide.pyimport("micropip");
            console.log("[Worker] micropip imported");

            // Mock binary or CLI-only dependencies
            micropip.add_mock_package("watchfiles", "0.21.0");
            micropip.add_mock_package("uvicorn", "0.27.0");
            micropip.add_mock_package("textual", "7.4.0");
            micropip.add_mock_package("rich-click", "1.9.6");

            // Install Starlette and Dependencies into persistent target
            await micropip.install("typing-extensions>=4.10.0", { target: sitePackages });
            await micropip.install("starlette", { target: sitePackages });
            console.log("[Worker] Base dependencies installed in IDBFS");

            // Install PyWire
            // NOTE: The wheel filename is updated during build-assets.mjs
            const pywireWhlUrl = `${baseUrl}dist/pywire-0.1.6.dev0+g303329e26.d20260204-py3-none-any.whl`;
            const wheelFileName = pywireWhlUrl.split('/').pop()!;
            console.log("[Worker] Installing pywire from:", pywireWhlUrl, "to", wheelFileName);

            const response = await fetch(pywireWhlUrl);
            const buffer = await response.arrayBuffer();
            const filePath = `/${wheelFileName}`;
            pyodide.FS.writeFile(filePath, new Uint8Array(buffer));
            await micropip.install(`emfs:${filePath}`, { target: sitePackages });

            // Create marker file
            pyodide.FS.writeFile(`${PERSISTENT_DIR}/INSTALLED_MARKER`, "");

            // Sync memory back to IndexedDB
            await new Promise<void>((resolve, reject) => {
                pyodide!.FS.syncfs(false, (err: any) => {
                    if (err) {
                        console.error("[Worker] Error syncing IDBFS (write):", err);
                        reject(err);
                    } else {
                        console.log("[Worker] IDBFS synced to IndexedDB");
                        resolve();
                    }
                });
            });

            await pyodide.runPythonAsync("import importlib; importlib.invalidate_caches()");
            postMessage({ type: "STDOUT", message: "Packages installed and cached." });
        }

        postMessage({ type: "STDOUT", message: "PyWire ready." });

        // Initialize File System
        pyodide.FS.mkdir("/pages");
        console.log("[Worker] /pages directory created");

        // Load the Shim
        console.log("[Worker] Fetching shim.py from:", `${baseUrl}shim.py`);
        const shimCode = await fetch(`${baseUrl}shim.py`).then(r => r.text());
        console.log("[Worker] Running shim.py...");
        postMessage({ type: "STDOUT", message: "Initializing PyWire shim..." });
        await pyodide.runPythonAsync(shimCode);
        console.log("[Worker] Shim executed successfully");

        postMessage({ type: "STDOUT", message: "\x1b[32mReady!\x1b[0m" });
        postMessage({ type: "READY" });
        console.log("[Worker] READY message sent");
    } catch (e: any) {
        console.error("[Worker] Error:", e);
        postMessage({ type: "STDERR", message: `Worker Initialization Failed: ${e}` });
    }
}

self.onmessage = async (event) => {
    const { type, payload } = event.data;

    if (!pyodide && type !== "INIT") return;

    if (type === "INIT") {
        const baseUrl = payload.baseUrl || "/";
        await loadPywire(baseUrl);
    }

    else if (type === "UPDATE_FILE") {
        // Write user code to virtual FS
        const path = `/pages/${payload.filename}`;
        pyodide!.FS.writeFile(path, payload.content);

        // Invalidate app cache for this file
        pyodide!.globals.get("reload_page")(path);
    }

    else if (type === "RESET") {
        console.log("[Worker] Resetting virtual FS...");
        try {
            const files = pyodide!.FS.readdir("/pages");
            for (const file of files) {
                if (file !== "." && file !== "..") {
                    pyodide!.FS.unlink(`/pages/${file}`);
                }
            }
            console.log("[Worker] Virtual FS reset successful");
        } catch (e) {
            console.error("[Worker] Error during reset:", e);
        }
    }

    else if (type === "REQUEST") {
        // Pass to Python shim safely
        pyodide!.globals.set("temp_req_payload", pyodide!.toPy(payload));
        await pyodide!.runPythonAsync(`
import asyncio
import js
from pyodide.ffi import to_js
asyncio.create_task(js.handle_message(temp_req_payload))
    `);
    }
};
