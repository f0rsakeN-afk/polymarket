"use client";

import { curveMonotoneX } from "@visx/curve";
import type { CurveFactory } from "d3-shape";

import { AreaClosed, LinePath } from "@visx/shape";
import { motion } from "motion/react";
import { useCallback, useId, useMemo } from "react";
import { chartCssVars, useChart } from "./chart-context";

export type Momentum = "up" | "down" | "flat";

export interface MomentumColors {
  up: string;
  down: string;
  flat: string;
}

export function detectMomentum(
  data: Record<string, unknown>[],
  dataKey: string,
  lookback = 20
): Momentum {
  if (data.length < 5) {
    return "flat";
  }
  const start = Math.max(0, data.length - lookback);
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (let i = start; i < data.length; i++) {
    const v = data[i]?.[dataKey];
    if (typeof v === "number") {
      if (v < min) {
        min = v;
      }
      if (v > max) {
        max = v;
      }
    }
  }
  const range = max - min;
  if (range === 0) {
    return "flat";
  }
  const tailStart = Math.max(start, data.length - 5);
  const rawFirst = data[tailStart]?.[dataKey];
  const rawLast = data.at(-1)?.[dataKey];
  // A missing sample is a gap, not a zero. Defaulting either end to 0 made the
  // tail look like a crash to zero and flipped the line to the "down" colour.
  if (
    typeof rawFirst !== "number" ||
    !Number.isFinite(rawFirst) ||
    typeof rawLast !== "number" ||
    !Number.isFinite(rawLast)
  ) {
    return "flat";
  }
  const delta = rawLast - rawFirst;
  const threshold = range * 0.12;
  if (delta > threshold) {
    return "up";
  }
  if (delta < -threshold) {
    return "down";
  }
  return "flat";
}

export interface LiveLineProps {
  /** Key in data to use for y values */
  dataKey: string;
  /** Stroke color. Default: var(--chart-line-primary) */
  stroke?: string;
  /** Stroke width. Default: 2 */
  strokeWidth?: number;
  /** Curve function. Default: curveMonotoneX */
  curve?: CurveFactory;
  /** Show gradient fill under the curve. Default: true */
  fill?: boolean;
  /** Show pulsing live dot at the right edge. Default: true */
  pulse?: boolean;
  /** Radius of the live dot. Default: 4 */
  dotSize?: number;
  /** Show value badge pill at the live tip. Default: true */
  badge?: boolean;
  /** Value label formatter for the badge */
  formatValue?: (v: number) => string;
  /**
   * When set, the line/fill color changes based on momentum direction.
   * Overrides `stroke` for the line and fill (dot always uses momentum colors).
   */
  momentumColors?: MomentumColors;
}

LiveLine.displayName = "LiveLine";

