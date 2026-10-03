"""Pygame font fallback for malformed Windows font registry entries."""
import os
from pathlib import Path
import pygame

_use_file = False


def arial(size):
    global _use_file
    if not _use_file:
        try:
            return pygame.font.SysFont('arial', size)
        except (TypeError, OSError):
            _use_file = True
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'arial.ttf'
    return pygame.font.Font(str(path) if path.is_file() else None, size)
