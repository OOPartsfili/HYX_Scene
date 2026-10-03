"""Streaming pose recordings, indexed replay and strict environment-mode checks."""
import json
from pathlib import Path
from scene_studio.timeline import motion_hash

class RecordingWriter:
    def __init__(self,folder,scene,weather):
        self.folder=Path(folder);self.scene=scene;self.weather=weather
        self.stream=(self.folder/'trajectory.jsonl').open('w',encoding='utf-8')
        self.count=0;self.last_t=0;self.paths={};self.last_sample=-1.;self.override=False
    def append(self,t,actors,control):
        clean={aid:{k:v for k,v in a.items() if k not in ('id','carla_id')} for aid,a in actors.items()}
        self.stream.write(json.dumps({'t':round(t,6),'actors':clean,'control':control},separators=(',',':'),allow_nan=False)+'\n')
        self.stream.flush();self.count+=1;self.last_t=t
        if control.get('owner')!='auto':self.override=True
        if t-self.last_sample>=max(.1,self.scene['duration']/1500)-1e-6:
            for aid,a in clean.items():self.paths.setdefault(aid,[]).append([round(t,6),a['x'],a['y'],a['z'],a['yaw'],a['speed']])
            self.last_sample=t
    def close(self,error=None):
        self.stream.close()
        value={'version':1,'id':self.folder.name,'scene':self.scene,'weather':self.weather,'dt':self.scene['dt'],'duration':self.last_t,'frame_count':self.count,'motion_hash':motion_hash(self.scene),'manual_override':self.override,'complete':error is None and self.count>1,'error':error,'paths':self.paths}
        (self.folder/'take.json').write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        return value

class Recording:
    def __init__(self,folder):
        self.folder=Path(folder);self.header=json.loads((self.folder/'take.json').read_text(encoding='utf-8'))
        if not self.header.get('complete'):raise ValueError('该次录制不完整，不能作为锁定轨迹')
        self.stream=(self.folder/'trajectory.jsonl').open('rb');self.offsets=[]
        while True:
            pos=self.stream.tell();line=self.stream.readline()
            if not line:break
            self.offsets.append(pos)
        if len(self.offsets)!=self.header['frame_count']:self.close();raise ValueError('轨迹文件不完整')
    def frame(self,index):
        index=max(0,min(len(self.offsets)-1,int(index)));self.stream.seek(self.offsets[index]);return json.loads(self.stream.readline())
    def at(self,t):return self.frame(round(t/self.header['dt']))
    def verify(self,scene):
        if motion_hash(scene)!=self.header['motion_hash']:raise ValueError('环境模式的车辆、轨迹、速度或时间轴已改变，请重新录制基准或恢复基准场景')
        return True
    def close(self):self.stream.close()
