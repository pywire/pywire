// How esbuild --define works:
// Format: --define:KEY=VALUE where VALUE is a JavaScript expression
// esbuild evaluates this as JS code at compile time

const wheelFile = "pywire-0.3.0-cp310-abi3-pyodide_2025_0_wasm32.whl";

// CURRENT CODE (PROBLEMATIC):
const defineStr1 = `--define:__PYWIRE_WHEEL_NAME__='"${wheelFile}"'`;
console.log("=== CURRENT CODE (has quote bug) ===");
console.log("Shell command part:", defineStr1);
console.log("\nWhat esbuild sees as the VALUE:");
const valueStr1 = `'"${wheelFile}"'`;
console.log("  " + valueStr1);
console.log("\nThis is interpreted by esbuild as: a JSON string literal with the quotes");
console.log("The actual string value becomes: pywire-...whl with literal quotes in it!");

// FIXED APPROACH 1 - Using JSON.stringify:
const defineStr2 = `--define:__PYWIRE_WHEEL_NAME__=${JSON.stringify(wheelFile)}`;
console.log("\n\n=== FIX OPTION 1: JSON.stringify ===");
console.log("Shell command part:", defineStr2);
console.log("\nWhat esbuild sees as the VALUE:");
const valueStr2 = JSON.stringify(wheelFile);
console.log("  " + valueStr2);
console.log("\nThis is correct: a proper JSON string that esbuild evaluates correctly");

// FIXED APPROACH 2 - Direct string (also works):
const defineStr3 = `--define:__PYWIRE_WHEEL_NAME__="${wheelFile}"`;
console.log("\n\n=== FIX OPTION 2: Direct double quotes ===");
console.log("Shell command part:", defineStr3);
console.log("\nWhat esbuild sees as the VALUE:");
const valueStr3 = `"${wheelFile}"`;
console.log("  " + valueStr3);
console.log("\nThis also works, as long as wheelFile has no quotes in it");

// The root cause explanation:
console.log("\n\n=== ROOT CAUSE ===");
console.log("Current code uses nested quotes: '\"..\"'");
console.log("Shell removes outer quotes, leaves inner: \"...\"");
console.log("esbuild sees the VALUE as: \"pywire-...whl\"");
console.log("But since this is treated as a string in esbuild's expression evaluator,");
console.log("the quotes are LITERAL characters in the final string value!");
