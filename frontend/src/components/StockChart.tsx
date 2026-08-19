import { useRef, useState } from "react";
import type { MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { getStockChart } from "../api/client";
import { Card } from "./ui/card";

const WIDTH = 640;
const HEIGHT = 180;
const PAD_X = 8;
const PAD_Y = 14;

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
      <Card className="mb-3 px-5 py-4 text-center text-sm text-muted-foreground">Loading price chart...</Card>
    );
  }

  if (isError || !data || data.points.length < 2) {
    return (
      <Card className="mb-3 px-5 py-4 text-center text-sm text-muted-foreground">
        Price chart unavailable for {ticker}.
      </Card>
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
  const color = isUp ? "var(--success)" : "var(--destructive)";

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
    <Card className="mb-3 px-5 py-4">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-semibold text-foreground">{data.ticker} &middot; YTD</span>
        <span className="text-sm font-semibold" style={{ color }}>
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
        className="block cursor-crosshair"
        role="img"
        aria-label={`${data.ticker} year-to-date closing price chart, ${isUp ? "up" : "down"} ${Math.abs(data.changePercent).toFixed(2)} percent`}
      >
        <path d={areaPath} fill={color} fillOpacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hoverCoord && hovered && tooltipBox && (
          <g pointerEvents="none">
            <line x1={hoverCoord[0]} x2={hoverCoord[0]} y1={PAD_Y} y2={HEIGHT - PAD_Y} stroke="var(--input)" strokeWidth={1} />
            <circle cx={hoverCoord[0]} cy={hoverCoord[1]} r={4} fill={color} stroke="var(--card)" strokeWidth={2} />
            <rect x={tooltipBox.x} y={tooltipBox.y} width={tooltipBox.w} height={tooltipBox.h} rx={6} fill="var(--popover)" stroke="var(--input)" strokeWidth={1} />
            <text x={tooltipBox.x + 8} y={tooltipBox.y + 15} fontSize="9" fill="var(--muted-foreground)">
              {hovered.date}
            </text>
            <text x={tooltipBox.x + 8} y={tooltipBox.y + 28} fontSize="12" fontWeight={700} fill="var(--foreground)">
              ${hovered.close.toFixed(2)}
            </text>
          </g>
        )}
      </svg>

      <div className="mt-1.5 flex justify-between text-xs text-muted-foreground">
        <span>{data.points[0].date}</span>
        <span>{data.points[data.points.length - 1].date}</span>
      </div>
    </Card>
  );
}
