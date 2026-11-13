# -*- coding: utf-8 -*-
"""文件简介：一次性排查脚本——扫所有频道，列出时长 10-40 分钟（疑似能量类）的视频，用来找测试素材。"""
import io, sys, os, time
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
os.chdir(_ROOT)
from concurrent.futures import ThreadPoolExecutor, as_completed
from tarot_pipeline import pipeline as P
from tarot_pipeline import bloggers as bg, profiles as prof

cfg = P.load_config()
proxy = 'http://127.0.0.1:7890'
state = P.load_state(cfg)
bs = [b for b in bg.load_from_docx(cfg['blogger_docx']) if b.ok]
done = state.get('videos', {})
profiles = prof.load()

def scan(b):
    return P.scan_one_channel(cfg, proxy, b, done, profiles)

hits = []
t0 = time.time()
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = [ex.submit(scan, b) for b in bs]
    for fut in as_completed(futs):
        r = fut.result()
        b = r['blogger']
        for v in r['keep']:
            d = v.duration or 0
            if 600 <= d <= 2400:
                hits.append((d // 60, b.cn, v.video_id, (v.title or '')[:56]))
hits.sort()
print('elapsed %.0fs, hits %d' % (time.time() - t0, len(hits)))
for h in hits[:25]:
    print('%4dmin  %-10s %s  %s' % h)