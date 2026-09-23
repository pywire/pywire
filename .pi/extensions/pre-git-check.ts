// Runs scripts/hooks/pre-git-check.sh before the agent's `git commit` / `git push`
// and blocks the call if the affected packages' checks fail.
import { isToolCallEventType, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const GIT_COMMIT_OR_PUSH = /(^|[;&|(]|\$\()\s*git(\s+-[Cc]\s+\S+)*\s+(commit|push)(\s|$)/;

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    if (!isToolCallEventType("bash", event)) return;
    const { command } = event.input;
    if (!GIT_COMMIT_OR_PUSH.test(command)) return;

    ctx.ui.setStatus("pre-git-check", "Running checks before git commit/push...");
    try {
      const res = await pi.exec(
        "bash",
        ["-c", 'exec bash "$(git rev-parse --show-toplevel)/scripts/hooks/pre-git-check.sh" "$1"', "_", command],
        { cwd: ctx.cwd, timeout: 900_000, signal: ctx.signal },
      );
      if (res.code !== 0) {
        return { block: true, reason: res.stderr.trim() || "pre-git-check failed" };
      }
    } finally {
      ctx.ui.setStatus("pre-git-check", undefined);
    }
  });
}
