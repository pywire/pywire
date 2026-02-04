/// <reference lib="webworker" />

const CACHE_NAME = 'pywire-pyodide-cache-v1';
const PYODIDE_VERSION = '0.29.3';
const PYODIDE_BASE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;


const sw = self as unknown as ServiceWorkerGlobalScope;

sw.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME).then(async (cache) => {
            console.log('[SW] Caching Pyodide base assets');
            const filesToCache = [
                `${PYODIDE_BASE_URL}pyodide.js`,
                `${PYODIDE_BASE_URL}pyodide.asm.js`,
                `${PYODIDE_BASE_URL}pyodide.asm.wasm`,
                `${PYODIDE_BASE_URL}python_stdlib.zip`,
            ];
            for (const file of filesToCache) {
                try {
                    const response = await fetch(file);
                    if (response.ok) {
                        await cache.put(file, response);
                    } else {
                        console.warn(`[SW] Failed to cache ${file}: ${response.status}`);
                    }
                } catch (e) {
                    console.warn(`[SW] Error caching ${file}:`, e);
                }
            }
        }).then(() => {
            console.log('[SW] Install sequence completed');
            return sw.skipWaiting();
        })
    );
});

sw.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('[SW] Clearing old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => sw.clients.claim())
    );
});

sw.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Intercept Pyodide CDN requests and wheel files
    if ((url.hostname === 'cdn.jsdelivr.net' && url.pathname.includes('/pyodide/')) ||
        (url.pathname.endsWith('.whl') || url.pathname.endsWith('.zip'))) {
        event.respondWith(
            caches.match(event.request).then((cachedResponse) => {
                if (cachedResponse) {
                    // console.log('[SW] Serving from cache:', url.pathname);
                    return cachedResponse;
                }

                return fetch(event.request).then((response) => {
                    // Dynamic caching for wheels and other Pyodide assets
                    if (!response || response.status !== 200 || (response.type !== 'cors' && response.type !== 'basic')) {
                        return response;
                    }

                    const responseToCache = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseToCache);
                    });

                    return response;
                });
            })
        );
    }
});
