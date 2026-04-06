export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // --- 0. DETERMINE ENVIRONMENT ---
    const hostname = url.hostname;
    const isNightly = hostname.startsWith("nightly.");

    // Define base targets based on environment
    const landingTarget = isNightly ? "nightly.pywire-landing.pages.dev" : "pywire-landing.pages.dev";
    const docsTarget = isNightly ? "nightly.pywire-docs.pages.dev" : "pywire-docs.pages.dev";

    // --- 1. HANDLE SHORTCUT REDIRECTS ---
    const redirects = {
      // "/discord": "https://discord.gg/pywire", // Update this!
      "/github": "https://github.com/pywire/pywire",
    };
    if (redirects[path]) return Response.redirect(redirects[path], 302);

    // --- 2. DEFINE PROXY FUNCTION ---
    // This helper strips the 'Host' header so Pages accepts the request
    async function proxy(targetOrigin, pathOverride) {
      const newUrl = new URL(request.url);
      newUrl.hostname = targetOrigin;

      // Apply path override if provided (for stripping /docs)
      if (pathOverride !== undefined) {
        newUrl.pathname = pathOverride;
      }

      // ⚠️ CRITICAL: Create a clean request to avoid Host header mismatch
      const newRequest = new Request(newUrl, {
        method: request.method,
        headers: request.headers,
        body: request.body,
        redirect: "manual",
      });

      // Force the Host header to match the target origin
      newRequest.headers.set("Host", targetOrigin);

      return fetch(newRequest);
    }

    // --- 3. ROUTE TO DOCS ---
    if (path.startsWith("/docs")) {
      // Strip "/docs" so the origin sees "/_astro/..." or "/"
      const newPath = path.replace(/^\/docs/, "") || "/";
      return proxy(docsTarget, newPath);
    }

    // --- 4. ROUTE TO LANDING ---
    return proxy(landingTarget);
  },
};
