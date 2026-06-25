import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AreaSeries, ColorType, createChart, type Time } from "lightweight-charts";

import { fetchQuote, type Quote } from "../api";

// --- global chart-style store (so the toggle switches every chart on the page at once) ---
export type ChartStyle = "lightweight" | "tradingview" | "svg";
const KEY = "equity-scout-chart-style";
let current: ChartStyle = "lightweight";
try {
  const saved = localStorage.getItem(KEY);
  if (saved === "lightweight" || saved === "tradingview" || saved === "svg") current = saved;
} catch {
  /* localStorage unavailable — keep default */
}
const listeners = new Set<() => void>();
export function setChartStyle(style: ChartStyle) {
  current = style;
  try {
    localStorage.setItem(KEY, style);
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}
export function useChartStyle(): ChartStyle {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => current,
    () => current,
  );
}

const STYLES: { key: ChartStyle; label: string }[] = [
  { key: "lightweight", label: "TradingView-Lib (lokal)" },
  { key: "tradingview", label: "TradingView-Widget" },
  { key: "svg", label: "Einfach (SVG)" },
];

export function ChartStyleToggle() {
  const active = useChartStyle();
  return (
    <div className="chart-toggle" role="group" aria-label="Chart-Stil wählen">
      <span className="chart-toggle-label">Chart-Stil</span>
      {STYLES.map((s) => (
        <button
          key={s.key}
          className={active === s.key ? "chart-toggle-btn active" : "chart-toggle-btn"}
          onClick={() => setChartStyle(s.key)}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}

function ChartHeader({ quote }: { quote: Quote }) {
  const cls = quote.change_period >= 0 ? "pos" : "neg";
  const sign = quote.change_period >= 0 ? "+" : "";
  return (
    <div className="chart-head">
      <span className="chart-ticker">{quote.ticker}</span>
      <span className="chart-last tnum">{quote.last.toFixed(2)}</span>
      <span className={`chart-change tnum ${cls}`}>
        {sign}
        {quote.change_period.toFixed(1)} % · 6M
      </span>
    </div>
  );
}

function LightweightChart({ quote }: { quote: Quote }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      height: 200,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9b96ad",
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(20,16,50,0.05)" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#7c5cff", // theme --accent (lightweight-charts needs a literal colour)
      topColor: "rgba(124, 92, 255, 0.25)",
      bottomColor: "rgba(124, 92, 255, 0)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(quote.closes.map(([t, value]) => ({ time: t as Time, value })));
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [quote]);
  return <div ref={ref} className="lw-chart" />;
}

function SvgChart({ quote }: { quote: Quote }) {
  const W = 600;
  const H = 200;
  const pad = 6;
  const vals = quote.closes.map((c) => c[1]);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i: number) => (i / Math.max(quote.closes.length - 1, 1)) * W;
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - 2 * pad);
  const line = quote.closes.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(c[1]).toFixed(1)}`).join(" ");
  const gid = `sc-${quote.ticker.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="svg-chart" role="img" aria-label={`Kurs ${quote.ticker}`}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${W},${H} L0,${H} Z`} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function DataChart({ ticker, svg }: { ticker: string; svg: boolean }) {
  const [quote, setQuote] = useState<Quote | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    setQuote(undefined);
    fetchQuote(ticker)
      .then((q) => alive && setQuote(q))
      .catch(() => alive && setQuote(null));
    return () => {
      alive = false;
    };
  }, [ticker]);
  if (quote === undefined) return <div className="chart-state muted">Kurs lädt…</div>;
  if (!quote) return <div className="chart-state muted">Keine Kursdaten für {ticker}.</div>;
  return (
    <div className="stock-chart">
      <ChartHeader quote={quote} />
      {svg ? <SvgChart quote={quote} /> : <LightweightChart quote={quote} />}
    </div>
  );
}

function TradingViewChart({ ticker }: { ticker: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = "";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    el.appendChild(widget);
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js";
    script.async = true;
    script.text = JSON.stringify({
      symbol: ticker,
      width: "100%",
      height: 220,
      locale: "de_DE",
      dateRange: "6M",
      colorTheme: "light",
      isTransparent: true,
      autosize: false,
    });
    el.appendChild(script);
    return () => {
      el.innerHTML = "";
    };
  }, [ticker]);
  return <div ref={ref} className="tradingview-widget-container tv-chart" />;
}

export function StockChart({ ticker }: { ticker: string }) {
  const style = useChartStyle();
  if (style === "tradingview") return <TradingViewChart ticker={ticker} />;
  return <DataChart ticker={ticker} svg={style === "svg"} />;
}
