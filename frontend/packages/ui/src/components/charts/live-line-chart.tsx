"use client";

import { localPoint } from "@visx/event";
import { ParentSize } from "@visx/responsive";
import { scaleLinear, scaleTime } from "@visx/scale";
import { bisector } from "d3-array";
import {
  Children,
  isValidElement,
  memo,
  type ReactElement,
  type ReactNode,
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@workspace/ui/lib/utils";
import {
  isClipExcludedComponent,
  isUnderlayComponent,
} from "./chart-child-passthrough";
import {
  ChartProvider,
  type LineConfig,
  type Margin,
  type TooltipData,
} from "./chart-context";
import { hmsTimeFmt } from "./chart-formatters";
import { DEFAULT_CHART_LIFECYCLE } from "./chart-phase";
import type { LiveLineProps } from "./live-line";
import { extractReferenceAreaConfigs } from "./reference-area-config";
import { wrapSingleYScale } from "./y-axis-scales";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LiveLinePoint {
  time: number;
  /** Primary value (used when only one line is needed) */
  value: number;
  /** YES price — use as dataKey="yes_price" for green line */
  yes_price?: number;
  /** NO price — use as dataKey="no_price" for red line */
  no_price?: number;
  /** Multi-outcome prices keyed by outcome name */
  [key: string]: number | string | undefined;
}

export interface LiveLineChartProps {
  /** Streaming data */
  data: LiveLinePoint[];
  /** Latest value for the primary line (smoothly interpolated) */
  value: number;
  /** Latest value for the secondary line (smoothly interpolated). When provided, enables dual-line mode. */
  valueNo?: number;
  /** Key used for the primary value field. Default: "value" */
  dataKey?: string;
  /** Visible time window in seconds. Default: 30 */
  window?: number;
  /** Number of X-axis ticks. Default: 5 */
  numXTicks?: number;
  /** Leading offset in X-tick units (0 = now at right edge). Default: 0 */
  nowOffsetUnits?: number;
  /** Tight Y-axis. Default: false */
  exaggerate?: boolean;
  /** Interpolation speed (0–1). Default: 0.08 */
  lerpSpeed?: number;
  /** Chart height in pixels. Default: 300 */
  height?: number;
  /** Chart margins */
  margin?: Partial<Margin>;
  /** Freeze chart scrolling. Default: false */
  paused?: boolean;
  /** Enable multi-outcome mode (3+ outcomes). Default: false */
  multiOutcome?: boolean;
  /** Child components (LiveLine, Grid, ChartTooltip, LiveXAxis, LiveYAxis, etc.) */
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LERP_SPEED = 0.08;
const DEFAULT_MARGIN: Margin = { top: 24, right: 16, bottom: 32, left: 16 };
/** React commit interval for the live animation loop (~30fps). */
const LIVE_FRAME_COMMIT_MS = 32;

interface AnimFrame {
  now: number;
  yMin: number;
  yMax: number;
  displayValue: number;
  displayValueNo?: number;
}

function numericValues(d: LiveLinePoint): number[] {
  const vals: number[] = [d.value];
  if (d.yes_price != null) vals.push(d.yes_price);
  if (d.no_price != null) vals.push(d.no_price);
  for (const [k, v] of Object.entries(d)) {
    if (k !== "time" && k !== "value" && k !== "yes_price" && k !== "no_price" && typeof v === "number") {
      vals.push(v);
    }
  }
  return vals;
}

function computeTargetRange(
  data: LiveLinePoint[],
  value: number,
  valueNo: number | undefined,
  exaggerate: boolean
) {
  if (data.length === 0) {
    return { yMin: 0, yMax: 100 };
  }
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const d of data) {
    for (const v of numericValues(d)) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  if (value < min) min = value;
  if (value > max) max = value;
  if (valueNo !== undefined) {
    if (valueNo < min) min = valueNo;
    if (valueNo > max) max = valueNo;
  }
  const rawRange = max - min;
  const paddingFactor = exaggerate ? 0.03 : 0.15;
  const rangePad = rawRange * paddingFactor || (exaggerate ? 0.04 : 10);
  return { yMin: min - rangePad, yMax: max + rangePad };
}

function nextAnimFrame(
  prev: AnimFrame,
  targetRange: { yMin: number; yMax: number },
  targetValue: number,
  targetValueNo: number | undefined,
  speed: number,
  isPaused: boolean
): AnimFrame {
  const nextNow = isPaused ? prev.now : Date.now();
  const nextYMin =
    targetRange.yMin < prev.yMin
      ? targetRange.yMin
      : prev.yMin + (targetRange.yMin - prev.yMin) * speed;
  const nextYMax =
    targetRange.yMax > prev.yMax
      ? targetRange.yMax
      : prev.yMax + (targetRange.yMax - prev.yMax) * speed;
  const nextValue =
    prev.displayValue + (targetValue - prev.displayValue) * speed;
  const nextValueNo =
    targetValueNo !== undefined
      ? prev.displayValueNo !== undefined
        ? prev.displayValueNo + (targetValueNo - prev.displayValueNo) * speed
        : targetValueNo
      : undefined;
  return {
    now: nextNow,
    yMin: nextYMin,
    yMax: nextYMax,
    displayValue: nextValue,
    displayValueNo: nextValueNo,
  };
}

function interpolateAtTime(
  points: LiveLinePoint[],
  timeSec: number
): number | null {
  if (points.length === 0) return null;
  const firstPt = points[0] as LiveLinePoint;
  const lastPt = points.at(-1) as LiveLinePoint;
  if (timeSec <= firstPt.time) return firstPt.value;
  if (timeSec >= lastPt.time) return lastPt.value;
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    const midPt = points[mid];
    if (midPt && midPt.time <= timeSec) lo = mid;
    else hi = mid;
  }
  const p1 = points[lo];
  const p2 = points[hi];
  if (!p1 || !p2) return null;
  const dt = p2.time - p1.time;
  if (dt === 0) return p1.value;
  const t = (timeSec - p1.time) / dt;
  return p1.value + (p2.value - p1.value) * t;
}

const bisectTime = bisector<LiveLinePoint, number>((d) => d.time).left;

function extractLiveLineConfigs(children: ReactNode): LineConfig[] {
  const configs: LineConfig[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const childType = child.type as { displayName?: string; name?: string };
    const name =
      typeof child.type === "function"
        ? childType.displayName || childType.name || ""
        : "";
    const props = child.props as LiveLineProps | undefined;
    if (
      (name === "LiveLine" || (props && "dataKey" in props)) &&
      props?.dataKey
    ) {
      configs.push({
        dataKey: props.dataKey,
        stroke: props.stroke || "var(--chart-line-primary)",
        strokeWidth: props.strokeWidth || 2,
      });
    }
  });
  return configs;
}

