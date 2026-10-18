"""Render a Scene Studio draft as a directly runnable Python scene launcher."""

import json
from pathlib import Path

from scene_studio.schema import boolean, number, validate


TEMPLATE = Path(__file__).with_name('exported_scene.py.txt')


def normalized_input_config(value=None):
    """Keep the editor's input calibration with the exported run."""
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError('输入设备设置必须为对象')
    source = value.get('source', 'keyboard')
    if source not in ('keyboard', 'gamepad', 'wheel'):
        raise ValueError('输入设备类型无效')
    result = {'source': source}
    for key, default, maximum in (('index', 0, 7), ('steerAxis', 0, 31),
                                  ('throttleIndex', 7, 31), ('brakeIndex', 6, 31)):
        raw = number(value.get(key, default), 0, maximum, key)
        if raw != int(raw):
            raise ValueError(key + ' 必须为整数')
        result[key] = int(raw)
    for key, default, low, high in (('steerCenter', 0, -2, 2),
                                    ('steerSpan', 1, .1, 2), ('deadzone', .06, 0, .5),
                                    ('throttleRest', -1, -2, 2), ('throttleFull', 1, -2, 2),
                                    ('brakeRest', -1, -2, 2), ('brakeFull', 1, -2, 2)):
        result[key] = number(value.get(key, default), low, high, key)
    result['invert'] = boolean(value.get('invert', False), '转向反向')
    for key in ('throttleMode', 'brakeMode'):
        mode = value.get(key, 'button')
        if mode not in ('button', 'axis'):
            raise ValueError(key + ' 只允许按钮或轴')
        result[key] = mode
    return result


def render_python(scene, project_root, input_config=None):
    """Embed the normalized scene so the downloaded .py needs no sidecar JSON."""
    normalized = validate(scene)
    source = TEMPLATE.read_text(encoding='utf-8')
    scene_text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    config_text = json.dumps(normalized_input_config(input_config), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return (source.replace('__HYX_SCENE_LITERAL__', repr(scene_text))
                  .replace('__HYX_INPUT_CONFIG_LITERAL__', repr(config_text))
                  .replace('__HYX_PROJECT_ROOT_LITERAL__', repr(str(Path(project_root).resolve()))))
