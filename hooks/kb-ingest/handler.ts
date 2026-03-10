import { execFile } from "child_process";
import { promisify } from "util";
import path from "path";

const execFileAsync = promisify(execFile);

const KB_CHANNEL_ID = "C0AGJ035DGF";
const WORKSPACE = "/root/.openclaw/workspace";
const INGEST_SCRIPT = path.join(WORKSPACE, "kb", "ingest.py");

const URL_REGEX = /https?:\/\/[^\s<>"]+/gi;

const handler = async (event: any) => {
  // Only handle message:received
  if (event.type !== "message" || event.action !== "received") return;

  const ctx = event.context ?? {};

  // Only handle #knowledge-base channel on Slack
  if (ctx.channelId !== "slack") return;
  if (ctx.conversationId !== KB_CHANNEL_ID) return;

  const content: string = ctx.content ?? "";
  const urls = content.match(URL_REGEX);
  if (!urls || urls.length === 0) return;

  for (const url of urls) {
    try {
      const { stdout, stderr } = await execFileAsync("python3", [INGEST_SCRIPT, url], {
        cwd: WORKSPACE,
        timeout: 60_000,
      });

      const output = stdout.trim() || stderr.trim();
      const lastLine = output.split("\n").filter(Boolean).pop() ?? "Done";

      event.messages.push(`📚 KB ingested: ${url}\n${lastLine}`);
    } catch (err: any) {
      const msg = err?.stderr?.trim() || err?.message || String(err);
      event.messages.push(`❌ KB ingest failed for ${url}\n${msg.slice(0, 200)}`);
    }
  }
};

export default handler;
