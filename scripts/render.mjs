// One click:  npm run reel -- stories/my_story.json   [--lite] [--scale=0.6667]
// story -> stills+assets (km_cards.py) -> voice (tts.py) -> Remotion -> ffmpeg 2-pass loudnorm (-14 LUFS, -1 dBTP) -> out/<id>.mp4
import {spawnSync} from 'node:child_process';
import fs from 'node:fs'; import path from 'node:path';
const args = process.argv.slice(2); const storyPath = args.find((a) => !a.startsWith('--')) || 'public/story.json';
const lite = args.includes('--lite'); const scale = (args.find((a) => a.startsWith('--scale=')) || '--scale=1').split('=')[1];
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const run = (cmd, a, opt = {}) => { console.log('>', cmd, a.join(' ')); const r = spawnSync(cmd, a, {stdio: opt.capture ? 'pipe' : 'inherit', shell: process.platform === 'win32', encoding: 'utf8', env: {...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8'}});
  if (r.status !== 0) { console.error(r.stderr || ''); process.exit(r.status || 1); } return r; };
const story = JSON.parse(fs.readFileSync(storyPath, 'utf8'));
if (path.resolve(storyPath) !== path.resolve('public/story.json')) fs.copyFileSync(storyPath, 'public/story.json');
fs.mkdirSync('out', {recursive: true});
if (!fs.existsSync('public/sfx/roomtone.wav')) run(PY, ['scripts/make_sfx.py', 'public/sfx']);
// 1) stills (QA PNGs) + paper/logo/baked strips into public/   (add --html-only to skip PNG stills)
run(PY, ['scripts/km_cards.py', 'public/story.json', '--out', 'out', '--fonts', 'public/fonts', '--public', 'public', ...(lite ? ['--html-only'] : [])]);
// 2) voice + word timings
run(PY, ['scripts/tts.py', 'public/story.json', 'public']);
const timing = JSON.parse(fs.readFileSync('public/timing.json', 'utf8'));
fs.writeFileSync('out/props.json', JSON.stringify({story, timing, lite}));
// 3) video. Concurrency 2, jpeg frames, CRF 18. --scale=0.6667 renders 720x1280 if the laptop chokes.
const tmp = `out/${story.id}.raw.mkv`;
run('npx', ['remotion', 'render', 'src/index.ts', 'Reel', tmp, '--props=out/props.json', '--concurrency=2', '--image-format=jpeg',
  '--jpeg-quality=92', '--crf=18', '--pixel-format=yuv420p', '--audio-codec=pcm-16', '--codec=h264', `--scale=${scale}`, '--gl=swangle']);
// 4) loudness: two-pass loudnorm, linear mode, video stream copied untouched
const p1 = run('ffmpeg', ['-hide_banner', '-i', tmp, '-af', 'loudnorm=I=-14:TP=-1.0:LRA=9:print_format=json', '-f', 'null', '-'], {capture: true});
const m = JSON.parse((p1.stderr.match(/\{[\s\S]*?\}/g) || []).pop());
const af = `loudnorm=I=-14:TP=-1.0:LRA=9:measured_I=${m.input_i}:measured_TP=${m.input_tp}:measured_LRA=${m.input_lra}:measured_thresh=${m.input_thresh}:offset=${m.target_offset}:linear=true,aresample=48000`;
const final = `out/${story.id}.mp4`;
run('ffmpeg', ['-y', '-hide_banner', '-i', tmp, '-c:v', 'copy', '-af', af, '-c:a', 'aac', '-b:a', '256k', '-ar', '48000',
  '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', '-metadata:s:v', 'handler_name=', '-metadata:s:a', 'handler_name=', '-movflags', '+faststart', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', final]);
const chk = run('ffmpeg', ['-hide_banner', '-i', final, '-af', 'ebur128=peak=true', '-f', 'null', '-'], {capture: true});
console.log((chk.stderr.match(/Integrated loudness:[\s\S]*?LUFS/) || [''])[0].replace(/\s+/g, ' '), '| target -14');
fs.rmSync(tmp); console.log('✓', final);

// Optional outro: fade each side through black, then join. Only replace the reel after validation.
export const attachOutro = (reel, outro = path.resolve('outro_final.mp4')) => {
  if (!fs.existsSync(outro)) { console.log('Note: outro_final.mp4 is missing; keeping the rendered reel without an outro.'); return false; }
  let work;
  const exec = (cmd, args) => {
    const r = spawnSync(cmd, args, {encoding: 'utf8', windowsHide: true});
    if (r.error || r.status !== 0) throw new Error(`${cmd} failed`);
    return r.stdout;
  };
  const probe = (file) => JSON.parse(exec('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', file]));
  try {
    const r = probe(reel), o = probe(outro);
    const rv = r.streams.find((s) => s.codec_type === 'video'), ov = o.streams.find((s) => s.codec_type === 'video');
    const duration = (p, v) => Number(v?.duration || p.format?.duration);
    const rd = duration(r, rv), od = duration(o, ov);
    if (!rv || !ov || !r.streams.some((s) => s.codec_type === 'audio') || !o.streams.some((s) => s.codec_type === 'audio') ||
        !Number.isFinite(rd) || !Number.isFinite(od) || rd < 0.3 || od < 0.3) throw new Error('invalid or too-short video/audio input');
    work = fs.mkdtempSync(path.join(path.dirname(path.resolve(reel)), '.outro-'));
    const candidate = path.join(work, 'joined.mp4');
    const vf = 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p';
    const filter = `[0:v:0]setpts=PTS-STARTPTS,${vf},trim=duration=${rd},fade=t=out:st=${rd - 0.3}:d=0.3[v0];` +
      `[0:a:0]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,atrim=duration=${rd},afade=t=out:st=${rd - 0.3}:d=0.3[a0];` +
      `[1:v:0]setpts=PTS-STARTPTS,${vf},trim=duration=${od},fade=t=in:st=0:d=0.3[v1];` +
      `[1:a:0]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,atrim=duration=${od},afade=t=in:st=0:d=0.3[a1];` +
      '[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]';
    exec('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', '-i', reel, '-i', outro, '-filter_complex', filter,
      '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
      '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-ac', '2', '-map_metadata', '-1', '-fflags', '+bitexact',
      '-flags:a', '+bitexact', '-metadata:s:v', 'handler_name=', '-metadata:s:a', 'handler_name=', '-movflags', '+faststart',
      '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', candidate]);
    const p = probe(candidate), v = p.streams.find((s) => s.codec_type === 'video'), a = p.streams.find((s) => s.codec_type === 'audio');
    if (!v || !a || !Number.isFinite(duration(p, v)) || v.width !== 1080 || v.height !== 1920 || Math.abs(duration(p, v) - (rd + od)) > 0.25 ||
        v.avg_frame_rate !== '30/1' || a.sample_rate !== '48000' || a.channels !== 2) throw new Error('joined output validation failed');
    // Decode before commit: a partial/broken file never replaces the rendered reel.
    exec('ffmpeg', ['-v', 'error', '-xerror', '-i', candidate, '-f', 'null', '-']);
    fs.renameSync(candidate, path.resolve(reel));
    console.log('Outro attached: 0.3s reel fade-out + 0.3s outro fade-in (video and audio).');
    return true;
  } catch (e) {
    console.warn('WARNING: outro attach failed; keeping the rendered reel untouched, without an outro. ' + e.message);
    return false;
  } finally {
    if (work) { try { fs.rmSync(work, {recursive: true, force: true}); } catch { /* no change to reel */ } }
  }
};
attachOutro(final);
