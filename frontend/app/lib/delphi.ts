// SSE client for the orchestrator's POST /chat endpoint.
// /chat is POST + text/event-stream, so we read the ReadableStream manually
// and parse `event:` / `data:` frames.

export type ChatEvent = {
  ev: string | undefined;
  data: any;
};

export async function* chat(
  query: string,
  sources: string[]
): AsyncGenerator<ChatEvent> {
  const sid =
    typeof window !== "undefined"
      ? sessionStorage.getItem("delphi_session_id") || ""
      : "";

  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || "http://localhost:8000";
  const res = await fetch(`${base}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, session_id: sid, sources: sources.join(",") }),
  });

  if (!res.body) throw new Error("No response body from orchestrator");

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() || "";
    for (const f of frames) {
      if (!f.trim()) continue;
      const ev = f.match(/event: (.*)/)?.[1];
      const data = JSON.parse(f.match(/data: (.*)/)?.[1] || "{}");
      if (ev === "session" && typeof window !== "undefined") {
        sessionStorage.setItem("delphi_session_id", data.session_id);
      }
      yield { ev, data };
    }
  }
}