export function LiveLine({
  dataKey,
  stroke = chartCssVars.linePrimary,
  strokeWidth = 2,
  curve = curveMonotoneX,
  fill = true,
  pulse = true,
  dotSize = 4,
  badge = true,
  formatValue = (v: number) => v.toFixed(2),
  momentumColors,
}: LiveLineProps) {
  const {
    data,
    xScale,
    yScale,
    innerWidth,
    innerHeight,
    xAccessor,
    lines,
    tooltipData,
  } = useChart();

  const isScrubbing = tooltipData !== null;

  const uid = useId();
  const gradientId = `live-line-grad-${uid}`;
  const areaGradientId = `live-area-grad-${uid}`;
  const fadeId = `live-fade-${uid}`;
  const fadeMaskId = `live-fade-mask-${uid}`;

  const getX = useCallback(
    (d: Record<string, unknown>) => xScale(xAccessor(d)) ?? 0,
    [xScale, xAccessor]
  );

  const getY = useCallback(
    (d: Record<string, unknown>) => {
      const v = d[dataKey];
      // NaN, not 0. A missing value used to fall back to the literal 0, which
      // is a *plotted* y: d3 reads it as a real zero, so the line dove to the
      // top of the plot and the y-domain stretched, and the badge showed 0.00.
      // NaN makes d3 treat the point as a gap instead - an honest "no data".
      return typeof v === "number" && Number.isFinite(v) ? yScale(v) : Number.NaN;
    },
    [dataKey, yScale]
  );

  // The second-to-last point is the "now" position (live tip).
  // The last point is the queued future point for the fade-out zone.
  const nowPoint = data.length >= 2 ? data.at(-2) : data.at(-1);
  const rawLive = nowPoint?.[dataKey];
  // null rather than 0: a tip with no value has no marker to draw, and
  // defaulting it to 0 printed a "0.00" badge and pinned the guide line to the
  // floor for a market that simply had no fresh sample.
  const liveValue =
    typeof rawLive === "number" && Number.isFinite(rawLive) ? rawLive : null;

  const liveDotX = nowPoint ? (xScale(xAccessor(nowPoint)) ?? 0) : innerWidth;
  const liveDotY = liveValue === null ? Number.NaN : yScale(liveValue);
  const hasLiveMarker = liveValue !== null && Number.isFinite(liveDotY);

  const momentum = useMemo(
    () => detectMomentum(data, dataKey),
    [data, dataKey]
  );

  const defaultMomentumColors: MomentumColors = {
    up: "var(--chart-1)",
    down: "var(--chart-5)",
    flat: stroke,
  };
  const dotMomentumColors = momentumColors ?? defaultMomentumColors;
  const dotColor = dotMomentumColors[momentum];

  // Find the line config for this dataKey to get the resolved stroke
  const lineConfig = lines.find((l) => l.dataKey === dataKey);
  const baseStroke = lineConfig?.stroke ?? stroke;
  const resolvedStroke = momentumColors ? momentumColors[momentum] : baseStroke;

  return (
    <>
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={resolvedStroke} stopOpacity={1} />
          <stop offset="100%" stopColor={resolvedStroke} stopOpacity={0.6} />
        </linearGradient>
        <linearGradient id={areaGradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={resolvedStroke} stopOpacity={0.1} />
          <stop offset="100%" stopColor={resolvedStroke} stopOpacity={0} />
        </linearGradient>
        <linearGradient id={fadeId} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="white" stopOpacity={0} />
          <stop offset="4%" stopColor="white" stopOpacity={1} />
          {liveDotX < innerWidth - 1 ? (
            <>
              <stop
                offset={`${(liveDotX / innerWidth) * 100}%`}
                stopColor="white"
                stopOpacity={1}
              />
              <stop offset="100%" stopColor="white" stopOpacity={0} />
            </>
          ) : (
            <stop offset="100%" stopColor="white" stopOpacity={1} />
          )}
        </linearGradient>
        <mask id={fadeMaskId}>
          <rect
            fill={`url(#${fadeId})`}
            height={innerHeight + 40}
            width={innerWidth}
            x={0}
            y={-20}
          />
        </mask>
      </defs>

      {/* Area fill */}
      {fill && data.length > 1 && (
        <g mask={`url(#${fadeMaskId})`}>
          <AreaClosed
            curve={curve}
            data={data}
            fill={`url(#${areaGradientId})`}
            strokeWidth={0}
            x={getX}
            y={getY}
            yScale={yScale}
          />
        </g>
      )}

      {/* Line */}
      {data.length > 1 && (
        <g mask={`url(#${fadeMaskId})`}>
          <LinePath
            curve={curve}
            data={data}
            stroke={`url(#${gradientId})`}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={strokeWidth}
            x={getX}
            y={getY}
          />
        </g>
      )}

      {/* Dashed horizontal line at current value */}
      {hasLiveMarker && (
        <line
          opacity={0.25}
          stroke={resolvedStroke}
          strokeDasharray="4,4"
          strokeWidth={1}
          x1={0}
          x2={innerWidth}
          y1={liveDotY}
          y2={liveDotY}
        />
      )}

      {/* Live indicator (dot + badge) • dims when crosshair is active */}
      <motion.g
        animate={{ opacity: isScrubbing ? 0.25 : 1 }}
        transition={{ duration: 0.3, ease: "easeInOut" }}
      >
        {/* Pulsing dot */}
        <g>
          {pulse && hasLiveMarker && (
            <circle
              cx={liveDotX}
              cy={liveDotY}
              fill="none"
              opacity={0.4}
              r={dotSize * 2}
              stroke={dotColor}
              strokeWidth={1.5}
            >
              <animate
                attributeName="r"
                dur="1.5s"
                from={String(dotSize)}
                repeatCount="indefinite"
                to={String(dotSize * 3.5)}
              />
              <animate
                attributeName="opacity"
                dur="1.5s"
                from="0.5"
                repeatCount="indefinite"
                to="0"
              />
            </circle>
          )}
          {hasLiveMarker && (
            <>
              <circle
                cx={liveDotX}
                cy={liveDotY}
                fill={dotColor}
                opacity={0.1}
                r={dotSize + 2}
              />
              <circle
                cx={liveDotX}
                cy={liveDotY}
                fill={dotColor}
                r={dotSize}
                stroke={chartCssVars.background}
                strokeWidth={2}
              />
            </>
          )}
        </g>

        {/* Badge • use popover vars so text is never white-on-white */}
        {badge && hasLiveMarker && liveValue !== null && (
          <g transform={`translate(${liveDotX + 12},${liveDotY})`}>
            <rect
              fill="var(--popover)"
              height={24}
              opacity={0.95}
              rx={6}
              width={formatValue(liveValue).length * 7.5 + 16}
              x={0}
              y={-12}
            />
            <text
              fill="var(--popover-foreground)"
              fontFamily="SF Mono, Menlo, Monaco, monospace"
              fontSize={11}
              fontWeight={500}
              x={8}
              y={4}
            >
              {formatValue(liveValue)}
            </text>
          </g>
        )}
      </motion.g>
    </>
  );
}

export default LiveLine;
