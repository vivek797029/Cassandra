// ARGUS Copilot — React shell (Phase-2 frontend; the Phase-1 working UI is frontend/static/).
// Screens: Chat (default) · Forecast Board · EWI Wall · Policy Studio (tabs).
import { useEffect, useRef, useState } from "react";
import { ask, getForecasts, getEwi, getAlerts, AskResponse, Forecast, Alert } from "./api";
import { AnswerCard } from "./components/AnswerCard";
import { ForecastBoard } from "./components/ForecastBoard";
import { PolicyStudio } from "./screens/PolicyStudio";

type Msg = { role: "user" | "bot"; text?: string; resp?: AskResponse };
const TABS = ["Chat", "Forecast Board", "Policy Studio", "EWI Wall"] as const;

export default function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Chat");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [persona, setPersona] = useState("analyst");
  const [forecasts, setForecasts] = useState<Forecast[]>([]);
  const [ewi, setEwi] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const sid = useRef<string | undefined>(undefined);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => { getForecasts().then(setForecasts); getEwi().then(setEwi); }, []);
  useEffect(() => {                                   // Task 64: live alert wall (<10s)
    if (tab !== "EWI Wall") return;
    let stop = false;
    const poll = () => getAlerts().then(r => !stop && setAlerts(r.alerts)).catch(() => {});
    poll();
    const t = window.setInterval(poll, 5000);
    return () => { stop = true; window.clearInterval(t); };
  }, [tab]);
  useEffect(() => { logRef.current?.scrollTo(0, logRef.current.scrollHeight); }, [msgs]);

  async function send(text?: string) {
    const t = (text ?? q).trim();
    if (!t || busy) return;
    setQ(""); setBusy(true);
    setMsgs(m => [...m, { role: "user", text: t }]);
    try {
      const r = await ask(t, persona, sid.current);
      sid.current = r.session_id;
      setMsgs(m => [...m, { role: "bot", resp: r }]);
    } catch (e) {
      setMsgs(m => [...m, { role: "bot", text: `engine error: ${e}` }]);
    } finally { setBusy(false); }
  }

  return (
    <div className="app">
      <header>
        <h1>ARGUS COPILOT</h1>
        <nav>{TABS.map(t =>
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
        </nav>
        <select value={persona} onChange={e => setPersona(e.target.value)}>
          {["analyst", "principal", "planner", "watch"].map(p => <option key={p}>{p}</option>)}
        </select>
      </header>

      {tab === "Chat" && (
        <main className="chat">
          <div className="log" ref={logRef}>
            {msgs.map((m, i) => m.role === "user"
              ? <div key={i} className="msg user">{m.text}</div>
              : <AnswerCard key={i} resp={m.resp} fallback={m.text} />)}
          </div>
          <div className="composer">
            <input value={q} onChange={e => setQ(e.target.value)}
                   onKeyDown={e => e.key === "Enter" && send()}
                   placeholder="Ask: forecasts, why, what-if, policy, early warnings…" />
            <button disabled={busy} onClick={() => send()}>{busy ? "…" : "Ask"}</button>
          </div>
        </main>
      )}
      {tab === "Forecast Board" && <ForecastBoard forecasts={forecasts} />}
      {tab === "Policy Studio" && <PolicyStudio />}
      {tab === "EWI Wall" && (
        <main className="ewi">
          {alerts.length > 0 && (
            <section className="card alerts">
              <h2>ACTIVE ALERTS ({alerts.length})</h2>
              {alerts.map((a, i) => (
                <div key={i} className={`ewi-card alert-${a.severity}`}>
                  <b>{a.indicator}</b> <span className={`chip ${a.severity === "critical"
                    ? "FRAGILE" : "SENSITIVE"}`}>{a.severity}</span>
                  <span>{a.message}</span>
                  <span className="mut">observed {String(a.value)} (threshold {String(a.threshold)})
                    · {new Date(a.fired_at * 1000).toISOString().slice(0, 16)}Z</span>
                </div>))}
            </section>
          )}
          {ewi.map((e, i) => (
            <div className="ewi-card" key={i}>
              <b>{e.indicator}</b>
              <span>{e.metric}</span>
              <span>threshold {e.threshold} · lead {e.lead_time} · {e.confidence}</span>
            </div>))}
        </main>
      )}
    </div>
  );
}
