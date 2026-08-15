import { ImageResponse } from "next/og";

export const runtime = "edge";

export async function GET() {
  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#0a0a0b",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        {/* Hexagon mark */}
        <svg
          width="80"
          height="80"
          viewBox="0 0 20 20"
          fill="none"
          style={{ marginBottom: 24 }}
        >
          <path
            d="M10 1L18.5 6.5V15.5L10 21L1.5 15.5V6.5L10 1Z"
            stroke="#e4e4e7"
            strokeWidth="1.5"
            strokeLinejoin="round"
            fill="none"
          />
          <path
            d="M10 1V21M1.5 6.5L18.5 6.5M1.5 15.5L18.5 15.5"
            stroke="#e4e4e7"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>

        <div
          style={{
            fontSize: 48,
            fontWeight: 700,
            color: "#e4e4e7",
            letterSpacing: "-0.02em",
            marginBottom: 8,
          }}
        >
          PredictX
        </div>

        <div
          style={{
            fontSize: 20,
            color: "#71717a",
            maxWidth: 480,
            textAlign: "center",
            lineHeight: 1.4,
          }}
        >
          Decentralized prediction markets. Trade on real-world outcomes.
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
    }
  );
}
