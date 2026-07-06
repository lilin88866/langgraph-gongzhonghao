import React from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

export type ProblemSolving3DClip = {
  start: number;
  end: number;
  visual: string;
  voiceover: string;
  subtitle: string;
  sceneImage?: string | null;
  sceneType?: string;
  scenePhase?: string;
};

export type ProblemSolving3DVideoProps = {
  title: string;
  coverText: string;
  audioSrc: string;
  totalDurationSeconds: number;
  clips: ProblemSolving3DClip[];
};

const fps = 30;
const safeText = (value: string, limit = 80) => {
  const protectedTokens: string[] = [];
  const protectedText = (value || "知识点讲解").replace(
    /mol\/\(L·min\)|mol\/L|rad\/s|mL|min|H2O|CO2|NaCl|NH4Cl|Ba\(OH\)2/g,
    (token) => {
      protectedTokens.push(token);
      return `占位${protectedTokens.length - 1}位占`;
    },
  );
  let cleaned = protectedText
    .replace(/[^\u4e00-\u9fff0-9πvcmtgosTLFqkrNBUEI＋+×÷=＝·./\-^Δθ²³₁₂₃₄₅₆₇₈₉₀°？?，。：“”《》、()（） ]/g, "");
  protectedTokens.forEach((token, index) => {
    cleaned = cleaned.replace(`占位${index}位占`, token);
  });
  return cleaned.replace(/\s+/g, " ").trim().slice(0, limit) || "知识点讲解";
};

export const ProblemSolving3DVideo: React.FC<ProblemSolving3DVideoProps> = ({ title, coverText, audioSrc, clips }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#07111f", fontFamily: '"Noto Sans CJK SC", sans-serif', overflow: "hidden" }}>
      <Background />
      {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
      <Header title={safeText(coverText || title, 18)} />
      {clips.map((clip, index) => {
        const from = Math.max(0, Math.round(clip.start * fps));
        const durationInFrames = Math.max(1, Math.round((clip.end - clip.start) * fps));
        return (
          <Sequence key={`${clip.start}-${index}`} from={from} durationInFrames={durationInFrames}>
            <Scene clip={clip} index={index} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const Background: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        background:
          "radial-gradient(circle at 50% 16%, rgba(96,165,250,0.36), transparent 32%), radial-gradient(circle at 78% 72%, rgba(34,197,94,0.20), transparent 28%), linear-gradient(180deg, #07111f 0%, #0f172a 58%, #111827 100%)",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: -120,
          right: -120,
          bottom: 175,
          height: 520,
          background:
            "linear-gradient(90deg, rgba(56,189,248,0.12) 1px, transparent 1px), linear-gradient(0deg, rgba(56,189,248,0.12) 1px, transparent 1px)",
          backgroundSize: "72px 72px",
          transform: "perspective(900px) rotateX(64deg)",
          transformOrigin: "center bottom",
          borderTop: "2px solid rgba(125,211,252,0.22)",
        }}
      />
    </AbsoluteFill>
  );
};

const Header: React.FC<{ title: string }> = ({ title }) => {
  return (
    <div
      style={{
        position: "absolute",
        top: 86,
        left: 70,
        right: 70,
        minHeight: 156,
        borderRadius: 34,
        background: "linear-gradient(135deg, rgba(37,99,235,0.96), rgba(14,165,233,0.88))",
        color: "white",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 58,
        fontWeight: 800,
        letterSpacing: 1,
        textAlign: "center",
        padding: "0 42px",
        boxShadow: "0 22px 52px rgba(37, 99, 235, 0.34), inset 0 1px 0 rgba(255,255,255,0.28)",
      }}
    >
      {title}
    </div>
  );
};

const Scene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const rotateY = interpolate(frame, [0, 45, 120], [-12, 0, 7], {
    extrapolateLeft: "clamp",
  });
  const translateZ = interpolate(frame, [0, 24], [-120, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <AbsoluteFill style={{ opacity }}>
      <div
        style={{
          position: "absolute",
          top: 300,
          left: 70,
          right: 70,
          height: 1115,
          borderRadius: 42,
          overflow: "hidden",
          background: "rgba(15,23,42,0.72)",
          border: "2px solid rgba(125,211,252,0.30)",
          boxShadow: "0 34px 90px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.16)",
          perspective: 1400,
          transformStyle: "preserve-3d",
          transform: `translateZ(${translateZ}px) rotateY(${rotateY}deg)`,
        }}
      >
        {clip.sceneImage ? <SceneImage src={clip.sceneImage} /> : null}
        <SceneVisual clip={clip} index={index} />
      </div>
    </AbsoluteFill>
  );
};

const SceneImage: React.FC<{ src: string }> = ({ src }) => {
  return (
    <>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: "blur(8px) saturate(0.45) brightness(1.18)",
        }}
      />
      <AbsoluteFill style={{ background: "rgba(255,255,255,0.68)" }} />
    </>
  );
};

