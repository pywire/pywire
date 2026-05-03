import type { SuccessCriteria } from './types'

export interface ValidationResult {
  passed: boolean
  description?: string
}

export class SuccessValidator {
  /**
   * Validates a set of success criteria against the current state.
   * @returns Array of validation results corresponding to the criteria order
   */
  static async validate(
    files: Record<string, string>,
    criteria: SuccessCriteria[],
    browserHtml?: string,
    fetchRoute?: (path: string) => Promise<string>,
    liveIframeText?: string,
    visitedRoutes?: Set<string>,
  ): Promise<ValidationResult[]> {
    if (!criteria || criteria.length === 0) return []

    const results: ValidationResult[] = []

    for (const criterion of criteria) {
      try {
        let passed = false
        switch (criterion.type) {
          case 'file_exists': {
            passed = criterion.target ? files[criterion.target] !== undefined : false
            break
          }

          case 'file_contains': {
            const content = files[criterion.target || '']
            // Patterns are literal substrings: tutorial copy uses ``$if=``,
            // ``{props.text}``, etc. ``$`` and ``{`` are regex metacharacters
            // and a regex engine silently turns "$if={show}" into an anchor
            // that never matches. Substring matching is what the docs imply.
            passed =
              content !== undefined && !!criterion.pattern && content.includes(criterion.pattern)
            break
          }

          case 'browser_route_text': {
            // Live iframe text first (reactive state); fall back to last
            // server HTML, then a re-fetch of the criterion's route.
            if (criterion.pattern) {
              const needle = criterion.pattern

              if (liveIframeText && liveIframeText.includes(needle)) {
                passed = true
                break
              }

              if (browserHtml && browserHtml.includes(needle)) {
                passed = true
                break
              }

              if (criterion.route && fetchRoute) {
                try {
                  const fetched = await fetchRoute(criterion.route)
                  passed = !!fetched && fetched.includes(needle)
                } catch (e) {
                  console.warn(`Failed to fetch route ${criterion.route}:`, e)
                  passed = false
                }
              }
            }
            break
          }

          case 'route_visited': {
            // User must have actually navigated to this route inside the
            // preview iframe. Used for "Click X to go to /Y" steps where
            // a content-based check (browser_route_text) would always
            // pass on load because fetchRoute returns the page content
            // for any route — even routes the user never visited.
            passed = !!criterion.route && !!visitedRoutes?.has(criterion.route)
            break
          }

          case 'browser_element': {
            if (browserHtml && criterion.target) {
              const parser = new DOMParser()
              const doc = parser.parseFromString(browserHtml, 'text/html')
              passed = doc.querySelector(criterion.target) !== null
            }
            break
          }

          default:
            passed = false
        }

        results.push({
          passed,
          description: criterion.description,
        })
      } catch (e) {
        console.warn('Validation error:', e)
        results.push({ passed: false, description: criterion.description })
      }
    }
    return results
  }
}
