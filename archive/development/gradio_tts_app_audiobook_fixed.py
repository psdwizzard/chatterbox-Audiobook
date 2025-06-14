import random
import numpy as np
import torch
import gradio as gr
import json
import os
import shutil
import re
import wave
from pathlib import Path
from chatterbox.tts import ChatterboxTTS
import time
from typing import List

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
# Force CPU mode for multi-voice to avoid CUDA indexing errors
MULTI_VOICE_DEVICE = "cpu"  # Force CPU for multi-voice processing

# Default voice library path
DEFAULT_VOICE_LIBRARY = "voice_library"
CONFIG_FILE = "audiobook_config.json"
MAX_CHUNKS_FOR_INTERFACE = 100 # Increased from 50 to 100, will add pagination later
MAX_CHUNKS_FOR_AUTO_SAVE = 100 # Match the interface limit for now

def load_config():
    """Load configuration including voice library path"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            return config.get('voice_library_path', DEFAULT_VOICE_LIBRARY)
        except:
            return DEFAULT_VOICE_LIBRARY
    return DEFAULT_VOICE_LIBRARY 