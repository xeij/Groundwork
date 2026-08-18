import { useRef, useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { getStockChart } from "../api/client";

const WIDTH = 640;
const HEIGHT = 180;
const PAD_X = 8;
const PAD_Y = 14;

const CARD_STYLE: CSSProperties = {
  border: "1px solid #21262d",
  borderRadius: 10,
  background: "#161b22",
  padding: "1rem 1.25rem",
  marginBottom: "0.75rem",
};

export function StockChart({ ticker }: { ticker: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["stock-chart", ticker],
    queryFn: () => getStockChart(ticker),
    retry: false,
  });
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div style={{ ...CARD_STYLE, color: "#8b949e", fontSize: "0.85rem", textAlign: "center" }}>
        Loading price chart...
      </div>
    );
  }

  if (isError || !data || data.points.length < 2) {
    return (
      <div style={{ ...CARD_STYLE, color: "#8b949e", fontSize: "0.85rem", textAlign: "center" }}>
        Price chart unavailable for {ticker}.
      </div>
    );
  }

  const closes = data.points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const xStep = (WIDTH - PAD_X * 2) / (data.points.length - 1);
  const scaleY = (close: number) => HEIGHT - PAD_Y - ((close - min) / range) * (HEIGHT - PAD_Y * 2);

  const coords = data.points.map((p, i) => [PAD_X + i * xStep, scaleY(p.close)] as const);
  const linePath = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1][0].toFixed(2)},${HEIGHT - PAD_Y} L${coords[0][0].toFixed(2)},${HEIGHT - PAD_Y} Z`;

  const isUp = data.changePercent >= 0;
  const color = isUp ? "#3fb950" : "#f85149";

  function handleMouseMove(e: MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || !data) return;
    const rect = svg.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * WIDTH;
    const index = Math.round((relX - PAD_X) / xStep);
    setHoverIndex(Math.min(Math.max(index, 0), data.points.length - 1));
  }

  const hovered = hoverIndex != null ? data.points[hoverIndex] : null;
  const hoverCoord = hoverIndex != null ? coords[hoverIndex] : null;

  let tooltipBox: { x: number; y: number; w: number; h: number } | null = null;
  if (hoverCoord) {
    const w = 92;
    const h = 36;
    const flip = hoverCoord[0] + 10 + w > WIDTH;
    tooltipBox = {
      x: flip ? hoverCoord[0] - 10 - w : hoverCoord[0] + 10,
      y: Math.min(Math.max(hoverCoord[1] - h / 2, 2), HEIGHT - h - 2),
      w,
      h,
    };
  }

  return (
    <div style={CARD_STYLE}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: "0.95rem", fontWeight: 600, color: "#e6edf3" }}>{data.ticker} &middot; YTD</span>
        <span style={{ fontSize: "0.9rem", fontWeight: 600, color }}>
          {isUp ? "+" : ""}
          {data.changePercent.toFixed(2)}%
        </span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width="100%"
        height={HEIGHT}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIndex(null)}
        style={{ display: "block", cursor: "crosshair" }}
        role="img"
        aria-label={`${data.ticker} year-to-date closing price chart, ${isUp ? "up" : "down"} ${Math.abs(data.changePercent).toFixed(2)} percent`}
      >
        <path d={areaPath} fill={color} fillOpacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hoverCoord && hovered && tooltipBox && (
          <g pointerEvents="none">
            <line x1={hoverCoord[0]} x2={hoverCoord[0]} y1={PAD_Y} y2={HEIGHT - PAD_Y} stroke="#30363d" strokeWidth={1} />
            <circle cx={hoverCoord[0]} cy={hoverCoord[1]} r={4} fill={color} stroke="#161b22" strokeWidth={2} />
            <rect x={tooltipBox.x} y={tooltipBox.y} width={tooltipBox.w} height={tooltipBox.h} rx={6} fill="#0d1117" stroke="#30363d" strokeWidth={1} />
            <text x={tooltipBox.x + 8} y={tooltipBox.y + 15} fontSize="9" fill="#8b949e">
              {hovered.date}
            </text>
            <text x={tooltipBox.x + 8} y={tooltipBox.y + 28} fontSize="12" fontWeight={700} fill="#e6edf3">
              ${hovered.close.toFixed(2)}
            </text>
          </g>
        )}
      </svg>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", color: "#8b949e", marginTop: "0.35rem" }}>
        <span>{data.points[0].date}</span>
        <span>{data.points[data.points.length - 1].date}</span>
      </div>
    </div>
  );
}