const SceneVisual: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const sceneType = inferredSceneType(clip);
  const phase = inferredScenePhase(clip, index);
  const enrichedClip = { ...clip, scenePhase: phase };
  if (sceneType === "physics_force") {
    return <PhysicsForceScene clip={enrichedClip} index={index} />;
  }
  if (sceneType === "physics_charge") {
    return <PhysicsChargeScene clip={enrichedClip} index={index} />;
  }
  if (sceneType === "physics_field") {
    return <PhysicsFieldScene clip={enrichedClip} index={index} />;
  }
  if (sceneType === "chemistry_reaction") {
    return <ChemistryReactionScene clip={enrichedClip} index={index} />;
  }
  if (sceneType === "math_graph") {
    return <MathGraphScene clip={enrichedClip} index={index} />;
  }
  if (sceneType === "biology_process") {
    return <BiologyProcessScene clip={enrichedClip} index={index} />;
  }
  return <GenericAnalysisScene clip={enrichedClip} index={index} />;
};

const inferredSceneType = (clip: ProblemSolving3DClip) => {
  const explicit = clip.sceneType || "concept";
  if (explicit !== "concept") return explicit;
  const text = `${clip.subtitle} ${clip.voiceover} ${clip.visual}`;
  if (/点电荷|库仑定律|库仑力|静电力|等边三角形/.test(text)) return "physics_charge";
  if (/电磁场|电场|磁场|电荷|洛伦兹力|安培力|电势/.test(text)) return "physics_field";
  if (/圆周运动|向心力|圆锥摆|拉力|重力|合力/.test(text)) return "physics_force";
  if (/反应|浓度|溶液|化学|酸|碱/.test(text)) return "chemistry_reaction";
  if (/函数|坐标|图像|几何|方程|抛物线/.test(text)) return "math_graph";
  if (/细胞|染色体|光合作用|呼吸作用|分裂/.test(text)) return "biology_process";
  return explicit;
};

const inferredScenePhase = (clip: ProblemSolving3DClip, index: number) => {
  if (clip.scenePhase && clip.scenePhase !== "explain") return clip.scenePhase;
  if (index === 0) return "intro";
  if (index === 1) return "question";
  if (index === 2) return "conditions";
  if (index === 3) return "model";
  if (/结果|所以|答案/.test(`${clip.subtitle} ${clip.voiceover}`)) return "result";
  return "solve";
};

const PhysicsForceScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const orbit = (frame + index * 18) / 28;
  const x = 360 + Math.cos(orbit) * 220;
  const y = 520 + Math.sin(orbit) * 76;
  return (
    <AbsoluteFill style={{ transformStyle: "preserve-3d", perspective: 1300 }}>
      <OrbitPlane />
      <StringLine x1={360} y1={250} x2={x} y2={y} label="拉力" />
      <ForceArrow x1={x} y1={y} x2={x} y2={y + 170} color="#fb923c" label="重力" />
      <ForceArrow x1={x} y1={y + 90} x2={360} y2={y + 90} color="#22c55e" label="向心力" />
      <Ball x={x} y={y} />
      <FormulaBoard lines={["受力分解", "T cosθ = mg", "T sinθ = m v² / r", safeText(clip.subtitle, 24)]} />
    </AbsoluteFill>
  );
};

const PhysicsChargeScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const phase = clip.scenePhase || "solve";
  const progress = Math.min(1, frame / 80);
  const q1 = { x: 500, y: 280 };
  const q2 = { x: 250, y: 700 };
  const q3 = { x: 750, y: 700 };
  const showForces = ["conditions", "model", "solve", "result"].includes(phase);
  const showResult = ["solve", "result"].includes(phase);
  return (
    <AbsoluteFill style={{ perspective: 1300, transformStyle: "preserve-3d" }}>
      <StageLabel phase={phase} />
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, transform: "translateZ(90px)" }}>
        <line x1={q1.x} y1={q1.y} x2={q2.x} y2={q2.y} stroke="rgba(125,211,252,0.52)" strokeWidth="8" />
        <line x1={q2.x} y1={q2.y} x2={q3.x} y2={q3.y} stroke="rgba(125,211,252,0.52)" strokeWidth="8" />
        <line x1={q1.x} y1={q1.y} x2={q3.x} y2={q3.y} stroke="rgba(125,211,252,0.52)" strokeWidth="8" />
        <line x1={q3.x} y1={q3.y} x2={q3.x - 95 * progress} y2={q3.y - 160 * progress} stroke="#38bdf8" strokeWidth="5" strokeDasharray="10 8" />
      </svg>
      <ChargeBall x={q1.x} y={q1.y} label="q₁" />
      <ChargeBall x={q2.x} y={q2.y} label="q₂" />
      <ChargeBall x={q3.x} y={q3.y} label="q₃" highlight />
      {showForces ? (
        <>
          <ForceArrow x1={q3.x} y1={q3.y} x2={q3.x - 125 * progress} y2={q3.y + 5} color="#38bdf8" label="F₂" />
          <ForceArrow x1={q3.x} y1={q3.y} x2={q3.x + 82 * progress} y2={q3.y - 138 * progress} color="#f472b6" label="F₁" />
        </>
      ) : null}
      {showResult ? <ForceArrow x1={q3.x} y1={q3.y} x2={q3.x + 170 * progress} y2={q3.y - 70 * progress} color="#facc15" label="F" /> : null}
      <ChargeFormulaPanel lines={chargeFormulaLines(phase, clip.subtitle)} />
      <ProcessHint text={phase === "result" ? "合力方向" : processHintText(phase, clip.subtitle)} />
    </AbsoluteFill>
  );
};

const ChargeBall: React.FC<{ x: number; y: number; label: string; highlight?: boolean }> = ({ x, y, label, highlight = false }) => (
  <>
    <div style={{ position: "absolute", left: x - 45, top: y - 45, width: 90, height: 90, borderRadius: "50%", background: highlight ? "radial-gradient(circle at 32% 24%, #fef3c7, #f97316)" : "radial-gradient(circle at 32% 24%, #e0f2fe, #38bdf8)", border: "5px solid rgba(255,255,255,0.68)", boxShadow: "0 22px 42px rgba(0,0,0,0.30)", transform: "translateZ(180px)" }} />
    <Label left={x} top={y - 72} text={label} color={highlight ? "#fed7aa" : "#bae6fd"} />
    <Label left={x} top={y + 4} text="+" color="#0f172a" />
  </>
);

const chargeFormulaLines = (phase: string, subtitle: string) => {
  if (phase === "question") return ["库仑力合成", "只分析 q₃", "F₁、F₂ 对称"];
  if (phase === "conditions") return ["库仑力", "F₁ = F₂", "r = 0.50 m"];
  if (phase === "model") return ["核心公式", "F₁ = F₂ = kq²/r²", safeText(subtitle, 64)];
  if (phase === "result") return ["合力结果", "F = 2F₁ cos30°", "F = 0.25 N"];
  return ["推导公式", safeText(subtitle, 64), "分力按平行四边形合成"];
};

const ChargeFormulaPanel: React.FC<{ lines: string[] }> = ({ lines }) => (
  <div
    style={{
      position: "absolute",
      left: 72,
      top: 88,
      width: 470,
      borderRadius: 22,
      padding: "14px 18px",
      background: "rgba(15,23,42,0.92)",
      border: "2px solid rgba(125,211,252,0.42)",
      boxShadow: "0 18px 38px rgba(0,0,0,0.28)",
      transform: "translateZ(260px)",
    }}
  >
    {lines.filter(Boolean).slice(0, 3).map((line, i) => {
      const text = safeText(line, 72);
      return (
        <div
          key={`${line}-${i}`}
          style={{
            color: i === 0 ? "#93c5fd" : "#ffffff",
            fontSize: i === 0 ? 22 : text.length > 32 ? 18 : 21,
            fontWeight: 950,
            lineHeight: 1.18,
            overflowWrap: "anywhere",
            wordBreak: "break-word",
            marginBottom: i === 0 ? 5 : 3,
          }}
        >
          {text}
        </div>
      );
    })}
  </div>
);

const PhysicsFieldScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const phase = clip.scenePhase || "explain";
  if (isElectrostaticInductionClip(clip)) {
    return <ElectrostaticInductionScene clip={clip} phase={phase} frame={frame} />;
  }
  const entryProgress = Math.min(1, frame / 90);
  const particleX = 145 + entryProgress * 330;
  const particleY = 515;
  const orbitProgress = Math.min(1, frame / 120);
  const angle = -Math.PI * 0.15 + orbitProgress * Math.PI * 1.55 + index * 0.08;
  const orbitX = 475 + Math.cos(angle) * 210;
  const orbitY = 515 + Math.sin(angle) * 150;
  const showOrbit = ["model", "solve", "result"].includes(phase);
  const showVectors = ["model", "solve", "result"].includes(phase);
  const showConditions = ["question", "conditions"].includes(phase);
  const ballX = showOrbit ? orbitX : particleX;
  const ballY = showOrbit ? orbitY : particleY;
  return (
    <AbsoluteFill style={{ perspective: 1300, transformStyle: "preserve-3d" }}>
      <FieldVolume />
      <StageLabel phase={phase} />
      {showConditions ? <ConditionTokens /> : null}
      {showOrbit ? <ParticleOrbit progress={orbitProgress} /> : <EntryBeam progress={entryProgress} />}
      {showVectors ? (
        <>
          <ForceArrow x1={ballX} y1={ballY} x2={ballX + 145} y2={ballY - 72} color="#facc15" label="洛伦兹力" />
          <ForceArrow x1={ballX} y1={ballY} x2={ballX + 128} y2={ballY} color="#38bdf8" label="速度" />
          <RadiusLine x={ballX} y={ballY} />
        </>
      ) : null}
      <Ball x={ballX} y={ballY} color="#a78bfa" />
      {phase === "solve" ? <EquationFlow left="qvB" middle="mv² / r" right="r = mv / qB" /> : null}
      {phase === "result" ? <ResultGauges /> : null}
      <ProcessHint text={processHintText(phase, clip.subtitle)} />
    </AbsoluteFill>
  );
};

const isElectrostaticInductionClip = (clip: ProblemSolving3DClip) => /静电感应|验电器|箔片|导体|带电体|近端|远端|自由电荷/.test(`${clip.visual} ${clip.voiceover} ${clip.subtitle}`);

const ElectrostaticInductionScene: React.FC<{ clip: ProblemSolving3DClip; phase: string; frame: number }> = ({ clip, phase, frame }) => {
  const approach = Math.min(1, frame / 70);
  const chargeShift = Math.min(1, Math.max(0, (frame - 18) / 70));
  const foilOpen = ["solve", "result"].includes(phase) ? Math.min(1, Math.max(0, (frame - 35) / 55)) : 0.25 * chargeShift;
  const rodX = 150 + approach * 78;
  return (
    <AbsoluteFill style={{ perspective: 1300, transformStyle: "preserve-3d" }}>
      <StageLabel phase={phase} />
      <div style={{ position: "absolute", left: 110, top: 255, width: 700, height: 540, borderRadius: 42, background: "linear-gradient(135deg, rgba(15,23,42,0.72), rgba(30,64,175,0.36))", border: "3px solid rgba(125,211,252,0.36)", transform: "rotateX(9deg) translateZ(70px)", boxShadow: "inset 0 0 60px rgba(56,189,248,0.14)" }} />
      <ChargedRod x={rodX} />
      <Electroscope foilOpen={foilOpen} />
      <ElectronFlow progress={chargeShift} />
      <ChargeLabels progress={chargeShift} />
      <AnnotationArrow fromX={rodX + 115} fromY={380} toX={405} toY={390} label="带电体靠近" color="#facc15" />
      {["conditions", "model", "solve", "result"].includes(phase) ? <AnnotationArrow fromX={520} fromY={430} toX={610} toY={430} label="自由电子移动" color="#38bdf8" /> : null}
      {["solve", "result"].includes(phase) ? <AnnotationArrow fromX={555} fromY={635} toX={465 - foilOpen * 55} toY={760} label="同种电荷排斥" color="#fb7185" /> : null}
      <FormulaBoard
        lines={[
          "静电感应解法",
          phase === "question" ? "先判断带电体电性" : "近端异种 远端同种",
          phase === "solve" ? "箔片同种电荷排斥而张开" : safeText(clip.subtitle, 28),
        ]}
      />
      <ProcessHint text={processHintText(phase, clip.subtitle)} />
    </AbsoluteFill>
  );
};

const ChargedRod: React.FC<{ x: number }> = ({ x }) => (
  <div style={{ position: "absolute", left: x, top: 300, width: 118, height: 250, borderRadius: 999, background: "linear-gradient(180deg, #fb7185, #dc2626)", boxShadow: "0 28px 44px rgba(220,38,38,0.34)", transform: "translateZ(210px)", display: "grid", placeItems: "center", color: "white", fontSize: 42, fontWeight: 1000 }}>
    + + +
  </div>
);