// ---------------------------------------------------------------------------
// Inner chart
// ---------------------------------------------------------------------------

function liveTooltipKey(
  tooltip: TooltipData | null,
  dataKey: string
): string | null {
  if (!tooltip) return null;
  return `${Math.round(tooltip.x)}:${Math.round(tooltip.yPositions[dataKey] ?? 0)}`;
}

function resolveLiveTooltip(
  cursorX: number | null,
  innerWidth: number,
  innerHeight: number,
  frame: AnimFrame,
  leadingMs: number,
  windowMs: number,
  xTickUnitMs: number,
  data: LiveLinePoint[],
  dataKey: string
): TooltipData | null {
  if (cursorX === null || innerWidth <= 0 || innerHeight <= 0) return null;

  const domainEndMs = frame.now + leadingMs;
  const xScaleNext = scaleTime({
    domain: [new Date(domainEndMs - windowMs), new Date(domainEndMs)],
    range: [0, innerWidth],
  });
  const yScaleNext = scaleLinear({
    domain: [frame.yMin, frame.yMax],
    range: [innerHeight, 0],
    nice: true,
  });
  const timeMs = xScaleNext.invert(cursorX).getTime();
  const timeSec = timeMs / 1000;
  const visible = data.filter((p) => p.time >= (domainEndMs - windowMs) / 1000);
  visible.push({ time: frame.now / 1000, value: frame.displayValue });
  visible.push({
    time: (frame.now + xTickUnitMs) / 1000,
    value: frame.displayValue,
  });
  const val = interpolateAtTime(visible, timeSec);
  if (val === null) return null;

  return {
    point: { date: new Date(timeMs), [dataKey]: val },
    index: 0,
    x: cursorX,
    yPositions: { [dataKey]: yScaleNext(val) ?? 0 },
  };
}

function shouldCommitLiveUpdates(
  now: number,
  lastFrameCommit: number,
  tooltipKey: string | null,
  lastTooltipKey: string | null
): { commitFrame: boolean; commitTooltip: boolean } {
  const commitFrame = now - lastFrameCommit >= LIVE_FRAME_COMMIT_MS;
  const commitTooltip = tooltipKey !== lastTooltipKey;
  return { commitFrame, commitTooltip };
}

interface InnerProps {
  data: LiveLinePoint[];
  value: number;
  valueNo?: number;
  dataKey: string;
  windowSecs: number;
  numXTicks: number;
  nowOffsetUnits: number;
  exaggerate: boolean;
  lerpSpeed: number;
  margin: Margin;
  paused: boolean;
  width: number;
  height: number;
  containerRef: React.RefObject<HTMLDivElement | null>;
  children: ReactNode;
}

