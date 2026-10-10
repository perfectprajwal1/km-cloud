"""One uncached half per process, CPU only. Never reads keys or uses network."""
import argparse,json,math,subprocess,tempfile,wave
from pathlib import Path
import numpy as np
import onnxruntime as ort

def main():
    ap=argparse.ArgumentParser();ap.add_argument('model');ap.add_argument('audio');ap.add_argument('output');ap.add_argument('greedy');args=ap.parse_args()
    model=Path(args.model);audio=Path(args.audio)
    with tempfile.TemporaryDirectory(prefix='km_onnx_') as d:
        wav=Path(d)/'mono16k.wav'
        # Project already uses ffmpeg; no scipy/torch resampling dependency.
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(audio),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True)
        with wave.open(str(wav),'rb') as w:x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
    if not len(x):raise RuntimeError('Empty audio')
    x=(x-x.mean())/np.sqrt(x.var()+1e-7)
    so=ort.SessionOptions();so.intra_op_num_threads=2;so.inter_op_num_threads=1;so.enable_cpu_mem_arena=True;so.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    session=ort.InferenceSession(str(model/'nepali_int8.onnx'),sess_options=so,providers=['CPUExecutionProvider'])
    logits=session.run(None,{'input_values':x[None,:]})[0][0]
    if not np.isfinite(logits).all():raise RuntimeError('Nonfinite ONNX logits')
    y=logits-logits.max(axis=-1,keepdims=True);lp=y-np.log(np.exp(y).sum(axis=-1,keepdims=True))
    vocab=json.loads((model/'vocab.json').read_text(encoding='utf-8'));chars=[None]*65
    for ch,i in vocab.items():chars[i]=ch
    ids=logits.argmax(-1);greedy=''.join(chars[int(n)] for i,n in enumerate(ids) if n!=64 and (i==0 or ids[i-1]!=n)).replace('|',' ')
    np.save(args.output,lp);Path(args.greedy).write_text(json.dumps({'greedy':greedy},ensure_ascii=False),encoding='utf-8')
if __name__=='__main__':main()
