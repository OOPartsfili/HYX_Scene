"""会话资源、停止信号及性能记录。导入本模块不会连接 CARLA。"""
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from optimization_config import ROOT

STOP = threading.Event()
_resources = []
_lock = threading.Lock()
_closed = False
_samples = defaultdict(lambda: deque(maxlen=10000))
_counters = defaultdict(int)
_metadata = {}

class SceneStopped(Exception):
    pass

def sleep(seconds):
    if STOP.wait(seconds):
        raise SceneStopped()

def request_stop():
    STOP.set()

def register(resource, method='stop'):
    with _lock:
        _resources.append((resource, method))
    return resource


def register_thread(thread):
    """Join polling listeners before the display/input subsystem is closed."""
    class ThreadResource:
        def stop(self):
            if thread is not threading.current_thread() and thread.ident is not None:
                thread.join(timeout=2)
                if thread.is_alive():
                    raise RuntimeError(f'Listener thread {thread.name} has not stopped')
    register(ThreadResource())
    return thread

def observe(name, value):
    with _lock:
        _samples[name].append(float(value))

def count(name, value=1):
    with _lock:
        _counters[name] += value

def metadata(**values):
    with _lock:
        _metadata.update(values)

def write_metrics():
    with _lock:
        result = dict(metadata=dict(_metadata), counters=dict(_counters), samples={})
        for name, values in _samples.items():
            ordered = sorted(values)
            if ordered:
                result['samples'][name] = dict(count=len(ordered), mean=sum(ordered)/len(ordered),
                    p50=ordered[(len(ordered)-1)//2], p95=ordered[int((len(ordered)-1)*.95)],
                    max=ordered[-1])
    path = ROOT / 'optimization_reports' / ('runtime_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return path

def shutdown():
    global _closed
    if _closed:
        return
    _closed = True
    STOP.set()
    errors = []
    # 登记顺序与创建顺序一致；先停止控制，再保存数据，再销毁传感器/车辆。
    for method in ('stop', 'save_info', 'destroy', 'restore'):
        # Window.stop() 会等待显示线程结束；此期间它仍可能登记相机。
        # 每个阶段重新取登记表，确保随后 destroy 阶段也能看到这些资源。
        with _lock:
            resources = list(reversed(_resources))
        for resource, action in resources:
            if action == method:
                try:
                    result = getattr(resource, action)()
                    if action == 'destroy' and result is False:
                        raise RuntimeError('destroy returned False')
                except Exception as exc:
                    errors.append(f'{type(resource).__name__}.{action}: {exc}')
    metadata(cleanup_errors=errors)
    path = write_metrics()
    print('Performance record:', path)
    for error in errors:
        print('Cleanup error:', error)
