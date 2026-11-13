import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Mistral } from "@mistralai/mistralai";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT ?? 3000);
const MODEL = "mistral-small-latest";

if (!process.env.MISTRAL_API_KEY) {
  console.error("Fehlt: MISTRAL_API_KEY ist nicht gesetzt (z. B. via .env oder Umgebungsvariable).");
  process.exit(1);
}

const client = new Mistral({ apiKey: process.env.MISTRAL_API_KEY });

type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf-8");
}

const server = createServer(async (req, res) => {
  if (req.method === "GET" && (req.url === "/" || req.url === "/index.html")) {
    const html = await readFile(join(__dirname, "..", "public", "index.html"), "utf-8");
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(html);
    return;
  }

  if (req.method === "POST" && req.url === "/api/chat") {
    try {
      const payload = JSON.parse(await readBody(req)) as { messages?: ChatMessage[] };
      const messages = payload.messages;
      if (!Array.isArray(messages) || messages.length === 0) {
        sendJson(res, 400, { error: "messages fehlt oder ist leer." });
        return;
      }
      const completion = await client.chat.complete({ model: MODEL, messages });
      const reply = completion.choices[0]?.message?.content ?? "";
      sendJson(res, 200, { reply });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unbekannter Fehler";
      sendJson(res, 500, { error: message });
    }
    return;
  }

  sendJson(res, 404, { error: "Not found" });
});

server.listen(PORT, () => {
  console.log(`Chat-App läuft auf http://localhost:${PORT} (Modell: ${MODEL})`);
});