const Electroscope: React.FC<{ foilOpen: number }> = ({ foilOpen }) => {
  const leftX = 475 - foilOpen * 70;
  const rightX = 475 + foilOpen * 70;
  return (
    <>
      <div style={{ position: "absolute", left: 430, top: 320, width: 90, height: 90, borderRadius: "50%", background: "#e2e8f0", border: "6px solid #94a3b8", transform: "translateZ(180px)" }} />
      <div style={{ position: "absolute", left: 470, top: 408, width: 14, height: 235, borderRadius: 999, background: "#cbd5e1", transform: "translateZ(180px)" }} />
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, transform: "translateZ(190px)" }}>
        <line x1="477" y1="635" x2={leftX} y2="805" stroke="#facc15" strokeWidth="16" strokeLinecap="round" />
        <line x1="477" y1="635" x2={rightX} y2="805" stroke="#facc15" strokeWidth="16" strokeLinecap="round" />
        <ellipse cx="477" cy="642" rx="185" ry="260" fill="none" stroke="rgba(226,232,240,0.38)" strokeWidth="7" />
      </svg>
      <Label left={477} top={287} text="验电器" color="#bae6fd" />
    </>
  );
};

const ElectronFlow: React.FC<{ progress: number }> = ({ progress }) => (
  <>
    {Array.from({ length: 6 }).map((_, i) => {
      const start = 570 + i * 22;
      const x = start - progress * (95 + i * 10);
      const y = 390 + Math.sin(i) * 16;
      return <Charge key={i} x={x} y={y} text="-" color="#38bdf8" />;
    })}
  </>
);

const ChargeLabels: React.FC<{ progress: number }> = ({ progress }) => (
  <>
    <Charge x={395} y={390} text="-" color="#38bdf8" opacity={0.45 + progress * 0.55} />
    <Charge x={620} y={390} text="+" color="#fb7185" opacity={0.45 + progress * 0.55} />
    <Label left={370} top={460} text="近端感应负电" color="#38bdf8" />
    <Label left={650} top={460} text="远端感应正电" color="#fb7185" />
  </>
);

const Charge: React.FC<{ x: number; y: number; text: string; color: string; opacity?: number }> = ({ x, y, text, color, opacity = 1 }) => (
  <div style={{ position: "absolute", left: x - 22, top: y - 22, width: 44, height: 44, borderRadius: "50%", background: color, color: "white", opacity, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 34, fontWeight: 1000, boxShadow: "0 12px 24px rgba(0,0,0,0.28)", transform: "translateZ(230px)" }}>
    {text}
  </div>
);

const AnnotationArrow: React.FC<{ fromX: number; fromY: number; toX: number; toY: number; label: string; color: string }> = ({ fromX, fromY, toX, toY, label, color }) => (
  <>
    <ForceArrow x1={fromX} y1={fromY} x2={toX} y2={toY} color={color} label={label} />
  </>
);

const processHintText = (phase: string, fallback: string) => {
  if (phase === "intro") return "先建模";
  if (phase === "question") return "只提条件";
  if (phase === "conditions") return "标出物理量";
  if (phase === "model") return "建立模型";
  if (phase === "solve") return "推导解释";
  if (phase === "result") return "结果回到图形";
  return safeText(fallback, 12);
};

const FieldVolume: React.FC = () => (
  <>
    <div style={{ position: "absolute", left: 138, top: 245, width: 660, height: 540, borderRadius: 38, background: "linear-gradient(135deg, rgba(14,165,233,0.14), rgba(99,102,241,0.20))", border: "3px solid rgba(125,211,252,0.32)", transform: "rotateX(10deg) translateZ(30px)", boxShadow: "inset 0 0 70px rgba(56,189,248,0.14)" }} />
    {Array.from({ length: 42 }).map((_, i) => {
      const col = i % 7;
      const row = Math.floor(i / 7);
      return (
        <div key={i} style={{ position: "absolute", left: 185 + col * 86, top: 300 + row * 75, width: 32, height: 32, borderRadius: "50%", border: "4px solid rgba(147,197,253,0.82)", color: "#bfdbfe", fontSize: 22, fontWeight: 900, lineHeight: "22px", textAlign: "center", transform: `translateZ(${80 + row * 4}px)` }}>
          ×
        </div>
      );
    })}
  </>
);

