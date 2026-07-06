# LangGraph Study Video Renderer

Remotion 3.0 renderer for problem-solving 3D explanation videos.

## Install

This subproject requires Node.js and npm.

```bash
cd video-renderer
npm install
```

## Preview

```bash
npm run studio
```

## Backend Integration

The FastAPI backend writes Remotion props JSON and calls:

```bash
npx remotion render src/index.ts ProblemSolving3DVideo <output.mp4> --props <props.json>
```

If Node.js, npm, or `node_modules` is missing, the backend automatically falls back to the existing Pillow + ffmpeg renderer.

## Rendering Rules

- Composition: `ProblemSolving3DVideo`
- Size: 1080x1920
- FPS: 30
- Text is rendered by React components, not by image models.
- Image model outputs are treated as softened backgrounds only.
- Captions and formulas must remain Simplified Chinese or valid math symbols.
