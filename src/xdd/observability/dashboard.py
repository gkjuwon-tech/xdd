"""Minimal real-time dashboard (FastAPI).

Shows equity, open positions, recent decisions with their natural-language
reasoning, and calibration — plus a kill-switch button. This is the P0
observability surface: every trade's rationale must be visible and auditable.
"""

from __future__ import annotations

import html

from xdd.orchestrator.builder import TradingSystem


def create_app(system: TradingSystem):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="xdd trading agent")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _render(system)

    @app.get("/api/state")
    def state() -> JSONResponse:
        return JSONResponse(_state(system))

    @app.post("/api/kill")
    def kill() -> JSONResponse:
        system.kill_switch.engage("dashboard")
        return JSONResponse({"engaged": True})

    @app.post("/api/release")
    def release() -> JSONResponse:
        system.kill_switch.release()
        return JSONResponse({"engaged": False})

    @app.post("/api/run-cycle")
    def run_cycle() -> JSONResponse:
        report = system.run_cycle()
        return JSONResponse(
            {
                "signals": report.signals_collected,
                "events": report.events_formed,
                "decisions": report.decisions,
                "exits": report.exits,
                "equity": report.equity,
                "halted": report.halted,
            }
        )

    return app


def _state(system: TradingSystem) -> dict:
    snap = system.accountant.snapshot()
    positions = []
    for ticker, pos in snap.positions.items():
        price = snap.prices.get(ticker, pos.avg_price)
        positions.append(
            {
                "ticker": ticker,
                "quantity": round(pos.quantity, 4),
                "avg_price": round(pos.avg_price, 2),
                "price": round(price, 2),
                "pnl_pct": round(pos.unrealized_pnl_pct(price), 4),
            }
        )
    from xdd.risk import CalibrationTracker

    cal = CalibrationTracker(system.repo)
    return {
        "equity": round(snap.equity, 2),
        "cash": round(snap.cash, 2),
        "day_pnl_pct": round(snap.day_pnl_pct, 4),
        "drawdown_pct": round(snap.drawdown_pct, 4),
        "gross_exposure": round(snap.gross_exposure, 4),
        "kill_switch": system.kill_switch.engaged,
        "positions": positions,
        "reliability": cal.reliability(),
        "recent": system.audit.recent(30),
    }


def _render(system: TradingSystem) -> str:
    s = _state(system)
    rows = "".join(
        f"<tr><td>{html.escape(p['ticker'])}</td><td>{p['quantity']}</td>"
        f"<td>{p['avg_price']}</td><td>{p['price']}</td>"
        f"<td class='{'pos' if p['pnl_pct'] >= 0 else 'neg'}'>{p['pnl_pct']:+.2%}</td></tr>"
        for p in s["positions"]
    ) or "<tr><td colspan=5>no open positions</td></tr>"

    decisions = ""
    for r in s["recent"]:
        if r["kind"] not in ("decision", "hypothesis", "fill", "lesson", "liquidation"):
            continue
        payload = r["payload"]
        summary = _summarize(r["kind"], payload)
        decisions += (
            f"<div class='card'><b>{html.escape(r['kind'])}</b> "
            f"<span class='muted'>{html.escape(r['ts'][:19])} "
            f"{html.escape(str(r.get('ticker') or ''))}</span><br>{summary}</div>"
        )

    kill = "ON" if s["kill_switch"] else "off"
    reliability = f"{s['reliability']:.0%}" if s["reliability"] is not None else "n/a"

    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>xdd agent</title><style>
body{{font-family:ui-monospace,monospace;background:#0e1116;color:#d5dae1;margin:0;padding:24px}}
h1{{font-size:18px}} table{{border-collapse:collapse;width:100%;margin:8px 0}}
td,th{{border:1px solid #2a2f3a;padding:6px 10px;text-align:left;font-size:13px}}
.pos{{color:#4ade80}} .neg{{color:#f87171}} .muted{{color:#7a8594;font-size:11px}}
.card{{background:#161b22;border:1px solid #2a2f3a;border-radius:6px;padding:8px 12px;margin:6px 0;font-size:12px}}
.stat{{display:inline-block;background:#161b22;border:1px solid #2a2f3a;border-radius:6px;padding:8px 14px;margin:4px}}
button{{background:#f87171;color:#0e1116;border:0;padding:8px 16px;border-radius:6px;font-weight:bold;cursor:pointer}}
.grid{{display:flex;flex-wrap:wrap;gap:4px}}
</style></head><body>
<h1>xdd — autonomous trading agent</h1>
<div class=grid>
<div class=stat>equity<br><b>{s['equity']:,.0f}</b></div>
<div class=stat>cash<br><b>{s['cash']:,.0f}</b></div>
<div class=stat>day pnl<br><b class='{'pos' if s['day_pnl_pct']>=0 else 'neg'}'>{s['day_pnl_pct']:+.2%}</b></div>
<div class=stat>drawdown<br><b>{s['drawdown_pct']:.2%}</b></div>
<div class=stat>exposure<br><b>{s['gross_exposure']:.0%}</b></div>
<div class=stat>calibration<br><b>{reliability}</b></div>
<div class=stat>kill switch<br><b>{kill}</b></div>
</div>
<h2 style='font-size:14px'>positions</h2>
<table><tr><th>ticker</th><th>qty</th><th>avg</th><th>price</th><th>pnl%</th></tr>{rows}</table>
<h2 style='font-size:14px'>recent decisions & reasoning</h2>
{decisions or '<div class=muted>no activity yet</div>'}
<p><button onclick="fetch('/api/kill',{{method:'POST'}}).then(()=>location.reload())">ENGAGE KILL SWITCH</button>
<button style='background:#4ade80' onclick="fetch('/api/run-cycle',{{method:'POST'}}).then(()=>location.reload())">RUN CYCLE</button></p>
</body></html>"""


def _summarize(kind: str, payload: dict) -> str:
    if kind == "decision":
        reasons = "<br>".join(html.escape(r) for r in payload.get("reasons", []))
        return (
            f"{payload.get('ticker')} → <b>{payload.get('action')}</b> "
            f"({payload.get('status')}, conf {payload.get('effective_confidence')})<br>"
            f"<span class=muted>{reasons}</span>"
        )
    if kind == "hypothesis":
        return (
            f"{payload.get('direction')} conf {payload.get('confidence')} — "
            f"{html.escape(str(payload.get('thesis', '')))}"
        )
    if kind == "fill":
        f = payload.get("fill", {})
        return f"{f.get('side')} {f.get('quantity')} @ {f.get('price')} (pnl {payload.get('realized_pnl')})"
    if kind in ("lesson",):
        return html.escape(str(payload.get("summary", "")))
    if kind == "liquidation":
        return f"{html.escape(str(payload.get('reason', '')))} pnl {payload.get('realized_pnl')}"
    return ""
