import React from 'react';
import {AbsoluteFill, Html5Audio, Composition, Sequence, OffthreadVideo, staticFile} from 'remotion';
import manifest from './manifest.json';

// Copy public/assets into your Remotion project's public/assets.
// Place this component beside manifest.json; register AssetRoot in your entrypoint.
export const AssetTimeline: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: 'black'}}>
    {manifest.clips.map((clip) => (
      <Sequence key={clip.id} from={clip.from} durationInFrames={clip.durationInFrames}>
        {clip.kind === 'video'
          ? <OffthreadVideo src={staticFile(clip.src)} style={{width: '100%', height: '100%', objectFit: 'contain'}} />
          : <Html5Audio src={staticFile(clip.src)} />}
      </Sequence>
    ))}
  </AbsoluteFill>
);
export const AssetRoot: React.FC = () => (
  <Composition id="AssetTimeline" component={AssetTimeline} fps={manifest.fps}
    width={manifest.width} height={manifest.height} durationInFrames={manifest.durationInFrames} />
);
