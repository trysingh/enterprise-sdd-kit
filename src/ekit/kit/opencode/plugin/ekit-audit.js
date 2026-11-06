// ekit audit plugin for OpenCode (managed by enterprise-sdd-kit; `ekit sync` rewrites it, do not edit).
//
// Records every tool call the agent makes into the project's action log by running
// `ekit log append --json ...`: tool name, target path, shell command (cut to 500 chars), duration,
// and for write/edit/patch tools the sha256 of the target file before and after. File CONTENTS are
// never logged. Everything is wrapped in try/catch: auditing must never break the agent.
//
// VERIFY BEFORE RELYING ON THIS: the hook names ("tool.execute.before" / "tool.execute.after"), their
// (input, output) shapes (input.tool, input.sessionID, input.callID, output.args) and the plugin
// signature ({ directory }) are assumptions about the OpenCode plugin API. Check them against the
// installed OpenCode version's plugin documentation. `ekit doctor` only checks that this file exists.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";

const WRITERS = /^(write|edit|patch|multiedit|apply_patch)$/i;

export const EkitAudit = async ({ directory }) => {
  process.env.EKIT_ACTOR = "agent";
  const pending = new Map();

  const sha = (p) => {
    try {
      if (!p) return null;
      const full = isAbsolute(p) ? p : resolve(directory, p);
      return createHash("sha256").update(readFileSync(full)).digest("hex");
    } catch {
      return null; // missing file (a new one) or unreadable: no hash
    }
  };

  const argsOf = (output) => (output && output.args) || {};
  const pathOf = (a) => a.filePath ?? a.path ?? null;

  const send = (ev) => {
    try {
      spawnSync("ekit", ["log", "append", "--json", JSON.stringify(ev)], { cwd: directory, stdio: "ignore", timeout: 10000 });
    } catch {
      /* never throw */
    }
  };

  return {
    "tool.execute.before": async (input, output) => {
      try {
        const args = argsOf(output);
        const p = pathOf(args);
        pending.set(input.callID, {
          t0: Date.now(),
          args,
          sha_before: WRITERS.test(String(input.tool)) ? sha(p) : null,
        });
      } catch {
        /* never throw */
      }
    },
    "tool.execute.after": async (input, output) => {
      try {
        const start = pending.get(input.callID) || { t0: Date.now(), args: argsOf(output), sha_before: null };
        pending.delete(input.callID);
        const args = start.args || {};
        const p = pathOf(args);
        const command = typeof args.command === "string" ? args.command.slice(0, 500) : null;
        send({
          kind: "tool.call",
          tool: input.tool,
          session: input.sessionID,
          duration_ms: Date.now() - start.t0,
          path: p,
          command,
          sha_before: start.sha_before,
          sha_after: WRITERS.test(String(input.tool)) ? sha(p) : null,
          outcome: "ok",
        });
      } catch {
        /* never throw */
      }
    },
  };
};
