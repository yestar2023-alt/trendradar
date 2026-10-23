#!/usr/bin/env python3
"""Small source-first pilot: persistent snapshots; no first-run new claims."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

def parse_feed(blob):
    ns={'a':'http://www.w3.org/2005/Atom','yt':'http://www.youtube.com/xml/schemas/2015'}
    root=ET.fromstring(blob)
    out={}
    for e in root.findall('a:entry', ns):
        vid=e.findtext('yt:videoId',namespaces=ns)
        if vid and len(vid)==11 and all(x.isalnum() or x in '-_' for x in vid):
            out[vid]={'title':e.findtext('a:title','',ns),'published':e.findtext('a:published','',ns),
                      'url':'https://www.youtube.com/watch?v='+vid}
    return out

def get_feed(channel):
    url='https://www.youtube.com/feeds/videos.xml?channel_id='+channel
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; AIUpstreamPilot/0.1)'})
    with urlopen(req,timeout=20) as r:
        blob=r.read(2000001)
    if len(blob)>2000000:
        raise ValueError('Oversize response')
    return parse_feed(blob)

def run(root, config, fetcher=get_feed, now=None):
    now=now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    path=root/'data/state.json'
    state=json.loads(path.read_text()) if path.exists() else {'sources':{},'videos':{}}
    report=[]
    new=[]
    success=0
    for src in config['channels']:
        name=src['name']; sid=src['id']
        try:
            entries=fetcher(src['channel_id'])
            if not entries: raise ValueError('Empty feed')
            success+=1
            old=state['sources'].get(sid)
            if old is not None:
                for video_id in sorted(set(entries)-set(old['ids'])):
                    new.append((src, video_id, entries[video_id]))
            for video_id, item in entries.items():
                state['videos'].setdefault(video_id,dict(item,first_seen=now,source=sid))
            state['sources'][sid]={'ids':sorted(entries),'last_success':now}
            report.append((name, 'OK: '+str(len(entries))+' RSS videos'))
        except Exception as exc:
            report.append((name, '抓取失败: '+type(exc).__name__+': '+str(exc)[:100]))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(state,indent=2,ensure_ascii=False))
    bj=datetime.fromisoformat(now.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
    lines=['# AI 视频上游信号（试运行）','',f'- 北京时间: {bj}',f'- 成功: {success}/{len(config["channels"])}',
           f'- 从历史成功快照观察到的新视频: {len(new)}','','首次运行只建基线；官方视频不等于 AI 新玩法。','',
           '## 来源状态','']
    lines+=['- '+name+': '+status for name,status in report]
    lines+=['','## 新视频候选','']
    for src,vid,item in new:
        lines.append(f'- [{item["title"]}]({item["url"]}) | 上传: {item["published"]} | 观察: {bj} | {src["name"]}')
    if not new: lines.append('无已确认新增（或首次基线）')
    if not success: lines.append('**数据未更新/抓取失败，不能确认今日新增。**')
    reportdir=root/'reports'
    reportdir.mkdir(parents=True,exist_ok=True)
    (reportdir/'latest.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'successful_sources':success,'new_video_urls':len(new)},ensure_ascii=False))
    return success

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    config=json.loads((args.root/'config.json').read_text())
    run(args.root,config)
