// Weak-laptop defaults (RTX 2050 / 4 GB VRAM). The design uses no blur, no filters, no WebGL.
import {Config} from '@remotion/cli/config';
Config.setVideoImageFormat('jpeg');      // jpeg frames: ~3x faster than png, invisible after CRF 18
Config.setJpegQuality(92);
Config.setConcurrency(2);                // 2 tabs; raise to 3 only with >= 12 GB RAM; 1 if the laptop swaps
Config.setChromiumOpenGlRenderer('angle'); // if Chrome crashes use 'swangle' (CPU)
Config.setCodec('h264');
Config.setCrf(18);
Config.setPixelFormat('yuv420p');
Config.setOverwriteOutput(true);
Config.setEntryPoint('src/index.ts');
