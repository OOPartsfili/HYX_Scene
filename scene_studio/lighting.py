"""Vehicle lamp bits shared by preview and physical runs (CARLA VehicleLightState)."""
BRAKE = 8
RIGHT = 16
LEFT = 32


def lights_at(spec, time):
    """Initial lamps, overridden only inside an enabled light clip's window.

    Lamp state is an experimental stimulus, independent of pedal commands.
    Keep all other bits so headlights and legacy hazard scenes remain intact.
    """
    value = spec.get('lights', 0)
    for clip in sorted(spec.get('clips', []), key=lambda c: (c['start'], c['id'])):
        if (clip['type'] == 'lights' and clip.get('enabled', True)
                and clip['start'] <= time < clip['start'] + clip['duration']):
            value = clip.get('value', 3)
    return value
