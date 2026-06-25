import { useEffect, useRef } from "react";

// Per-stock price chart via TradingView's embeddable mini symbol-overview widget, 1-year range.
// Loads from tradingview.com (external) — chosen for the polished, interactive look + live price.
// International tickers may not always resolve on TradingView's symbol database.
export function StockChart({ ticker }: { ticker: string }) {
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
      height: 260,
      locale: "de_DE",
      dateRange: "12M", // 1 year
      colorTheme: "light",
      isTransparent: true,
      autosize: false,
      chartOnly: false, // keep the price + change header
    });
    el.appendChild(script);

    return () => {
      el.innerHTML = "";
    };
  }, [ticker]);

  return (
    <div className="stock-chart">
      <div ref={ref} className="tradingview-widget-container tv-chart" />
    </div>
  );
}
