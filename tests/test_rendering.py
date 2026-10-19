"""Four-camera geometry, mirror handedness and fixed-size video output."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from scene_studio.rendering import DriverView, MIRRORS, OUTPUT_SIZE, compose, preview_size


class RenderingTests(unittest.TestCase):
    def test_reference_mirror_positions_flip_and_hud_location(self):
        front=np.zeros((1010,5740,3),np.uint8)
        mirrors={}
        for name,config in MIRRORS.items():
            _,_,w,h=config['rect']
            img=np.zeros((h,w,3),np.uint8)
            img[:,:w//2]=(0,40,100);img[:,w//2:]=(0,180,240)
            mirrors[name]=img
        composite=compose(front,mirrors,overlay=None,bits=32)
        self.assertEqual(composite.shape,(1010,5740,3))
        for config in MIRRORS.values():
            x,y,w,h=config['rect']
            self.assertEqual(tuple(composite[y+h//2,x+10]),(0,180,240))
            self.assertEqual(tuple(composite[y+h//2,x+w-10]),(0,40,100))
        self.assertGreater(int(composite[625,2375,1]),0)
        self.assertEqual(int(composite[80,2870,1]),0)

    def test_preview_is_a_smaller_canvas_with_export_aspect(self):
        size=preview_size({'width':1280,'height':720})
        self.assertEqual(size,(1280,225))
        self.assertEqual(OUTPUT_SIZE,(5740,1010))

    def test_video_writer_is_native_size_and_indexed_by_simulation_time(self):
        with tempfile.TemporaryDirectory() as folder:
            view=DriverView(folder,10,False)
            view.overlay=np.zeros((1,1,4),np.uint8)
            view._mirrors_for=lambda frame:{}
            raw=np.zeros((1010,5740,4),np.uint8).tobytes()
            image=SimpleNamespace(raw_data=raw,height=1010,width=5740,frame=1)
            view.render(image,0)
            view.render(image,.2)
            view.close()
            capture=cv2.VideoCapture(str(Path(folder)/'video.mp4'))
            self.assertTrue(capture.isOpened())
            self.assertEqual((int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))),OUTPUT_SIZE)
            self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),3)
            capture.release()


if __name__=='__main__':unittest.main()