const StageLabel: React.FC<{ phase: string }> = ({ phase }) => (
  <div style={{ position: "absolute", left: 96, top: 78, borderRadius: 999, background: "rgba(37,99,235,0.94)", color: "white", padding: "12px 24px", fontSize: 30, fontWeight: 900, transform: "translateZ(220px)", boxShadow: "0 16px 32px rgba(0,0,0,0.22)" }}>
    {processHintText(phase, "")}
  </div>
);

const ConditionTokens: React.FC = () => (
  <div style={{ position: "absolute", left: 120, right: 120, top: 740, display: "flex", justifyContent: "center", gap: 18, transform: "translateZ(210px)" }}>
    {["v", "B", "q", "m", "求 r/T"].map((item, i) => (
      <div key={item} style={{ width: 126, height: 82, borderRadius: 22, background: ["#2563eb", "#7c3aed", "#0891b2", "#16a34a", "#f97316"][i], color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 30, fontWeight: 900, boxShadow: "0 20px 38px rgba(0,0,0,0.28)", transform: `translateY(${Math.sin((i + 1) * 0.8) * 8}px)` }}>
        {item}
      </div>
    ))}
  </div>
);

const EntryBeam: React.FC<{ progress: number }> = ({ progress }) => (
  <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, transform: "translateZ(110px)" }}>
    <line x1="128" y1="515" x2={145 + progress * 330} y2="515" stroke="#38bdf8" strokeWidth="8" strokeDasharray="18 16" />
  </svg>
);

const ParticleOrbit: React.FC<{ progress: number }> = ({ progress }) => (
  <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, transform: "translateZ(118px)" }}>
    <ellipse cx="475" cy="515" rx="210" ry="150" fill="none" stroke="rgba(56,189,248,0.32)" strokeWidth="10" />
    <path d={`M680 492 A210 150 0 ${progress > 0.5 ? 1 : 0} 1 ${475 + Math.cos(-Math.PI * 0.15 + progress * Math.PI * 1.55) * 210} ${515 + Math.sin(-Math.PI * 0.15 + progress * Math.PI * 1.55) * 150}`} fill="none" stroke="#38bdf8" strokeWidth="12" strokeLinecap="round" />
  </svg>
);

const RadiusLine: React.FC<{ x: number; y: number }> = ({ x, y }) => (
  <>
    <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
      <line x1="475" y1="515" x2={x} y2={y} stroke="#fb923c" strokeWidth="7" strokeDasharray="14 10" />
    </svg>
    <Label left={(475 + x) / 2} top={(515 + y) / 2 - 20} text="r" color="#fb923c" />
  </>
);

const EquationFlow: React.FC<{ left: string; middle: string; right: string }> = ({ left, middle, right }) => (
  <div style={{ position: "absolute", left: 102, right: 102, bottom: 130, display: "flex", alignItems: "center", justifyContent: "center", gap: 18, transform: "translateZ(230px)" }}>
    {[left, "=", middle, "→", right].map((item, i) => (
      <div key={`${item}-${i}`} style={{ borderRadius: 18, background: i % 2 === 0 ? "rgba(15,23,42,0.92)" : "transparent", color: i % 2 === 0 ? "white" : "#93c5fd", padding: i % 2 === 0 ? "18px 20px" : "0", fontSize: 32, fontWeight: 900, border: i % 2 === 0 ? "2px solid rgba(148,163,184,0.35)" : 0 }}>
        {item}
      </div>
    ))}
  </div>
);

const ResultGauges: React.FC = () => (
  <div style={{ position: "absolute", left: 130, right: 130, bottom: 132, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22, transform: "translateZ(230px)" }}>
    {["半径 r 变大：轨道变宽", "周期 T：转一圈用时"].map((item) => (
      <div key={item} style={{ borderRadius: 24, background: "rgba(15,23,42,0.90)", border: "2px solid rgba(125,211,252,0.42)", color: "white", padding: "24px 22px", fontSize: 30, fontWeight: 900, textAlign: "center" }}>
        {item}
      </div>
    ))}
  </div>
);

const ProcessHint: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ position: "absolute", right: 90, top: 78, color: "#bae6fd", fontSize: 30, fontWeight: 900, transform: "translateZ(220px)" }}>{safeText(text, 18)}</div>
);

const ChemistryReactionScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ perspective: 1300 }}>
      <Beaker x={170} label="反应前" bubbles={frame} />
      <Arrow3D left={420} top={520} />
      <Beaker x={610} label="反应后" bubbles={frame + 30} />
      <FormulaBoard lines={["浓度变化", "v = Δc / Δt", safeText(clip.subtitle, 24)]} />
    </AbsoluteFill>
  );
};

const MathGraphScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, frame / 90);
  return (
    <AbsoluteFill style={{ perspective: 1300 }}>
      <div style={{ position: "absolute", left: 150, top: 285, width: 620, height: 520, transform: "rotateX(10deg) translateZ(80px)" }}>
        <div style={{ position: "absolute", left: 40, top: 460, width: 540, height: 5, background: "#cbd5e1" }} />
        <div style={{ position: "absolute", left: 70, top: 60, width: 5, height: 430, background: "#cbd5e1" }} />
        <svg width="620" height="520" style={{ position: "absolute", inset: 0 }}>
          <path d={`M80 420 C 180 ${420 - 180 * progress}, 330 ${180 + 80 * progress}, 560 ${110 + 60 * (1 - progress)}`} stroke="#38bdf8" strokeWidth="10" fill="none" strokeLinecap="round" />
        </svg>
      </div>
      <FormulaBoard lines={["函数图像", "看变化趋势", safeText(clip.subtitle, 24)]} />
    </AbsoluteFill>
  );
};

const BiologyProcessScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const split = Math.min(1, frame / 80);
  return (
    <AbsoluteFill style={{ perspective: 1300 }}>
      <Cell x={360 - split * 140} y={480} label="细胞" />
      <Cell x={360 + split * 140} y={480} label="变化" />
      <Arrow3D left={430} top={500} />
      <FormulaBoard lines={["生命过程", "结构变化", safeText(clip.subtitle, 24)]} />
    </AbsoluteFill>
  );
};

const GenericAnalysisScene: React.FC<{ clip: ProblemSolving3DClip; index: number }> = ({ clip, index }) => {
  const frame = useCurrentFrame();
  const phase = clip.scenePhase || "solve";
  const progress = Math.min(1, frame / 90);
  const nodes = ["条件", "模型", "关系", "结果"];
  return (
    <AbsoluteFill style={{ perspective: 1300, transformStyle: "preserve-3d" }}>
      <StageLabel phase={phase} />
      <div style={{ position: "absolute", left: 130, right: 130, top: 250, height: 460, transform: "rotateX(10deg) translateZ(80px)" }}>
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
          <line x1="110" y1="230" x2="690" y2="230" stroke="rgba(125,211,252,0.42)" strokeWidth="10" strokeDasharray="20 16" />
        </svg>
        {nodes.map((node, i) => {
          const active = progress * (nodes.length - 1) >= i || phase === "result";
          return (
            <div key={node} style={{ position: "absolute", left: 58 + i * 190, top: 130 + Math.sin((frame + i * 10) / 28) * 10, width: 150, height: 150, borderRadius: 38, background: active ? ["#2563eb", "#0f766e", "#d97706", "#7c3aed"][i] : "rgba(30,41,59,0.82)", color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 34, fontWeight: 900, boxShadow: "0 28px 48px rgba(0,0,0,0.30)", transform: `translateZ(${120 + i * 22}px)` }}>
              {node}
            </div>
          );
        })}
      </div>
      <FormulaBoard lines={[processHintText(phase, clip.subtitle), safeText(clip.subtitle || clip.visual, 24), "用动画表现解析链路"]} />
    </AbsoluteFill>
  );
};

const OrbitPlane: React.FC = () => (
  <div style={{ position: "absolute", left: 150, top: 415, width: 620, height: 210, borderRadius: "50%", border: "8px solid rgba(125,211,252,0.55)", transform: "rotateX(62deg) translateZ(40px)", boxShadow: "0 0 50px rgba(56,189,248,0.22)" }} />
);

const Ball: React.FC<{ x: number; y: number; color?: string }> = ({ x, y, color = "#fb923c" }) => (
  <div style={{ position: "absolute", left: x - 54, top: y - 54, width: 108, height: 108, borderRadius: "50%", background: `radial-gradient(circle at 30% 25%, #fff7ed, ${color})`, boxShadow: "0 28px 48px rgba(0,0,0,0.36)", transform: "translateZ(180px)" }} />
);

const StringLine: React.FC<{ x1: number; y1: number; x2: number; y2: number; label: string }> = ({ x1, y1, x2, y2, label }) => (
  <>
    <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#bae6fd" strokeWidth="8" />
    </svg>
    <Label left={(x1 + x2) / 2} top={(y1 + y2) / 2 - 28} text={label} color="#facc15" />
  </>
);

