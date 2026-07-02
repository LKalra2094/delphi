"use client";

import { useEffect, useRef, useState } from "react";
import { chat } from "./lib/delphi";

type Msg = { role: "user" | "assistant"; text: string };

const SOURCES = ["NEWS", "REVIEWS_A", "REVIEWS_B"];
const STATUS_LABELS: Record<string, string> = {
  classifying: "Classifying domain…",
  routing: "Routing to agents…",
  agents_working: "Agents working in parallel…",
};

export default function Page() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [enabled, setEnabled] = useState<string[]>([...SOURCES]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, status]);

  function toggle(src: string) {
    setEnabled((cur) =>
      cur.includes(src) ? cur.filter((s) => s !== src) : [...cur, src]
    );
  }

  async function send() {
    const query = input.trim();
    if (!query || busy) return;
    setInput("");
    setBusy(true);
    setStatus("");
    setMessages((m) => [...m, { role: "user", text: query }]);

    // placeholder assistant bubble we stream into
    let assistantIndex = -1;
    setMessages((m) => {
      assistantIndex = m.length;
      return [...m, { role: "assistant", text: "" }];
    });

    try {
      for await (const { ev, data } of chat(query, enabled)) {
        if (ev === "status") {
          setStatus(STATUS_LABELS[data.stage] || data.stage || "");
        } else if (ev === "token") {
          setStatus("");
          setMessages((m) => {
            const copy = [...m];
            const last = copy.length - 1;
            copy[last] = { role: "assistant", text: copy[last].text + data.text };
            return copy;
          });
        } else if (ev === "done") {
          setStatus("");
          if (data.final_answer) {
            setMessages((m) => {
              const copy = [...m];
              const last = copy.length - 1;
              copy[last] = { role: "assistant", text: data.final_answer };
              return copy;
            });
          }
        } else if (ev === "error") {
          setMessages((m) => {
            const copy = [...m];
            const last = copy.length - 1;
            copy[last] = {
              role: "assistant",
              text: `⚠️ ${data.message || "Something went wrong."}`,
            };
            return copy;
          });
        }
      }
    } catch (e: any) {
      setMessages((m) => {
        const copy = [...m];
        const last = copy.length - 1;
        copy[last] = {
          role: "assistant",
          text: `⚠️ Could not reach the orchestrator (${e?.message || e}).`,
        };
        return copy;
      });
    } finally {
      setStatus("");
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <div className="header">
        <h1>Delphi</h1>
        <p>
          Multi-agent customer-intelligence. Ask a question; Delphi federates
          NEWS, store reviews, and survey feedback into one grounded answer.
        </p>
        <div className="toggles">
          {SOURCES.map((s) => (
            <label key={s}>
              <input
                type="checkbox"
                checked={enabled.includes(s)}
                onChange={() => toggle(s)}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      <div className="messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            Try: “What are customers saying about checkout this week?”
            <br />
            or “Any recent news about competitor delivery, and does it match our
            reviews?”
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.text || (m.role === "assistant" && busy ? "…" : "")}
          </div>
        ))}
        {status && <div className="status">{status}</div>}
      </div>

      <div className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask Delphi about customer feedback…"
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
