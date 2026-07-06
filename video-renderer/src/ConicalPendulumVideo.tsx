import React from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type ConicalPendulumVideoProps = {
  title: string;
  audioSrc: string;
  durationSeconds: number;
  narration: string;
};

const safeText = (value: string, limit = 90) =>
  (value || "")
    .replace(/[^\u4e00-\u9fff0-9＋+×÷=？?，。：“”《》、；;（）() ]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);

export const ConicalPendulumVideo: React.FC<ConicalPendulumVideoProps> = ({
  title,
  audioSrc,
  durationSeconds,
}) => {
  const { fps } = useVideoConfig();
  const totalFrames = Math.max(1, Math.round(durationSeconds * fps));
  return (
    <AbsoluteFill style={{ backgroundColor: "#07111f", fontFamily: '"Noto Sans CJK SC", sans-serif' }}>
      <SceneBackground />
      {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
      <Title text={safeText(title, 20)} />
      <Sequence from={0} durationInFrames={totalFrames}>
        <ConicalPendulum3D />
      </Sequence>
      <FormulaPanel />
    </AbsoluteFill>
  );
};

const SceneBackground: React.FC = () => (
  <AbsoluteFill
    style={{
      background:
        "radial-gradient(circle at 50% 18%, rgba(96,165,250,0.30), transparent 32%), radial-gradient(circle at 50% 78%, rgba(34,197,94,0.18), transparent 26%), linear-gradient(180deg, #07111f 0%, #0f172a 52%, #111827 100%)",
    }}
  />
);

const Title: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: "absolute",
      top: 86,
      left: 72,
      right: 72,
      textAlign: "center",
      color: "white",
      fontSize: 62,
      fontWeight: 900,
      letterSpacing: 2,
    }}
  >
    {text || "圆锥摆运动"}
  </div>
);

const ConicalPendulum3D: React.FC = () => {
  const frame = useCurrentFrame();
  const angle = frame * 4.2;
  const swing = interpolate(Math.sin((frame / 30) * Math.PI * 2), [-1, 1], [-4, 4]);
  const bobX = Math.cos((angle * Math.PI) / 180) * 265;
  const bobZ = Math.sin((angle * Math.PI) / 180) * 92;
  const bobY = 675 + bobZ * 0.25;
  const bobScale = interpolate(bobZ, [-92, 92], [0.86, 1.08]);
  const stringRotate = Math.atan2(bobX, 560) * (180 / Math.PI);
  const stringLength = Math.sqrt(bobX * bobX + 560 * 560);
  const forceOpacity = interpolate(frame, [20, 45], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <AbsoluteFill style={{ perspective: 1200, transformStyle: "preserve-3d" }}>
      <div
        style={{
          position: "absolute",
          left: 540 - 8,
          top: 290,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#e0f2fe",
          boxShadow: "0 0 34px rgba(125,211,252,0.9)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 540,
          top: 300,
          width: 6,
          height: stringLength,
          background: "linear-gradient(180deg, #e0f2fe, #38bdf8)",
          transformOrigin: "top center",
          transform: `rotate(${stringRotate + swing}deg) rotateX(58deg)`,
          borderRadius: 6,
          boxShadow: "0 0 18px rgba(56,189,248,0.5)",
        }}
      />
      <OrbitRing />
      <div
        style={{
          position: "absolute",
          left: 540 + bobX - 72,
          top: bobY - 72,
          width: 144,
          height: 144,
          borderRadius: "50%",
          background: "radial-gradient(circle at 34% 28%, #fde68a 0%, #f97316 44%, #7c2d12 100%)",
          transform: `scale(${bobScale})`,
          boxShadow: `0 ${34 + bobZ * 0.08}px 72px rgba(0,0,0,0.45)`,
        }}
      />
      <ForceArrow label="拉力" x={540 + bobX * 0.55} y={bobY - 230} rotate={-stringRotate - 20} opacity={forceOpacity} />
      <ForceArrow label="重力" x={540 + bobX + 64} y={bobY + 6} rotate={90} opacity={forceOpacity} />
      <ForceArrow label="合力指向圆心" x={540 + bobX * 0.55} y={bobY + 130} rotate={bobX > 0 ? 180 : 0} opacity={forceOpacity} wide />
      <CenterAxis />
    </AbsoluteFill>
  );
};

const OrbitRing: React.FC = () => (
  <div
    style={{
      position: "absolute",
      left: 246,
      top: 650,
      width: 588,
      height: 210,
      border: "6px solid rgba(147,197,253,0.52)",
      borderRadius: "50%",
      transform: "rotateX(68deg)",
      boxShadow: "0 0 42px rgba(59,130,246,0.32)",
    }}
  />
);

const CenterAxis: React.FC = () => (
  <div
    style={{
      position: "absolute",
      left: 536,
      top: 300,
      width: 8,
      height: 695,
      background: "linear-gradient(180deg, rgba(226,232,240,0.65), rgba(226,232,240,0.08))",
      borderRadius: 8,
    }}
  />
);

const ForceArrow: React.FC<{ label: string; x: number; y: number; rotate: number; opacity: number; wide?: boolean }> = ({
  label,
  x,
  y,
  rotate,
  opacity,
  wide,
}) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      opacity,
      transform: `rotate(${rotate}deg)`,
      transformOrigin: "left center",
      display: "flex",
      alignItems: "center",
      gap: 14,
      color: "#f8fafc",
      fontSize: 34,
      fontWeight: 900,
    }}
  >
    <div style={{ width: wide ? 220 : 150, height: 10, borderRadius: 10, background: "#facc15" }} />
    <div
      style={{
        width: 0,
        height: 0,
        borderTop: "18px solid transparent",
        borderBottom: "18px solid transparent",
        borderLeft: "32px solid #facc15",
      }}
    />
    <span style={{ transform: `rotate(${-rotate}deg)`, textShadow: "0 2px 12px rgba(0,0,0,0.5)" }}>{label}</span>
  </div>
);

const FormulaPanel: React.FC = () => (
  <div
    style={{
      position: "absolute",
      left: 82,
      right: 82,
      bottom: 310,
      borderRadius: 34,
      padding: "30px 38px",
      background: "rgba(15,23,42,0.72)",
      border: "2px solid rgba(148,163,184,0.45)",
      color: "white",
      fontSize: 42,
      fontWeight: 850,
      lineHeight: 1.45,
    }}
  >
    <div>竖直方向：拉力竖直分量平衡重力</div>
    <div>水平方向：合力提供向心力</div>
    <div>结论：半径越大或转得越快，需要的向心力越大</div>
  </div>
);