const ForceArrow: React.FC<{ x1: number; y1: number; x2: number; y2: number; color: string; label: string }> = ({ x1, y1, x2, y2, color, label }) => (
  <>
    <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
      <defs>
        <marker id={`arrow-${label}`} markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
          <path d="M0,0 L12,6 L0,12 z" fill={color} />
        </marker>
      </defs>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth="10" markerEnd={`url(#arrow-${label})`} />
    </svg>
    <Label left={(x1 + x2) / 2} top={(y1 + y2) / 2 - 26} text={label} color={color} />
  </>
);

const Label: React.FC<{ left: number; top: number; text: string; color: string }> = ({ left, top, text, color }) => (
  <div style={{ position: "absolute", left, top, transform: "translate(-50%, -50%) translateZ(210px)", color, fontSize: 30, fontWeight: 900, textShadow: "0 2px 10px #020617" }}>{text}</div>
);

const formulaFontSize = (text: string, index: number) => {
  if (index === 0) return 22;
  if (text.length > 48) return 16;
  if (text.length > 34) return 17;
  if (text.length > 24) return 18;
  return 20;
};

const FormulaBoard: React.FC<{ lines: string[] }> = ({ lines }) => (
  <div style={{ position: "absolute", left: 34, right: 34, bottom: 64, borderRadius: 24, padding: "14px 20px", background: "rgba(15,23,42,0.90)", border: "2px solid rgba(148,163,184,0.35)", transform: "translateZ(220px)" }}>
    {lines.filter(Boolean).slice(0, 3).map((line, i) => {
      const text = safeText(line, 76);
      return (
        <div
          key={`${line}-${i}`}
          style={{
            color: i === 0 ? "#93c5fd" : "white",
            fontSize: formulaFontSize(text, i),
            fontWeight: 900,
            lineHeight: 1.16,
            whiteSpace: "normal",
            overflowWrap: "anywhere",
            wordBreak: "break-word",
            marginBottom: i === 0 ? 5 : 3,
          }}
        >
          {text}
        </div>
      );
    })}
  </div>
);

const Beaker: React.FC<{ x: number; label: string; bubbles: number }> = ({ x, label, bubbles }) => (
  <div style={{ position: "absolute", left: x, top: 320, width: 250, height: 370, transform: "rotateX(8deg) translateZ(120px)" }}>
    <div style={{ position: "absolute", inset: "80px 28px 0", borderRadius: "0 0 44px 44px", border: "8px solid rgba(226,232,240,0.78)", borderTop: 0, background: "linear-gradient(180deg, rgba(56,189,248,0.24), rgba(14,165,233,0.66))" }} />
    {Array.from({ length: 7 }).map((_, i) => (
      <div key={i} style={{ position: "absolute", left: 62 + (i % 3) * 48, bottom: 40 + ((bubbles + i * 19) % 170), width: 22, height: 22, borderRadius: "50%", background: "rgba(255,255,255,0.78)" }} />
    ))}
    <Label left={125} top={45} text={label} color="#facc15" />
  </div>
);

const Arrow3D: React.FC<{ left: number; top: number }> = ({ left, top }) => (
  <div style={{ position: "absolute", left, top, width: 170, height: 34, borderRadius: 999, background: "#38bdf8", transform: "translateZ(180px)", boxShadow: "0 12px 30px rgba(56,189,248,0.35)" }}>
    <div style={{ position: "absolute", right: -34, top: -18, width: 0, height: 0, borderTop: "35px solid transparent", borderBottom: "35px solid transparent", borderLeft: "54px solid #38bdf8" }} />
  </div>
);

const Cell: React.FC<{ x: number; y: number; label: string }> = ({ x, y, label }) => (
  <div style={{ position: "absolute", left: x - 105, top: y - 105, width: 210, height: 210, borderRadius: "46% 54% 48% 52%", background: "radial-gradient(circle at 40% 38%, rgba(250,204,21,0.95), rgba(34,197,94,0.82))", border: "8px solid rgba(187,247,208,0.8)", boxShadow: "0 26px 52px rgba(0,0,0,0.28)", transform: "translateZ(170px)" }}>
    <div style={{ position: "absolute", left: 72, top: 72, width: 66, height: 66, borderRadius: "50%", background: "rgba(15,23,42,0.38)" }} />
    <Label left={105} top={245} text={label} color="#bbf7d0" />
  </div>
);

