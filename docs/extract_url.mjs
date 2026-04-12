import fs from 'fs';

const bundledCode = fs.readFileSync('./public/pywire-worker.js', 'utf-8');

// Look for dist/ references
const matches = bundledCode.match(/dist\/[^,\n]+/g);
if (matches) {
  console.log("Found dist/ references:");
  matches.forEach(m => {
    console.log("  " + m);
  });
}

// Look for the specific string pattern where the wheel URL is constructed
// In the original code: const pywireWhlUrl = `${baseUrl}dist/${__PYWIRE_WHEEL_NAME__}`
// This becomes a string concatenation in minified JS

// Try to find patterns that look like wheel filenames with quotes
const quoteMatches = bundledCode.match(/'[^']*\.whl'|"[^"]*\.whl"/g);
if (quoteMatches) {
  console.log("\nFound quoted wheel filenames:");
  quoteMatches.forEach(m => {
    console.log("  " + m);
  });
}

// Look at actual template string or concatenation patterns
const templateMatches = bundledCode.match(/\$\{[^}]+dist[^}]*\}|dist\/\$\{[^}]+\}/g);
if (templateMatches) {
  console.log("\nFound template/concat patterns:");
  templateMatches.forEach(m => {
    console.log("  " + m);
  });
}

// Let's search for where __PYWIRE_WHEEL_NAME__ was inlined
const wheelPattern = bundledCode.match(/pywire[^,\s"]*.whl/g);
if (wheelPattern) {
  console.log("\nWheel filenames found:");
  wheelPattern.forEach(m => {
    console.log("  " + m);
  });
}
