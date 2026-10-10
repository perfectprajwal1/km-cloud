import React from 'react';
import {Composition} from 'remotion';
import {Reel} from './Reel';
import {totalFrames} from './plan';
import {FPS} from './motion';
import {Props} from './types';
import story from '../public/story.json';
import timing from '../public/timing.json';

export const Root: React.FC = () => (
  <Composition
    id="Reel"
    component={Reel as unknown as React.FC<Record<string, unknown>>}
    fps={FPS}
    width={1080}
    height={1920}
    durationInFrames={300}
    defaultProps={{story, timing, lite: false} as unknown as Record<string, unknown>}
    calculateMetadata={async ({props}: {props: Record<string, unknown>}) => ({durationInFrames: totalFrames(props as unknown as Props)})}
  />
);
