"""Four-camera driver view matching the original 5740 x 1010 scene scripts."""
import threading
import time
from pathlib import Path

import cv2
import numpy as np

OUTPUT_SIZE = (5740, 1010)
PREVIEW_SIZE = (1600, 281)
# CARLA positions/yaws and Pygame layout in Scene1_01.py, relative to the ego.
MIRRORS = {
    'left': dict(pose=(.6, -1, .9, -140), rect=(700, 580, 670, 420), fov=100),
    'right': dict(pose=(.6, 1, .9, 140), rect=(4719, 570, 655, 415), fov=100),
    'rear': dict(pose=(-2.2, 0, 1.35, 180), rect=(2890, 210, 650, 190), fov=120),
}
OVERLAY = Path(__file__).resolve().parents[1] / 'asset' / '123V1.0.png'


def preview_size(camera):
    """Treat the editor's size as a maximum while preserving the export aspect."""
    scale = min(camera['width']/OUTPUT_SIZE[0], camera['height']/OUTPUT_SIZE[1], 1920/OUTPUT_SIZE[0])
    return (max(1, round(OUTPUT_SIZE[0]*scale)), max(1, round(OUTPUT_SIZE[1]*scale)))


def _fit(image, size):
    return image if image.shape[1::-1] == size else cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def _driver_hud(canvas, bits):
    """Small in-image turn cue, near the lower-left side of the driver's HUD."""
    scale = canvas.shape[1] / OUTPUT_SIZE[0]
    cx, cy = int(2420 * scale), int(625 * scale)
    for bit, direction in ((32, -1), (16, 1)):
        if bits & bit:
            x = cx + int(direction * 45 * scale)
            w, h = max(6, int(26 * scale)), max(4, int(13 * scale))
            pts = np.array([(x + direction*w, cy), (x, cy-h), (x, cy-4*scale),
                            (x-direction*w, cy-4*scale), (x-direction*w, cy+4*scale),
                            (x, cy+4*scale), (x, cy+h)], dtype=np.int32)
            cv2.fillPoly(canvas, [pts], (92, 235, 91))


def compose(front, mirrors, size=OUTPUT_SIZE, overlay=None, bits=0):
    """Return BGR composite. Mirror cameras are horizontally flipped like Set_sensor.py."""
    width, height = size
    canvas = _fit(front, size).copy()
    factor_x, factor_y = width / OUTPUT_SIZE[0], height / OUTPUT_SIZE[1]
    for name, config in MIRRORS.items():
        image = mirrors.get(name)
        if image is None:
            continue
        x, y, w, h = config['rect']
        x, y = round(x*factor_x), round(y*factor_y)
        w, h = round(w*factor_x), round(h*factor_y)
        canvas[y:y+h, x:x+w] = _fit(cv2.flip(image, 1), (w, h))
    if overlay is not None:
        oh, ow = overlay.shape[:2]
        x = round(400*factor_x)
        scaled = _fit(overlay, (round(ow*factor_x), round(oh*factor_y)))
        span = min(width-x, scaled.shape[1])
        high = min(height, scaled.shape[0])
        if span > 0 and high > 0:
            src = scaled[:high, :span]
            dst = canvas[:high, x:x+span]
            alpha = src[:, :, 3:4].astype(np.uint16)
            dst[:] = ((dst.astype(np.uint16)*(255-alpha)+src[:, :, :3].astype(np.uint16)*alpha+127)//255).astype(np.uint8)
    _driver_hud(canvas, bits)
    return canvas


class DriverView:
    """Bounded camera-frame cache; output video is always 5740 x 1010."""
    def __init__(self, folder, fps, preview, preview_dimensions=PREVIEW_SIZE):
        self.folder = Path(folder)
        self.fps = fps
        self.preview = preview
        self.size = preview_dimensions if preview else OUTPUT_SIZE
        self.overlay = cv2.imread(str(OVERLAY), cv2.IMREAD_UNCHANGED)
        if self.overlay is None or self.overlay.shape[2] != 4:
            raise RuntimeError('驾驶舱透明图层不可用')
        self.condition = threading.Condition()
        self.mirrors = {name: {} for name in MIRRORS}
        self.writer = None
        self.last_index = -1
        self.video_frames = 0
        self.last_image = None
        self.first_mirror_frame = None
        self.closed = False
        self.view = 'driver'

    def reset(self):
        with self.condition:
            for values in self.mirrors.values():values.clear()

    def push_mirror(self, name, image):
        arr = np.frombuffer(image.raw_data, np.uint8).reshape(image.height, image.width, 4)[:, :, :3].copy()
        with self.condition:
            if self.closed:return
            frames = self.mirrors[name]
            frames[image.frame] = arr
            for key in sorted(frames)[:-5]:del frames[key]
            self.condition.notify_all()

    def _mirrors_for(self, frame):
        # Camera callbacks have separate streams. Wait briefly for matching
        # world frames; a late sensor may use its latest earlier frame.
        deadline = time.monotonic() + .5
        with self.condition:
            while (not self.closed and time.monotonic() < deadline and
                   any(not any(i <= frame for i in frames) for frames in self.mirrors.values())):
                self.condition.wait(timeout=max(0, deadline-time.monotonic()))
            result = {}
            for name, frames in self.mirrors.items():
                eligible = [i for i in frames if i <= frame]
                if eligible:result[name] = frames[max(eligible)]
            if len(result) == 3 and self.first_mirror_frame is None:self.first_mirror_frame = frame
            return result

    def render(self, front_image, time_s, lights=0):
        front = np.frombuffer(front_image.raw_data, np.uint8).reshape(front_image.height, front_image.width, 4)[:, :, :3]
        if self.view == 'driver':
            visible_lights = lights if time_s % 1.0 < .5 else 0
            image = compose(front, self._mirrors_for(front_image.frame), self.size, self.overlay, visible_lights)
        else:image = _fit(front,self.size).copy()
        if not self.preview:
            if self.writer is None:
                path = str(self.folder/'video.mp4')
                self.writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), self.fps, OUTPUT_SIZE)
                if not self.writer.isOpened():raise RuntimeError('无法创建 5740×1010 视频文件')
            index = max(0, round(time_s*self.fps))
            if self.last_index < 0:self.last_index = -1
            if index > self.last_index:
                for _ in range(self.last_index+1, index+1):self.writer.write(image)
                self.video_frames += index-self.last_index
                self.last_index = index
                self.last_image = image
        return image

    def close(self, final_time=None):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.writer:
            if final_time is not None and self.last_image is not None:
                last = max(self.last_index,round(final_time*self.fps))
                for _ in range(self.last_index+1,last+1):self.writer.write(self.last_image)
                self.video_frames += last-self.last_index
                self.last_index = last
            self.writer.release()
            self.writer = None
