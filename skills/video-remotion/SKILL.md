---
name: video-remotion
description: Render textbook problem-solving scripts into narrated vertical 3D MP4 videos using Remotion React compositions. Use when working on /workflow/video/agent, Remotion, textbook problem videos, subtitles, voiceover sync, analytical animation phases, or React-based video rendering.
---

# Video Remotion

## Purpose

This project skill is the Remotion 3.0 rendering contract for `langgraph-study`.
It adapts the upstream `remotion-dev/skills/skills/remotion` best practices to
the local K12 video agent workflow.

Use it whenever implementing, debugging, or generating videos through:

- `/workflow/video/agent`
- `app/tools/video_render.py`
- `video-renderer/src/ProblemSolving3DVideo.tsx`
- `video-renderer/src/ConicalPendulumVideo.tsx`
- `scripts/render_conical_pendulum_video.py`

## Mandatory Output Contract

Every `/workflow/video/agent` result must satisfy all of these requirements:

1. The result page shows source material.
2. The result page shows the complete knowledge-point task or full question.
3. The result page shows the explanation process.
4. The generated MP4 has narration audio.

If a source is missing, the result page must still show the source section with
`未提供来源，需要人工补充或复核`. Do not omit the section.

If audio generation fails, do not treat a silent video as a final result. Return
an error or a clear review warning.

## Remotion Best Practices Skill Rules

For every `/workflow/video/agent` render, this skill is mandatory. Treat these
Remotion best practices as hard requirements, not optional style guidance:

1. Use `useCurrentFrame()` and `interpolate()` for animation.
2. Do not use CSS transitions, CSS animations, or Tailwind animation classes.
3. Use `Sequence` to place structured explanation phases on the timeline.
4. Use `calculateMetadata` to size duration from props/audio timing.
5. Use `staticFile()` for assets placed under `video-renderer/public`.
6. Use React text for subtitles and all readable labels.
7. Do not let AI-generated images provide readable text.
8. Use 9:16 vertical video by default, 1080x1920 at 30 fps.
9. Keep visual text Simplified Chinese only.
10. Render general K12 videos as 3D Remotion scenes by default: use perspective,
    `transformStyle: "preserve-3d"`, depth, orbit/floating motion, and layered
    subject-specific 3D objects.
11. The video must animate the problem-solving process, not just rotate text.
    Show condition extraction, model construction, force/field/reaction/graph
    changes, formula derivation, and the final result returning to the visual
    model.

For detailed upstream rules, read the files in `rules/` only when relevant:

- Layout and sizing: `rules/video-layout.md`
- Composition metadata: `rules/compositions.md`, `rules/calculate-metadata.md`
- Timing and sequencing: `rules/timing.md`, `rules/sequencing.md`
- Captions and subtitles: `rules/subtitles.md`, `rules/display-captions.md`
- Audio and voiceover: `rules/audio.md`, `rules/voiceover.md`
- Text animation: `rules/text-animations.md`
- 3D visuals: `rules/3d.md`
- Images and assets: `rules/images.md`

## Local Project Paths

- Remotion project: `video-renderer/`
- Remotion entry point: `video-renderer/src/index.ts`
- General composition: `ProblemSolving3DVideo`
- Conical pendulum demo composition: `ConicalPendulumVideo`
- Backend renderer bridge: `app/tools/video_render.py`
- Agent workspace: `/workflow/video/agent`
- PDF skill: `skills/pdf`
- TTS skill: `skills/voice-tts`

## Agent Workflow

The video agent should work in this order:

1. Parse the user's real topic. Do not treat "参考圆锥摆展示页模式" as the topic.
2. Use `skills/pdf` to obtain and verify textbook content before building the video. For ChinaTextbook tasks, locate the exact local/remote PDF, parse the selected page, and extract the source, full original problem, and solution basis.
3. Build a structured source/question/solution object from PDF skill output.
4. Build internal Remotion timeline clips directly from the structured question and explanation steps.
   Do not generate or parse a `分镜脚本` / storyboard markdown as an intermediate format.
5. Mark every clip with explanation phases such as `intro`, `question`,
   `conditions`, `model`, `solve`, and `result`, so `ProblemSolving3DVideo` can render an
   actual 3D analytical animation instead of text cards.
6. Generate narration audio using `skills/voice-tts`; its core backend calls the Volcengine text-to-speech API to convert narration text into voice audio, with explicit fallback only for local previews.
7. Measure the generated audio duration and synchronize clip timing to real audio duration.
8. Render a 3D animated video with Remotion `ProblemSolving3DVideo` and save the narrated result as a new MP4, for example `video-remotion-narrated.mp4`.
9. Save a result page that displays source, full task/question, explanation steps, and video.

For explicit conical-pendulum demo tasks only, use `ConicalPendulumVideo`.
For normal user tasks, use `ProblemSolving3DVideo`.

## Environment Rules

The service must prefer Remotion and should not silently fall back to the old
static-frame pipeline for `/workflow/video/agent`.

On this Linux environment, host glibc may be too old for Remotion. In that case
the backend should use Docker with a browser-ready image:

```bash
VIDEO_RENDER_REMOTION_DOCKER_IMAGE=mcr.microsoft.com/playwright:v1.49.1-jammy
```

Use `scripts/check_platform.py` to check whether Node, Remotion CLI, Docker,
and the renderer project are available.

## Result Page Requirements

The generated page must include these user-facing sections:

- `例题来源 / 任务来源`
- `完整题目 / Agent 任务`
- `解答过程`

The page must link or embed the narrated MP4.
The internal Remotion input is only used to render the MP4. Do not show a
`视频脚本` section on the result page. Render engine, skill path, warnings, and
review flags are backend metadata. Do not ask any script writer to output
`视频渲染`, `人工复核`, `注意`, `来源与复核`, `发布风险自查`, or `话题标签`.

## Review Requirements

Always mark generated educational videos for human review before publishing.
Review must cover:

- Source accuracy.
- Knowledge definition and formula correctness.
- Whether the explanation process is complete.
- Subtitle and visible text correctness.
- Audio sync and pronunciation.
- Image/video copyright.
