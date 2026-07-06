import { Composition, type CalculateMetadataFunction } from "remotion";
import { ConicalPendulumVideo, type ConicalPendulumVideoProps } from "./ConicalPendulumVideo";
import { ProblemSolving3DVideo, type ProblemSolving3DVideoProps } from "./ProblemSolving3DVideo";

const defaultProps: ProblemSolving3DVideoProps = {
  title: "题目解析 3D 动画",
  coverText: "题目解析",
  audioSrc: "",
  totalDurationSeconds: 10,
  clips: [
    {
      start: 0,
      end: 10,
      visual: "知识点讲解",
      voiceover: "知识点讲解",
      subtitle: "知识点讲解",
    },
  ],
};

const calculateMetadata: CalculateMetadataFunction<ProblemSolving3DVideoProps> = async ({ props }) => {
  return {
    durationInFrames: Math.max(1, Math.ceil((props.totalDurationSeconds || 10) * 30)),
    fps: 30,
    width: 1080,
    height: 1920,
    props,
  };
};

const conicalPendulumDefaultProps: ConicalPendulumVideoProps = {
  title: "圆锥摆运动",
  audioSrc: "",
  durationSeconds: 18,
  narration: "小球沿水平圆周运动时，绳子的拉力和重力合成一个指向圆心的力，这个合力提供向心力。",
};

const calculateConicalPendulumMetadata: CalculateMetadataFunction<ConicalPendulumVideoProps> = async ({ props }) => {
  return {
    durationInFrames: Math.max(1, Math.ceil((props.durationSeconds || 18) * 30)),
    fps: 30,
    width: 1080,
    height: 1920,
    props,
  };
};

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="ProblemSolving3DVideo"
        component={ProblemSolving3DVideo}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultProps}
        calculateMetadata={calculateMetadata}
      />
      <Composition
        id="ConicalPendulumVideo"
        component={ConicalPendulumVideo}
        durationInFrames={540}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={conicalPendulumDefaultProps}
        calculateMetadata={calculateConicalPendulumMetadata}
      />
    </>
  );
};
