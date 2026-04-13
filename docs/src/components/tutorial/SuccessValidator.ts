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
            passed =
              content !== undefined && new RegExp(criterion.pattern || '').test(content)
            break
          }

          case 'browser_route_text': {
            // Check live iframe text content first (captures reactive state from WS updates).
            // Fall back to re-fetching the route via HTTP (only sees initial server-rendered state).
            if (criterion.pattern) {
              const regex = new RegExp(criterion.pattern)

              // First try: live iframe DOM text (includes reactive/interactive state)
              if (liveIframeText && regex.test(liveIframeText)) {
                passed = true
                break
              }

              // Second try: last rendered HTML from HTTP response
              if (browserHtml && regex.test(browserHtml)) {
                passed = true
                break
              }

              // Third try: re-fetch the specific route
              if (criterion.route && fetchRoute) {
                try {
                  const fetched = await fetchRoute(criterion.route)
                  passed = regex.test(fetched || '')
                } catch (e) {
                  console.warn(`Failed to fetch route ${criterion.route}:`, e)
                  passed = false
                }
              }
            }
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