function LiveLineChartInner(props: InnerProps) {
  const { width, height, margin } = props;
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  if (innerWidth <= 0 || innerHeight <= 0) return null;
  return <LiveLineChartCore {...props} />;
}

const LiveLineChartCore = memo(function LiveLineChartCore({
  data,
  value,
  valueNo,
  dataKey,
  windowSecs,
  numXTicks,
  nowOffsetUnits,
  exaggerate,
  lerpSpeed,
  margin,
  paused,
  width,
  height,
  containerRef,
  children,
}: InnerProps) {
  const windowMs = windowSecs * 1000;
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  // ---- Animation state ----
  const animRef = useRef<AnimFrame>({
    now: Date.now(),
    yMin: 0,
    yMax: 100,
    displayValue: value,
    displayValueNo: valueNo,
  });
  const [frame, setFrame] = useState<AnimFrame>({
    now: Date.now(),
    yMin: 0,
    yMax: 100,
    displayValue: value,
    displayValueNo: valueNo,
  });

  const pausedRef = useRef(paused);
  const dataRef = useRef(data);
  const dataKeyRef = useRef(dataKey);
  dataRef.current = data;
  dataKeyRef.current = dataKey;

  useEffect(() => { pausedRef.current = paused; }, [paused]);

  const targetRange = useMemo(
    () => computeTargetRange(data, value, valueNo, exaggerate),
    [data, value, valueNo, exaggerate]
  );

  const lines = useMemo(() => extractLiveLineConfigs(children), [children]);

  const xTickUnitMs = windowMs / (numXTicks - 1);
  const leadingMs = nowOffsetUnits * xTickUnitMs;

  // ---- rAF loop ----
  const cursorXRef = useRef<number | null>(null);
  const [tooltipData, setTooltipData] = useState<TooltipData | null>(null);
  const lastFrameCommitRef = useRef(0);
  const lastTooltipKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let raf: number;
    const tick = () => {
      const next = nextAnimFrame(
        animRef.current,
        targetRange,
        value,
        valueNo,
        lerpSpeed,
        pausedRef.current
      );
      animRef.current = next;

      const nextTooltip = resolveLiveTooltip(
        cursorXRef.current,
        innerWidth,
        innerHeight,
        next,
        leadingMs,
        windowMs,
        xTickUnitMs,
        dataRef.current,
        dataKeyRef.current
      );
      const now = performance.now();
      const tooltipKey = liveTooltipKey(nextTooltip, dataKeyRef.current);
      const { commitFrame, commitTooltip } = shouldCommitLiveUpdates(
        now,
        lastFrameCommitRef.current,
        tooltipKey,
        lastTooltipKeyRef.current
      );

      if (!(commitFrame || commitTooltip)) {
        raf = requestAnimationFrame(tick);
        return;
      }

      if (commitFrame) lastFrameCommitRef.current = now;
      if (commitTooltip) lastTooltipKeyRef.current = tooltipKey;

      startTransition(() => {
        if (commitFrame) setFrame(next);
        if (commitTooltip) setTooltipData(nextTooltip);
      });

      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [
    targetRange,
    value,
    valueNo,
    lerpSpeed,
    leadingMs,
    windowMs,
    xTickUnitMs,
    innerWidth,
    innerHeight,
  ]);

  const domainEndMs = frame.now + leadingMs;

  // ---- Scales ----
  const xScale = useMemo(
    () =>
      scaleTime({
        domain: [new Date(domainEndMs - windowMs), new Date(domainEndMs)],
        range: [0, innerWidth],
      }),
    [domainEndMs, windowMs, innerWidth]
  );

  const yScale = useMemo(
    () =>
      scaleLinear({
        domain: [frame.yMin, frame.yMax],
        range: [innerHeight, 0],
        nice: true,
      }),
    [frame.yMin, frame.yMax, innerHeight]
  );

  // ---- Build context-compatible data (supports dual-line via yes_price/no_price) ----
  const contextData = useMemo(() => {
    const windowStart = domainEndMs - windowMs;
    let startIdx = bisectTime(data, windowStart / 1000, 0);
    if (startIdx > 0) startIdx--;
    const sliced = data.slice(startIdx);
    const records: Record<string, unknown>[] = sliced.map((p) => ({
      date: new Date(p.time * 1000),
      [dataKey]: p.value,
      ...(p.yes_price !== undefined ? { yes_price: p.yes_price } : {}),
      ...(p.no_price !== undefined ? { no_price: p.no_price } : {}),
    }));
    // Virtual "now" point
    records.push({
      date: new Date(frame.now),
      [dataKey]: frame.displayValue,
      ...(frame.displayValueNo !== undefined ? { yes_price: frame.displayValue, no_price: frame.displayValueNo } : {}),
    });
    // Virtual "+1 unit" point
    records.push({
      date: new Date(frame.now + xTickUnitMs),
      [dataKey]: frame.displayValue,
      ...(frame.displayValueNo !== undefined ? { yes_price: frame.displayValue, no_price: frame.displayValueNo } : {}),
    });
    return records;
  }, [
    data,
    frame.now,
    frame.displayValue,
    frame.displayValueNo,
    domainEndMs,
    windowMs,
    dataKey,
    xTickUnitMs,
  ]);

  // ---- X accessor ----
  const xAccessor = useCallback(
    (d: Record<string, unknown>): Date =>
      d.date instanceof Date ? d.date : new Date(d.date as number),
    []
  );

  const handleMouseMove = useCallback(
    (event: React.MouseEvent<SVGGElement>) => {
      const coords = localPoint(event);
      if (!coords) return;
      const x = coords.x - margin.left;
      cursorXRef.current = x >= 0 && x <= innerWidth ? x : null;
    },
    [margin.left, innerWidth]
  );

  const handleMouseLeave = useCallback(() => {
    cursorXRef.current = null;
    lastTooltipKeyRef.current = null;
    setTooltipData(null);
  }, []);

  const dateLabels = useMemo(
    () => contextData.map((d) => hmsTimeFmt.format(xAccessor(d))),
    [contextData, xAccessor]
  );

  const columnWidth = useMemo(() => {
    if (contextData.length < 2) return 0;
    return innerWidth / (contextData.length - 1);
  }, [innerWidth, contextData.length]);

  const clipExcludedChildren: ReactElement[] = [];
  const underlayChildren: ReactElement[] = [];
  const seriesChildren: ReactElement[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    if (isClipExcludedComponent(child)) {
      clipExcludedChildren.push(child);
    } else if (isUnderlayComponent(child)) {
      underlayChildren.push(child);
    } else {
      seriesChildren.push(child);
    }
  });

  const referenceAreas = useMemo(
    () => extractReferenceAreaConfigs(children),
    [children]
  );

  const contextValue = useMemo(
    () => ({
      ...DEFAULT_CHART_LIFECYCLE,
      data: contextData,
      renderData: contextData,
      xScale,
      yScale,
      yScales: wrapSingleYScale(yScale),
      width,
      height,
      innerWidth,
      innerHeight,
      margin,
      columnWidth,
      tooltipData,
      setTooltipData,
      containerRef,
      lines,
      referenceAreas,
      isLoaded: true,
      animationDuration: 0,
      xAccessor,
      dateLabels,
    }),
    [
      contextData,
      xScale,
      yScale,
      width,
      height,
      innerWidth,
      innerHeight,
      margin,
      columnWidth,
      tooltipData,
      containerRef,
      lines,
      referenceAreas,
      xAccessor,
      dateLabels,
    ]
  );

  return (
    <ChartProvider value={contextValue}>
      <svg
        aria-hidden="true"
        className="overflow-visible"
        height={height}
        width={width}
      >
        {/* biome-ignore lint/a11y/noStaticElementInteractions: SVG group for mouse tracking */}
        <g
          onMouseLeave={handleMouseLeave}
          onMouseMove={handleMouseMove}
          style={{ cursor: "crosshair" }}
          transform={`translate(${margin.left},${margin.top})`}
        >
          <rect fill="transparent" height={innerHeight} width={innerWidth} x={0} y={0} />
          {clipExcludedChildren}
          {underlayChildren}
          {seriesChildren}
        </g>
      </svg>
    </ChartProvider>
  );
});

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function LiveLineChart({
  data,
  value,
  valueNo,
  dataKey = "value",
  window: windowSecs = 30,
  numXTicks = 5,
  nowOffsetUnits = 0,
  exaggerate = false,
  lerpSpeed = LERP_SPEED,
  height = 300,
  margin: marginProp,
  paused = false,
  children,
  className,
  style,
}: LiveLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const margin = { ...DEFAULT_MARGIN, ...marginProp };

  return (
    <div
      className={cn("relative w-full", className)}
      ref={containerRef}
      style={{ height, touchAction: "none", ...style }}
    >
      <ParentSize debounceTime={10}>
        {({ width, height }) => (
          <LiveLineChartInner
            containerRef={containerRef}
            data={data}
            dataKey={dataKey}
            exaggerate={exaggerate}
            height={height}
            lerpSpeed={lerpSpeed}
            margin={margin}
            nowOffsetUnits={nowOffsetUnits}
            numXTicks={numXTicks}
            paused={paused}
            value={value}
            valueNo={valueNo}
            width={width}
            windowSecs={windowSecs}
          >
            {children}
          </LiveLineChartInner>
        )}
      </ParentSize>
    </div>
  );
}

export default LiveLineChart;
