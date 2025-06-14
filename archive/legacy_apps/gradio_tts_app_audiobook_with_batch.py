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
import torchaudio
import tempfile
import time
from typing import List
import warnings
warnings.filterwarnings("ignore")

# Try importing the TTS module
try:
    from src.chatterbox.tts import ChatterboxTTS
    CHATTERBOX_AVAILABLE = True
except ImportError as e:
    print(f"Warning: ChatterboxTTS not available - {e}")
    CHATTERBOX_AVAILABLE = False

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

def save_config(voice_library_path):
    """Save configuration including voice library path"""
    config = {
        'voice_library_path': voice_library_path,
        'last_updated': str(Path().resolve())  # timestamp
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return f"✅ Configuration saved - Voice library path: {voice_library_path}"
    except Exception as e:
        return f"❌ Error saving configuration: {str(e)}"

def set_seed(seed: int):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)

def load_model():
    model = ChatterboxTTS.from_pretrained(DEVICE)
    return model

def load_model_cpu():
    """Load model specifically for CPU processing"""
    model = ChatterboxTTS.from_pretrained("cpu")
    return model

def generate(model, text, audio_prompt_path, exaggeration, temperature, seed_num, cfgw):
    if model is None:
        model = ChatterboxTTS.from_pretrained(DEVICE)

    if seed_num != 0:
        set_seed(int(seed_num))

    wav = model.generate(
        text,
        audio_prompt_path=audio_prompt_path,
        exaggeration=exaggeration,
        temperature=temperature,
        cfg_weight=cfgw,
    )
    return (model.sr, wav.squeeze(0).numpy())

def generate_with_cpu_fallback(model, text, audio_prompt_path, exaggeration, temperature, cfg_weight):
    """Generate audio with automatic CPU fallback for problematic CUDA errors"""
    
    # First try GPU if available
    if DEVICE == "cuda":
        try:
            clear_gpu_memory()
            wav = model.generate(
                text,
                audio_prompt_path=audio_prompt_path,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
            )
            return wav, "GPU"
        except RuntimeError as e:
            if ("srcIndex < srcSelectDimSize" in str(e) or 
                "CUDA" in str(e) or 
                "out of memory" in str(e).lower()):
                
                print(f"⚠️ CUDA error detected, falling back to CPU: {str(e)[:100]}...")
                # Fall through to CPU mode
            else:
                raise e
    
    # CPU fallback or primary CPU mode
    try:
        # Load CPU model if needed
        cpu_model = ChatterboxTTS.from_pretrained("cpu")
        wav = cpu_model.generate(
            text,
            audio_prompt_path=audio_prompt_path,
            exaggeration=exaggeration,
            temperature=temperature,
            cfg_weight=cfg_weight,
        )
        return wav, "CPU"
    except Exception as e:
        raise RuntimeError(f"Both GPU and CPU generation failed: {str(e)}")

def force_cpu_processing():
    """Check if we should force CPU processing for stability"""
    # For multi-voice, always use CPU to avoid CUDA indexing issues
    return True

def chunk_text_by_sentences(text, max_words=50):
    """
    Split text into chunks, breaking at sentence boundaries after reaching max_words
    """
    # Split text into sentences using regex to handle multiple punctuation marks
    sentences = re.split(r'([.!?]+\s*)', text)
    
    chunks = []
    current_chunk = ""
    current_word_count = 0
    
    i = 0
    while i < len(sentences):
        sentence = sentences[i].strip()
        if not sentence:
            i += 1
            continue
            
        # Add punctuation if it exists
        if i + 1 < len(sentences) and re.match(r'[.!?]+\s*', sentences[i + 1]):
            sentence += sentences[i + 1]
            i += 2
        else:
            i += 1
        
        sentence_words = len(sentence.split())
        
        # If adding this sentence would exceed max_words, start new chunk
        if current_word_count > 0 and current_word_count + sentence_words > max_words:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = sentence
            current_word_count = sentence_words
        else:
            current_chunk += " " + sentence if current_chunk else sentence
            current_word_count += sentence_words
    
    # Add the last chunk if it exists
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks

def save_audio_chunks(audio_chunks, sample_rate, project_name, output_dir="audiobook_projects"):
    """
    Save audio chunks as numbered WAV files
    """
    if not project_name.strip():
        project_name = "untitled_audiobook"
    
    # Sanitize project name
    safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_project_name = safe_project_name.replace(' ', '_')
    
    # Create output directory
    project_dir = os.path.join(output_dir, safe_project_name)
    os.makedirs(project_dir, exist_ok=True)
    
    saved_files = []
    
    for i, audio_chunk in enumerate(audio_chunks, 1):
        filename = f"{safe_project_name}_{i:03d}.wav"
        filepath = os.path.join(project_dir, filename)
        
        # Save as WAV file
        with wave.open(filepath, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            
            # Convert float32 to int16
            audio_int16 = (audio_chunk * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        
        saved_files.append(filepath)
    
    return saved_files, project_dir

def ensure_voice_library_exists(voice_library_path):
    """Ensure the voice library directory exists"""
    Path(voice_library_path).mkdir(parents=True, exist_ok=True)
    return voice_library_path

def get_voice_profiles(voice_library_path):
    """Get list of saved voice profiles"""
    if not os.path.exists(voice_library_path):
        return []
    
    profiles = []
    for item in os.listdir(voice_library_path):
        profile_path = os.path.join(voice_library_path, item)
        if os.path.isdir(profile_path):
            config_file = os.path.join(profile_path, "config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    profiles.append({
                        'name': item,
                        'display_name': config.get('display_name', item),
                        'description': config.get('description', ''),
                        'config': config
                    })
                except:
                    continue
    return profiles

def get_voice_choices(voice_library_path):
    """Get voice choices for dropdown with display names"""
    profiles = get_voice_profiles(voice_library_path)
    choices = [("Manual Input (Upload Audio)", None)]  # Default option
    for profile in profiles:
        display_text = f"🎭 {profile['display_name']} ({profile['name']})"
        choices.append((display_text, profile['name']))
    return choices

def get_audiobook_voice_choices(voice_library_path):
    """Get voice choices for audiobook creation (no manual input option)"""
    profiles = get_voice_profiles(voice_library_path)
    choices = []
    if not profiles:
        choices.append(("No voices available - Create voices first", None))
    else:
        for profile in profiles:
            display_text = f"🎭 {profile['display_name']} ({profile['name']})"
            choices.append((display_text, profile['name']))
    return choices

def load_text_file(file_path):
    """Load text from uploaded file"""
    if file_path is None:
        return "No file uploaded", "❌ Please upload a text file"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Basic validation
        if not content.strip():
            return "", "❌ File is empty"
        
        word_count = len(content.split())
        char_count = len(content)
        
        status = f"✅ File loaded successfully!\n📄 {word_count:,} words | {char_count:,} characters"
        
        return content, status
        
    except UnicodeDecodeError:
        try:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            word_count = len(content.split())
            char_count = len(content)
            status = f"✅ File loaded (latin-1 encoding)!\n📄 {word_count:,} words | {char_count:,} characters"
            return content, status
        except Exception as e:
            return "", f"❌ Error reading file: {str(e)}"
    except Exception as e:
        return "", f"❌ Error loading file: {str(e)}"

def validate_audiobook_input(text_content, selected_voice, project_name):
    """Validate inputs for audiobook creation"""
    issues = []
    
    if not text_content or not text_content.strip():
        issues.append("📝 Text content is required")
    
    if not selected_voice:
        issues.append("🎭 Voice selection is required")
    
    if not project_name or not project_name.strip():
        issues.append("📁 Project name is required")
    
    if text_content and len(text_content.strip()) < 10:
        issues.append("📏 Text is too short (minimum 10 characters)")
    
    if issues:
        return (
            gr.Button("🎵 Create Audiobook", variant="primary", size="lg", interactive=False),
            "❌ Please fix these issues:\n" + "\n".join(f"• {issue}" for issue in issues), 
            gr.Audio(visible=False)
        )
    
    word_count = len(text_content.split())
    chunks = chunk_text_by_sentences(text_content)
    chunk_count = len(chunks)
    
    return (
        gr.Button("🎵 Create Audiobook", variant="primary", size="lg", interactive=True),
        f"✅ Ready for audiobook creation!\n📊 {word_count:,} words → {chunk_count} chunks\n📁 Project: {project_name.strip()}", 
        gr.Audio(visible=True)
    )

def get_voice_config(voice_library_path, voice_name):
    """Get voice configuration for audiobook generation"""
    if not voice_name:
        return None
    
    # Sanitize voice name - remove special characters that might cause issues
    safe_voice_name = voice_name.replace("_-_", "_").replace("__", "_")
    safe_voice_name = "".join(c for c in safe_voice_name if c.isalnum() or c in ('_', '-')).strip('_-')
    
    # Try original name first, then sanitized name
    for name_to_try in [voice_name, safe_voice_name]:
        profile_dir = os.path.join(voice_library_path, name_to_try)
        config_file = os.path.join(profile_dir, "config.json")
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                audio_file = None
                if config.get('audio_file'):
                    audio_path = os.path.join(profile_dir, config['audio_file'])
                    if os.path.exists(audio_path):
                        audio_file = audio_path
                
                return {
                    'audio_file': audio_file,
                    'exaggeration': config.get('exaggeration', 0.5),
                    'cfg_weight': config.get('cfg_weight', 0.5),
                    'temperature': config.get('temperature', 0.8),
                    'display_name': config.get('display_name', name_to_try)
                }
            except Exception as e:
                print(f"⚠️ Error reading config for voice '{name_to_try}': {str(e)}")
                continue
    
    return None

def clear_gpu_memory():
    """Clear GPU memory cache to prevent CUDA errors"""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

def check_gpu_memory():
    """Check GPU memory status for troubleshooting"""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated()
        cached = torch.cuda.memory_reserved()
        return f"GPU Memory - Allocated: {allocated//1024//1024}MB, Cached: {cached//1024//1024}MB"
    return "CUDA not available"

def adaptive_chunk_text(text, max_words=50, reduce_on_error=True):
    """
    Adaptive text chunking that reduces chunk size if CUDA errors occur
    """
    if reduce_on_error:
        # Start with smaller chunks for multi-voice to reduce memory pressure
        max_words = min(max_words, 35)
    
    return chunk_text_by_sentences(text, max_words)

def generate_with_retry(model, text, audio_prompt_path, exaggeration, temperature, cfg_weight, max_retries=3):
    """Generate audio with retry logic for CUDA errors"""
    for retry in range(max_retries):
        try:
            # Clear memory before generation
            if retry > 0:
                clear_gpu_memory()
            
            wav = model.generate(
                text,
                audio_prompt_path=audio_prompt_path,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
            )
            return wav
            
        except RuntimeError as e:
            if ("srcIndex < srcSelectDimSize" in str(e) or 
                "CUDA" in str(e) or 
                "out of memory" in str(e).lower()):
                
                if retry < max_retries - 1:
                    print(f"⚠️ GPU error, retry {retry + 1}/{max_retries}: {str(e)[:100]}...")
                    clear_gpu_memory()
                    continue
                else:
                    raise RuntimeError(f"Failed after {max_retries} retries: {str(e)}")
            else:
                raise e
    
    raise RuntimeError("Generation failed after all retries")

def create_audiobook(
    model,
    text_content: str,
    voice_library_path: str,
    selected_voice: str,
    project_name: str,
    resume: bool = False,
    autosave_interval: int = 10
) -> tuple:
    """
    Create audiobook from text using selected voice with smart chunking, autosave every N chunks, and resume support.
    Args:
        model: TTS model
        text_content: Full text
        voice_library_path: Path to voice library
        selected_voice: Voice name
        project_name: Project name
        resume: If True, resume from last saved chunk
        autosave_interval: Chunks per autosave (default 10)
    Returns:
        (sample_rate, combined_audio), status_message
    """
    import numpy as np
    import os
    import json
    import wave
    from typing import List

    if not text_content or not selected_voice or not project_name:
        return None, "❌ Missing required fields"

    # Get voice configuration
    voice_config = get_voice_config(voice_library_path, selected_voice)
    if not voice_config:
        return None, f"❌ Could not load voice configuration for '{selected_voice}'"
    if not voice_config['audio_file']:
        return None, f"❌ No audio file found for voice '{voice_config['display_name']}'"

    # Prepare chunking
    chunks = chunk_text_by_sentences(text_content)
    total_chunks = len(chunks)
    if total_chunks == 0:
        return None, "❌ No text chunks to process"

    # Project directory
    safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
    project_dir = os.path.join("audiobook_projects", safe_project_name)
    os.makedirs(project_dir, exist_ok=True)

    # Resume logic: find already completed chunk files
    completed_chunks = set()
    chunk_filenames = [f"{safe_project_name}_{i+1:03d}.wav" for i in range(total_chunks)]
    for idx, fname in enumerate(chunk_filenames):
        if os.path.exists(os.path.join(project_dir, fname)):
            completed_chunks.add(idx)

    # If resuming, only process missing chunks
    start_idx = 0
    if resume and completed_chunks:
        # Find first missing chunk
        for i in range(total_chunks):
            if i not in completed_chunks:
                start_idx = i
                break
        else:
            return None, "✅ All chunks already completed. Nothing to resume."
    else:
        start_idx = 0

    # Initialize model if needed
    if model is None:
        model = ChatterboxTTS.from_pretrained(DEVICE)

    audio_chunks: List[np.ndarray] = []
    status_updates = []
    clear_gpu_memory()

    # For resume, load already completed audio
    for i in range(start_idx):
        fname = os.path.join(project_dir, chunk_filenames[i])
        with wave.open(fname, 'rb') as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
            audio_chunks.append(audio_data)

    # Process missing chunks
    for i in range(start_idx, total_chunks):
        if i in completed_chunks:
            continue  # Already done
        chunk = chunks[i]
        try:
            chunk_words = len(chunk.split())
            status_msg = f"🎵 Processing chunk {i+1}/{total_chunks}\n🎭 Voice: {voice_config['display_name']}\n📝 Chunk {i+1}: {chunk_words} words\n📊 Progress: {i+1}/{total_chunks} chunks"
            status_updates.append(status_msg)
            wav = generate_with_retry(
                model,
                chunk,
                voice_config['audio_file'],
                voice_config['exaggeration'],
                voice_config['temperature'],
                voice_config['cfg_weight']
            )
            audio_np = wav.squeeze(0).cpu().numpy()
            
            # Apply volume normalization if enabled in voice profile
            if voice_config.get('normalization_enabled', False):
                target_level = voice_config.get('target_level_db', -18.0)
                try:
                    # Analyze current audio level
                    level_info = analyze_audio_level(audio_np, model.sr)
                    current_level = level_info['rms_db']
                    
                    # Normalize audio
                    audio_np = normalize_audio_to_target(audio_np, current_level, target_level)
                    print(f"🎚️ Chunk {i+1}: Volume normalized from {current_level:.1f}dB to {target_level:.1f}dB")
                except Exception as e:
                    print(f"⚠️ Volume normalization failed for chunk {i+1}: {str(e)}")
            
            audio_chunks.append(audio_np)
            # Save this chunk immediately
            fname = os.path.join(project_dir, chunk_filenames[i])
            with wave.open(fname, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(model.sr)
                audio_int16 = (audio_np * 32767).astype(np.int16)
                wav_file.writeframes(audio_int16.tobytes())
            del wav
            clear_gpu_memory()
        except Exception as chunk_error:
            return None, f"❌ Error processing chunk {i+1}: {str(chunk_error)}"
        # Autosave every N chunks
        if (i + 1) % autosave_interval == 0 or (i + 1) == total_chunks:
            # Save project metadata
            voice_info = {
                'voice_name': selected_voice,
                'display_name': voice_config['display_name'],
                'audio_file': voice_config['audio_file'],
                'exaggeration': voice_config['exaggeration'],
                'cfg_weight': voice_config['cfg_weight'],
                'temperature': voice_config['temperature']
            }
            save_project_metadata(
                project_dir=project_dir,
                project_name=project_name,
                text_content=text_content,
                voice_info=voice_info,
                chunks=chunks,
                project_type="single_voice"
            )
    # Combine all audio for preview (just concatenate)
    combined_audio = np.concatenate(audio_chunks)
    total_words = len(text_content.split())
    duration_minutes = len(combined_audio) // model.sr // 60
    success_msg = f"✅ Audiobook created successfully!\n🎭 Voice: {voice_config['display_name']}\n📊 {total_words:,} words in {total_chunks} chunks\n⏱️ Duration: ~{duration_minutes} minutes\n📁 Saved to: {project_dir}\n🎵 Files: {len(audio_chunks)} audio chunks\n💾 Metadata saved for regeneration"
    return (model.sr, combined_audio), success_msg

def load_voice_for_tts(voice_library_path, voice_name):
    """Load a voice profile for TTS tab - returns settings for sliders"""
    if not voice_name:
        # Return to manual input mode
        return None, 0.5, 0.5, 0.8, gr.Audio(visible=True), "📝 Manual input mode - upload your own audio file below"
    
    profile_dir = os.path.join(voice_library_path, voice_name)
    config_file = os.path.join(profile_dir, "config.json")
    
    if not os.path.exists(config_file):
        return None, 0.5, 0.5, 0.8, gr.Audio(visible=True), f"❌ Voice profile '{voice_name}' not found"
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        audio_file = None
        if config.get('audio_file'):
            audio_path = os.path.join(profile_dir, config['audio_file'])
            if os.path.exists(audio_path):
                audio_file = audio_path
        
        # Hide manual audio upload when using saved voice
        audio_component = gr.Audio(visible=False) if audio_file else gr.Audio(visible=True)
        
        status_msg = f"✅ Using voice: {config.get('display_name', voice_name)}"
        if config.get('description'):
            status_msg += f" - {config['description']}"
        
        return (
            audio_file,
            config.get('exaggeration', 0.5),
            config.get('cfg_weight', 0.5),
            config.get('temperature', 0.8),
            audio_component,
            status_msg
        )
    except Exception as e:
        return None, 0.5, 0.5, 0.8, gr.Audio(visible=True), f"❌ Error loading voice profile: {str(e)}"

def save_voice_profile(voice_library_path, voice_name, display_name, description, audio_file, exaggeration, cfg_weight, temperature, enable_normalization=False, target_level_db=-18.0):
    """Save a voice profile with its settings and optional volume normalization"""
    if not voice_name:
        return "❌ Error: Voice name cannot be empty"
    
    # Sanitize voice name for folder
    safe_name = "".join(c for c in voice_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_name = safe_name.replace(' ', '_')
    
    if not safe_name:
        return "❌ Error: Invalid voice name"
    
    ensure_voice_library_exists(voice_library_path)
    
    profile_dir = os.path.join(voice_library_path, safe_name)
    os.makedirs(profile_dir, exist_ok=True)
    
    # Handle audio file and volume normalization
    audio_path = None
    normalization_applied = False
    original_level_info = None
    
    if audio_file:
        audio_ext = os.path.splitext(audio_file)[1]
        audio_path = os.path.join(profile_dir, f"reference{audio_ext}")
        
        # Apply volume normalization if enabled
        if enable_normalization:
            try:
                # Load and analyze original audio
                audio_data, sample_rate = librosa.load(audio_file, sr=24000)
                original_level_info = analyze_audio_level(audio_data, sample_rate)
                
                # Normalize audio
                normalized_audio = normalize_audio_to_target(
                    audio_data, 
                    original_level_info['rms_db'], 
                    target_level_db, 
                    method='rms'
                )
                
                # Save normalized audio
                sf.write(audio_path, normalized_audio, sample_rate)
                normalization_applied = True
                print(f"🎚️ Applied volume normalization: {original_level_info['rms_db']:.1f} dB → {target_level_db:.1f} dB")
                
            except Exception as e:
                print(f"⚠️ Volume normalization failed, using original audio: {str(e)}")
                # Fall back to copying original file
                shutil.copy2(audio_file, audio_path)
                normalization_applied = False
        else:
            # Copy original file without normalization
            shutil.copy2(audio_file, audio_path)
            
        # Store relative path
        audio_path = f"reference{audio_ext}"
    
    # Save configuration with normalization info
    config = {
        "display_name": display_name or voice_name,
        "description": description or "",
        "audio_file": audio_path,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "temperature": temperature,
        "created_date": str(time.time()),
        # Volume normalization settings
        "normalization_enabled": enable_normalization,
        "target_level_db": target_level_db,
        "normalization_applied": normalization_applied,
        "original_level_info": original_level_info,
        "version": "2.0"  # Updated version to include normalization
    }
    
    config_file = os.path.join(profile_dir, "config.json")
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    
    # Prepare result message
    result_msg = f"✅ Voice profile '{display_name or voice_name}' saved successfully!"
    if original_level_info and normalization_applied:
        result_msg += f"\n📊 Audio normalized from {original_level_info['rms_db']:.1f} dB to {target_level_db:.1f} dB"
    elif original_level_info:
        result_msg += f"\n📊 Original audio level: {original_level_info['rms_db']:.1f} dB RMS"
    
    return result_msg

def load_voice_profile(voice_library_path, voice_name):
    """Load a voice profile and return its settings"""
    if not voice_name:
        return None, 0.5, 0.5, 0.8, "No voice selected"
    
    profile_dir = os.path.join(voice_library_path, voice_name)
    config_file = os.path.join(profile_dir, "config.json")
    
    if not os.path.exists(config_file):
        return None, 0.5, 0.5, 0.8, f"❌ Voice profile '{voice_name}' not found"
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        audio_file = None
        if config.get('audio_file'):
            audio_path = os.path.join(profile_dir, config['audio_file'])
            if os.path.exists(audio_path):
                audio_file = audio_path
        
        return (
            audio_file,
            config.get('exaggeration', 0.5),
            config.get('cfg_weight', 0.5),
            config.get('temperature', 0.8),
            f"✅ Loaded voice profile: {config.get('display_name', voice_name)}"
        )
    except Exception as e:
        return None, 0.5, 0.5, 0.8, f"❌ Error loading voice profile: {str(e)}"

def delete_voice_profile(voice_library_path, voice_name):
    """Delete a voice profile"""
    if not voice_name:
        return "❌ No voice selected", []
    
    profile_dir = os.path.join(voice_library_path, voice_name)
    if os.path.exists(profile_dir):
        try:
            shutil.rmtree(profile_dir)
            return f"✅ Voice profile '{voice_name}' deleted successfully!", get_voice_profiles(voice_library_path)
        except Exception as e:
            return f"❌ Error deleting voice profile: {str(e)}", get_voice_profiles(voice_library_path)
    else:
        return f"❌ Voice profile '{voice_name}' not found", get_voice_profiles(voice_library_path)

def refresh_voice_list(voice_library_path):
    """Refresh the voice profile list"""
    profiles = get_voice_profiles(voice_library_path)
    choices = [p['name'] for p in profiles]
    return gr.Dropdown(choices=choices, value=choices[0] if choices else None)

def refresh_voice_choices(voice_library_path):
    """Refresh voice choices for TTS dropdown"""
    choices = get_voice_choices(voice_library_path)
    return gr.Dropdown(choices=choices, value=None)

def refresh_audiobook_voice_choices(voice_library_path):
    """Refresh voice choices for audiobook creation"""
    choices = get_audiobook_voice_choices(voice_library_path)
    return gr.Dropdown(choices=choices, value=choices[0][1] if choices and choices[0][1] else None)

def update_voice_library_path(new_path):
    """Update the voice library path and save to config"""
    if not new_path.strip():
        return DEFAULT_VOICE_LIBRARY, "❌ Path cannot be empty, using default", refresh_voice_list(DEFAULT_VOICE_LIBRARY), refresh_voice_choices(DEFAULT_VOICE_LIBRARY), refresh_audiobook_voice_choices(DEFAULT_VOICE_LIBRARY)
    
    # Ensure the directory exists
    ensure_voice_library_exists(new_path)
    
    # Save to config
    save_msg = save_config(new_path)
    
    # Return updated components
    return (
        new_path,  # Update the state
        save_msg,  # Status message
        refresh_voice_list(new_path),  # Updated voice dropdown
        refresh_voice_choices(new_path),  # Updated TTS choices
        refresh_audiobook_voice_choices(new_path)  # Updated audiobook choices
    )

def parse_multi_voice_text(text):
    """
    Parse text with voice tags like [voice_name] and return segments with associated voices
    Automatically removes character names from spoken text when they match the voice tag
    Returns: [(voice_name, text_segment), ...]
    """
    import re
    
    # Split text by voice tags but keep the tags
    pattern = r'(\[([^\]]+)\])'
    parts = re.split(pattern, text)
    
    segments = []
    current_voice = None
    
    i = 0
    while i < len(parts):
        part = parts[i].strip()
        
        if not part:
            i += 1
            continue
            
        # Check if this is a voice tag
        if part.startswith('[') and part.endswith(']'):
            # This is a voice tag
            current_voice = part[1:-1]  # Remove brackets
            i += 1
        else:
            # This is text content
            if part and current_voice:
                # Clean the text by removing character name if it matches the voice tag
                cleaned_text = clean_character_name_from_text(part, current_voice)
                # Only add non-empty segments after cleaning
                if cleaned_text.strip():
                    segments.append((current_voice, cleaned_text))
                else:
                    print(f"[DEBUG] Skipping empty segment after cleaning for voice '{current_voice}'")
            elif part:
                # Text without voice tag - use default
                segments.append((None, part))
            i += 1
    
    return segments

def clean_character_name_from_text(text, voice_name):
    """
    Remove character name from the beginning of text if it matches the voice name
    Handles various formats like 'P1', 'P1:', 'P1 -', etc.
    """
    text = text.strip()
    
    # If the entire text is just the voice name (with possible punctuation), return empty
    if text.lower().replace(':', '').replace('.', '').replace('-', '').strip() == voice_name.lower():
        print(f"[DEBUG] Text is just the voice name '{voice_name}', returning empty")
        return ""
    
    # Create variations of the voice name to check for
    voice_variations = [
        voice_name,                    # af_sarah
        voice_name.upper(),            # AF_SARAH  
        voice_name.lower(),            # af_sarah
        voice_name.capitalize(),       # Af_sarah
    ]
    
    # Also add variations without underscores for more flexible matching
    for voice_var in voice_variations[:]:
        if '_' in voice_var:
            voice_variations.append(voice_var.replace('_', ' '))  # af sarah
            voice_variations.append(voice_var.replace('_', ''))   # afsarah
    
    for voice_var in voice_variations:
        # Check for various patterns:
        # "af_sarah text..." -> "text..."
        # "af_sarah: text..." -> "text..."
        # "af_sarah - text..." -> "text..."
        # "af_sarah. text..." -> "text..."
        patterns = [
            rf'^{re.escape(voice_var)}\s+',      # "af_sarah "
            rf'^{re.escape(voice_var)}:\s*',     # "af_sarah:" or "af_sarah: "
            rf'^{re.escape(voice_var)}\.\s*',    # "af_sarah." or "af_sarah. "
            rf'^{re.escape(voice_var)}\s*-\s*',  # "af_sarah -" or "af_sarah-"
            rf'^{re.escape(voice_var)}\s*\|\s*', # "af_sarah |" or "af_sarah|"
            rf'^{re.escape(voice_var)}\s*\.\.\.', # "af_sarah..."
        ]
        
        for pattern in patterns:
            if re.match(pattern, text, re.IGNORECASE):
                # Remove the matched pattern and return the remaining text
                cleaned = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
                print(f"[DEBUG] Cleaned text for voice '{voice_name}': '{text[:50]}...' -> '{cleaned[:50] if cleaned else '(empty)'}'")
                return cleaned
    
    # If no character name pattern found, return original text
    return text

def chunk_multi_voice_segments(segments, max_words=50):
    """
    Take voice segments and chunk them appropriately while preserving voice assignments
    Returns: [(voice_name, chunk_text), ...]
    """
    final_chunks = []
    
    for voice_name, text in segments:
        # Chunk this segment using the same sentence boundary logic
        text_chunks = chunk_text_by_sentences(text, max_words)
        
        # Add voice assignment to each chunk
        for chunk in text_chunks:
            final_chunks.append((voice_name, chunk))
    
    return final_chunks

def validate_multi_voice_text(text_content, voice_library_path):
    """
    Validate multi-voice text and check if all referenced voices exist
    Returns: (is_valid, message, voice_counts)
    """
    if not text_content or not text_content.strip():
        return False, "❌ Text content is required", {}
    
    # Parse the text to find voice references
    segments = parse_multi_voice_text(text_content)
    
    if not segments:
        return False, "❌ No valid voice segments found", {}
    
    # Count voice usage and check availability
    voice_counts = {}
    missing_voices = []
    available_voices = [p['name'] for p in get_voice_profiles(voice_library_path)]
    
    for voice_name, text_segment in segments:
        if voice_name is None:
            voice_name = "No Voice Tag"
        
        if voice_name not in voice_counts:
            voice_counts[voice_name] = 0
        voice_counts[voice_name] += len(text_segment.split())
        
        # Check if voice exists (skip None/default)
        if voice_name != "No Voice Tag" and voice_name not in available_voices:
            if voice_name not in missing_voices:
                missing_voices.append(voice_name)
    
    if missing_voices:
        return False, f"❌ Missing voices: {', '.join(missing_voices)}", voice_counts
    
    if "No Voice Tag" in voice_counts:
        return False, "❌ Found text without voice tags. All text must be assigned to a voice using [voice_name]", voice_counts
    
    return True, "✅ All voices found and text properly tagged", voice_counts

def validate_multi_audiobook_input(text_content, voice_library_path, project_name):
    """Validate inputs for multi-voice audiobook creation"""
    issues = []
    
    if not project_name or not project_name.strip():
        issues.append("📁 Project name is required")
    
    if text_content and len(text_content.strip()) < 10:
        issues.append("📏 Text is too short (minimum 10 characters)")
    
    # Validate voice parsing
    is_valid, voice_message, voice_counts = validate_multi_voice_text(text_content, voice_library_path)
    
    if not is_valid:
        issues.append(voice_message)
    
    if issues:
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            "❌ Please fix these issues:\n" + "\n".join(f"• {issue}" for issue in issues),
            "",
            gr.Audio(visible=False)
        )
    
    # Show voice breakdown
    voice_breakdown = "\n".join([f"🎭 {voice}: {words} words" for voice, words in voice_counts.items()])
    chunks = chunk_multi_voice_segments(parse_multi_voice_text(text_content))
    total_words = sum(voice_counts.values())
    
    return (
        gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=True),
        f"✅ Ready for multi-voice audiobook creation!\n📊 {total_words:,} total words → {len(chunks)} chunks\n📁 Project: {project_name.strip()}\n\n{voice_breakdown}",
        voice_breakdown,
        gr.Audio(visible=True)
    )

def create_multi_voice_audiobook(model, text_content, voice_library_path, project_name):
    """Create multi-voice audiobook from tagged text"""
    if not text_content or not project_name:
        return None, "❌ Missing required fields"
    
    try:
        # Parse and validate the text
        is_valid, message, voice_counts = validate_multi_voice_text(text_content, voice_library_path)
        if not is_valid:
            return None, f"❌ Text validation failed: {message}"
        
        # Get voice segments and chunk them
        segments = parse_multi_voice_text(text_content)
        chunks = chunk_multi_voice_segments(segments, max_words=50)
        total_chunks = len(chunks)
        
        if total_chunks == 0:
            return None, "❌ No text chunks to process"
        
        # Initialize model if needed
        if model is None:
            model = ChatterboxTTS.from_pretrained(DEVICE)
        
        audio_chunks = []
        chunk_info = []  # For saving metadata
        
        for i, (voice_name, chunk_text) in enumerate(chunks, 1):
            # Get voice configuration
            voice_config = get_voice_config(voice_library_path, voice_name)
            if not voice_config:
                return None, f"❌ Could not load voice configuration for '{voice_name}'"
            
            if not voice_config['audio_file']:
                return None, f"❌ No audio file found for voice '{voice_config['display_name']}'"
            
            # Update status (this would be shown in real implementation)
            chunk_words = len(chunk_text.split())
            status_msg = f"🎵 Processing chunk {i}/{total_chunks}\n🎭 Voice: {voice_config['display_name']} ({voice_name})\n📝 Chunk {i}: {chunk_words} words\n📊 Progress: {i}/{total_chunks} chunks"
            
            # Generate audio for this chunk
            wav = model.generate(
                chunk_text,
                audio_prompt_path=voice_config['audio_file'],
                exaggeration=voice_config['exaggeration'],
                temperature=voice_config['temperature'],
                cfg_weight=voice_config['cfg_weight'],
            )
            
            audio_np = wav.squeeze(0).numpy()
            audio_chunks.append(audio_np)
            chunk_info.append({
                'chunk_num': i,
                'voice_name': voice_name,
                'character_name': voice_name,
                'voice_display': voice_config['display_name'],
                'text': chunk_text[:100] + "..." if len(chunk_text) > 100 else chunk_text,
                'word_count': chunk_words
            })
        
        # Save all chunks with voice info in filenames
        saved_files, project_dir = save_audio_chunks(audio_chunks, model.sr, project_name)
        
        # Combine all audio for preview
        combined_audio = np.concatenate(audio_chunks)
        
        total_words = sum([info['word_count'] for info in chunk_info])
        duration_minutes = len(combined_audio) // model.sr // 60
        
        # Create assignment summary
        assignment_summary = "\n".join([f"🎭 [{char}] → {voice_counts[char]}" for char in voice_counts.keys()])
        
        success_msg = f"✅ Multi-voice audiobook created successfully!\n📊 {total_words:,} words in {total_chunks} chunks\n🎭 Characters: {len(voice_counts)}\n⏱️ Duration: ~{duration_minutes} minutes\n📁 Saved to: {project_dir}\n🎵 Files: {len(saved_files)} audio chunks\n\nVoice Assignments:\n{assignment_summary}"
        
        return (model.sr, combined_audio), success_msg
        
    except Exception as e:
        error_msg = f"❌ Error creating multi-voice audiobook: {str(e)}"
        return None, error_msg

def analyze_multi_voice_text(text_content, voice_library_path):
    """
    Analyze multi-voice text and return character breakdown with voice assignment interface
    """
    if not text_content or not text_content.strip():
        return "", {}, gr.Group(visible=False), "❌ No text to analyze"
    
    # Parse the text to find voice references
    segments = parse_multi_voice_text(text_content)
    
    if not segments:
        return "", {}, gr.Group(visible=False), "❌ No voice tags found in text"
    
    # Count voice usage
    voice_counts = {}
    for voice_name, text_segment in segments:
        if voice_name is None:
            voice_name = "No Voice Tag"
        
        if voice_name not in voice_counts:
            voice_counts[voice_name] = 0
        voice_counts[voice_name] += len(text_segment.split())
    
    # Create voice breakdown display
    if "No Voice Tag" in voice_counts:
        breakdown_text = "❌ Found text without voice tags:\n"
        breakdown_text += f"• No Voice Tag: {voice_counts['No Voice Tag']} words\n"
        breakdown_text += "\nAll text must be assigned to a voice using [voice_name] tags!"
        return breakdown_text, voice_counts, gr.Group(visible=False), "❌ Text contains untagged content"
    
    breakdown_text = "✅ Voice tags found:\n"
    for voice, words in voice_counts.items():
        breakdown_text += f"🎭 [{voice}]: {words} words\n"
    
    return breakdown_text, voice_counts, gr.Group(visible=True), "✅ Analysis complete - assign voices below"

def create_assignment_interface_with_dropdowns(voice_counts, voice_library_path):
    """
    Create actual Gradio dropdown components for each character
    Returns the components and character names for proper handling
    """
    if not voice_counts or "No Voice Tag" in voice_counts:
        return [], [], "<div class='voice-status'>❌ No valid characters found</div>"
    
    # Get available voices
    available_voices = get_voice_profiles(voice_library_path)
    
    if not available_voices:
        return [], [], "<div class='voice-status'>❌ No voices available in library. Create voices first!</div>"
    
    # Create voice choices for dropdowns
    voice_choices = [("Select a voice...", None)]
    for voice in available_voices:
        display_text = f"🎭 {voice['display_name']} ({voice['name']})"
        voice_choices.append((display_text, voice['name']))
    
    # Create components for each character
    dropdown_components = []
    character_names = []
    
    for character_name, word_count in voice_counts.items():
        if character_name != "No Voice Tag":
            dropdown = gr.Dropdown(
                choices=voice_choices,
                label=f"Voice for [{character_name}] ({word_count} words)",
                value=None,
                interactive=True,
                info=f"Select which voice to use for character '{character_name}'"
            )
            dropdown_components.append(dropdown)
            character_names.append(character_name)
    
    # Create info display
    info_html = f"<div class='voice-status'>✅ Found {len(character_names)} characters. Select voices for each character using the dropdowns below.</div>"
    
    return dropdown_components, character_names, info_html

def validate_dropdown_assignments(text_content, voice_library_path, project_name, voice_counts, character_names, *dropdown_values):
    """
    Validate voice assignments from dropdown values
    """
    if not voice_counts or "No Voice Tag" in voice_counts:
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            "❌ Invalid text or voice tags",
            {},
            gr.Audio(visible=False)
        )
    
    if not project_name or not project_name.strip():
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            "❌ Project name is required",
            {},
            gr.Audio(visible=False)
        )
    
    if len(dropdown_values) != len(character_names):
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            f"❌ Assignment mismatch: {len(character_names)} characters, {len(dropdown_values)} dropdown values",
            {},
            gr.Audio(visible=False)
        )
    
    # Create voice assignments mapping from dropdown values
    voice_assignments = {}
    missing_assignments = []
    
    for i, character in enumerate(character_names):
        assigned_voice = dropdown_values[i] if i < len(dropdown_values) else None
        if not assigned_voice:
            missing_assignments.append(character)
        else:
            voice_assignments[character] = assigned_voice
    
    if missing_assignments:
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            f"❌ Please assign voices for: {', '.join(missing_assignments)}",
            voice_assignments,
            gr.Audio(visible=False)
        )
    
    # All assignments valid
    total_words = sum(voice_counts.values())
    assignment_summary = "\n".join([f"🎭 [{char}] → {voice_assignments[char]}" for char in character_names])
    
    return (
        gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=True),
        f"✅ All characters assigned!\n📊 {total_words:,} words total\n📁 Project: {project_name.strip()}\n\nAssignments:\n{assignment_summary}",
        voice_assignments,
        gr.Audio(visible=True)
    )

def get_model_device_str(model_obj):
    """Safely get the device string ("cuda" or "cpu") from a model object."""
    if not model_obj or not hasattr(model_obj, 'device'):
        # print("⚠️ Model object is None or has no device attribute.")
        return None 
    
    device_attr = model_obj.device
    if isinstance(device_attr, torch.device):
        return device_attr.type
    elif isinstance(device_attr, str):
        if device_attr in ["cuda", "cpu"]:
            return device_attr
        else:
            print(f"⚠️ Unexpected string for model.device: {device_attr}")
            return None 
    else:
        print(f"⚠️ Unexpected type for model.device: {type(device_attr)}")
        return None

def _filter_problematic_short_chunks(chunks, voice_assignments):
    """Helper to filter out very short chunks that likely represent only character tags."""
    if not chunks:
        return []

    filtered_chunks = []
    # Extract just the keys from voice_assignments, which are the character tags like 'af_sarah', 'af_aoede'
    # Ensure keys are strings and lowercased for consistent matching.
    known_char_tags = [str(tag).lower().strip() for tag in voice_assignments.keys()]
    original_chunk_count = len(chunks)

    for chunk_idx, chunk_info in enumerate(chunks):
        # Handle tuple format: (voice_name, text)
        if isinstance(chunk_info, tuple) and len(chunk_info) == 2:
            voice_name, text = chunk_info
            if not isinstance(text, str):
                print(f"⚠️ Skipping chunk with non-string text at index {chunk_idx}: {chunk_info}")
                filtered_chunks.append(chunk_info)
                continue
                
            text_to_check = text.strip().lower()
            is_problematic_tag_chunk = False
            
            # Check if text is just the voice name or character tag (with possible punctuation)
            # This handles cases like "af_sarah", "af_sarah.", "af_sarah...", etc.
            cleaned_for_check = text_to_check.replace('_', '').replace('-', '').replace('.', '').replace(':', '').strip()
            
            # Check against known character tags
            for tag in known_char_tags:
                tag_cleaned = tag.replace('_', '').replace('-', '').strip()
                if cleaned_for_check == tag_cleaned:
                    is_problematic_tag_chunk = True
                    break
            
            # Also check if it's very short and matches a tag pattern
            if not is_problematic_tag_chunk and 1 <= len(text_to_check) <= 20:
                # More robust check for tag-like patterns
                core_text_segment = text_to_check
                # Strip common endings
                for ending in ["...", "..", ".", ":", "-", "_"]:
                    if core_text_segment.endswith(ending):
                        core_text_segment = core_text_segment[:-len(ending)]
                
                # Check if what remains is a known character tag
                if core_text_segment in known_char_tags:
                    is_problematic_tag_chunk = True
            
            if is_problematic_tag_chunk:
                print(f"⚠️ Filtering out suspected tag-only chunk {chunk_idx+1}/{original_chunk_count} for voice '{voice_name}': '{text}'")
            else:
                filtered_chunks.append(chunk_info)
        else:
            # Handle unexpected format
            print(f"⚠️ Unexpected chunk format at index {chunk_idx}: {chunk_info}")
            filtered_chunks.append(chunk_info)
            
    if len(filtered_chunks) < original_chunk_count:
        print(f"ℹ️ Filtered {original_chunk_count - len(filtered_chunks)} problematic short chunk(s) out of {original_chunk_count}.")
    
    return filtered_chunks

def create_multi_voice_audiobook_with_assignments(
    model,
    text_content: str,
    voice_library_path: str,
    project_name: str,
    voice_assignments: dict,
    resume: bool = False,
    autosave_interval: int = 10
) -> tuple:
    """
    Create multi-voice audiobook using the voice assignments mapping, autosave every N chunks, and resume support.
    Args:
        model: TTS model
        text_content: Full text
        voice_library_path: Path to voice library
        project_name: Project name
        voice_assignments: Character to voice mapping
        resume: If True, resume from last saved chunk
        autosave_interval: Chunks per autosave (default 10)
    Returns:
        (sample_rate, combined_audio), status_message
    """
    import numpy as np
    import os
    import json
    import wave
    from typing import List

    if not text_content or not project_name or not voice_assignments:
        error_msg = "❌ Missing required fields or voice assignments. Ensure text is entered, project name is set, and voices are assigned after analyzing text."
        return None, None, error_msg, None

    # Parse the text and map voices
    segments = parse_multi_voice_text(text_content)
    mapped_segments = []
    for character_name, text_segment in segments:
        if character_name in voice_assignments:
            actual_voice = voice_assignments[character_name]
            mapped_segments.append((actual_voice, text_segment))
        else:
            return None, None, f"❌ No voice assignment found for character '{character_name}'", None

    initial_max_words = 30 if DEVICE == "cuda" else 40
    chunks = chunk_multi_voice_segments(mapped_segments, max_words=initial_max_words)
    chunks = _filter_problematic_short_chunks(chunks, voice_assignments)
    total_chunks = len(chunks)
    if not chunks:
        return None, None, "❌ No text chunks to process", None

    # Project directory
    safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
    project_dir = os.path.join("audiobook_projects", safe_project_name)
    os.makedirs(project_dir, exist_ok=True)

    # Resume logic: find already completed chunk files
    completed_chunks = set()
    chunk_filenames = []
    chunk_info = []
    for i, (voice_name, chunk_text) in enumerate(chunks):
        character_name = None
        for char_key, assigned_voice_val in voice_assignments.items():
            if assigned_voice_val == voice_name:
                character_name = char_key
                break
        character_name_file = character_name.replace(' ', '_') if character_name else voice_name
        filename = f"{safe_project_name}_{i+1:03d}_{character_name_file}.wav"
        chunk_filenames.append(filename)
        if os.path.exists(os.path.join(project_dir, filename)):
            completed_chunks.add(i)
        chunk_info.append({
            'chunk_num': i+1, 'voice_name': voice_name, 'character_name': character_name or voice_name,
            'voice_display': voice_name, 'text': chunk_text[:100] + "..." if len(chunk_text) > 100 else chunk_text,
            'word_count': len(chunk_text.split())
        })

    # If resuming, only process missing chunks
    start_idx = 0
    if resume and completed_chunks:
        for i in range(total_chunks):
            if i not in completed_chunks:
                start_idx = i
                break
        else:
            return None, None, "✅ All chunks already completed. Nothing to resume.", None
    else:
        start_idx = 0

    # Initialize model if needed
    processing_model = model
    if processing_model is None:
        processing_model = ChatterboxTTS.from_pretrained(DEVICE)

    audio_chunks: List[np.ndarray] = []
    # For resume, load already completed audio
    for i in range(start_idx):
        fname = os.path.join(project_dir, chunk_filenames[i])
        with wave.open(fname, 'rb') as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
            audio_chunks.append(audio_data)

    # Process missing chunks
    for i in range(start_idx, total_chunks):
        if i in completed_chunks:
            continue
        voice_name, chunk_text = chunks[i]
        try:
            voice_config = get_voice_config(voice_library_path, voice_name)
            if not voice_config:
                return None, None, f"❌ Could not load voice config for '{voice_name}'", None
            if not voice_config['audio_file']:
                return None, None, f"❌ No audio file for voice '{voice_config['display_name']}'", None
            if not os.path.exists(voice_config['audio_file']):
                return None, None, f"❌ Audio file not found: {voice_config['audio_file']}", None
            wav = processing_model.generate(
                chunk_text, audio_prompt_path=voice_config['audio_file'],
                exaggeration=voice_config['exaggeration'], temperature=voice_config['temperature'],
                cfg_weight=voice_config['cfg_weight'])
            audio_np = wav.squeeze(0).cpu().numpy()
            
            # Apply volume normalization if enabled in voice profile
            if voice_config.get('normalization_enabled', False):
                target_level = voice_config.get('target_level_db', -18.0)
                try:
                    # Analyze current audio level
                    level_info = analyze_audio_level(audio_np, model.sr)
                    current_level = level_info['rms_db']
                    
                    # Normalize audio
                    audio_np = normalize_audio_to_target(audio_np, current_level, target_level)
                    print(f"🎚️ Chunk {i+1}: Volume normalized from {current_level:.1f}dB to {target_level:.1f}dB")
                except Exception as e:
                    print(f"⚠️ Volume normalization failed for chunk {i+1}: {str(e)}")
            
            audio_chunks.append(audio_np)
            # Save this chunk immediately
            fname = os.path.join(project_dir, chunk_filenames[i])
            with wave.open(fname, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(processing_model.sr)
                audio_int16 = (audio_np * 32767).astype(np.int16)
                wav_file.writeframes(audio_int16.tobytes())
            del wav
            if get_model_device_str(processing_model) == 'cuda':
                torch.cuda.empty_cache()
        except Exception as chunk_error_outer:
            return None, None, f"❌ Outer error processing chunk {i+1} (voice: {voice_name}): {str(chunk_error_outer)}", None
        # Autosave every N chunks
        if (i + 1) % autosave_interval == 0 or (i + 1) == total_chunks:
            # Save project metadata
            metadata_file = os.path.join(project_dir, "project_info.json")
            with open(metadata_file, 'w') as f:
                json.dump({
                    'project_name': project_name, 'total_chunks': total_chunks,
                    'final_processing_mode': 'CPU' if DEVICE == 'cpu' else 'GPU',
                    'voice_assignments': voice_assignments, 'characters': list(voice_assignments.keys()),
                    'chunks': chunk_info
                }, f, indent=2)
    # Combine all audio for preview (just concatenate)
    combined_audio = np.concatenate(audio_chunks)
    total_words = sum(len(chunk[1].split()) for chunk in chunks)
    duration_minutes = len(combined_audio) // processing_model.sr // 60
    assignment_summary = "\n".join([f"🎭 [{char}] → {assigned_voice}" for char, assigned_voice in voice_assignments.items()])
    success_msg = (f"✅ Multi-voice audiobook created successfully!\n"
                   f"📊 {total_words:,} words in {total_chunks} chunks\n"
                   f"🎭 Characters: {len(voice_assignments)}\n"
                   f"⏱️ Duration: ~{duration_minutes} minutes\n"
                   f"📁 Saved to: {project_dir}\n"
                   f"🎵 Files: {len(audio_chunks)} audio chunks\n"
                   f"\nVoice Assignments:\n{assignment_summary}")
    return (processing_model.sr, combined_audio), None, success_msg, None

def handle_multi_voice_analysis(text_content, voice_library_path):
    """
    Analyze multi-voice text and populate character dropdowns
    Returns updated dropdown components
    """
    if not text_content or not text_content.strip():
        # Reset all dropdowns to hidden
        empty_dropdown = gr.Dropdown(choices=[("No character found", None)], visible=False, interactive=False)
        return (
            "<div class='voice-status'>❌ No text to analyze</div>",
            {},
            [],
            empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown,
            gr.Button("🔍 Validate Voice Assignments", interactive=False),
            "❌ Add text first"
        )
    
    # Parse the text to find voice references
    breakdown_text, voice_counts, group_visibility, status = analyze_multi_voice_text(text_content, voice_library_path)
    
    if not voice_counts or "No Voice Tag" in voice_counts:
        # Reset all dropdowns to hidden
        empty_dropdown = gr.Dropdown(choices=[("No character found", None)], visible=False, interactive=False)
        return (
            breakdown_text,
            voice_counts,
            [],
            empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown,
            gr.Button("🔍 Validate Voice Assignments", interactive=False),
            "❌ No voices in library"
        )
    
    # Get available voices for dropdown choices
    available_voices = get_voice_profiles(voice_library_path)
    if not available_voices:
        empty_dropdown = gr.Dropdown(choices=[("No voices available", None)], visible=False, interactive=False)
        return (
            "<div class='voice-status'>❌ No voices available in library. Create voices first!</div>",
            voice_counts,
            [],
            empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown, empty_dropdown,
            gr.Button("🔍 Validate Voice Assignments", interactive=False),
            "❌ No voices in library"
        )
    
    # Create voice choices for dropdowns
    voice_choices = [("Select a voice...", None)]
    for voice in available_voices:
        display_text = f"🎭 {voice['display_name']} ({voice['name']})"
        voice_choices.append((display_text, voice['name']))
    
    # Get character names (excluding "No Voice Tag")
    character_names = [name for name in voice_counts.keys() if name != "No Voice Tag"]
    
    # Create dropdown components for up to 6 characters
    dropdown_components = []
    for i in range(6):
        if i < len(character_names):
            character_name = character_names[i]
            word_count = voice_counts[character_name]
            dropdown = gr.Dropdown(
                choices=voice_choices,
                label=f"Voice for [{character_name}] ({word_count} words)",
                visible=True,
                interactive=True,
                info=f"Select which voice to use for character '{character_name}'"
            )
        else:
            dropdown = gr.Dropdown(
                choices=[("No character found", None)],
                label=f"Character {i+1}",
                visible=False,
                interactive=False
            )
        dropdown_components.append(dropdown)
    
    # Create summary message
    total_words = sum(voice_counts.values())
    summary_msg = f"✅ Found {len(character_names)} characters with {total_words:,} total words\n" + breakdown_text
    
    return (
        summary_msg,
        voice_counts,
        character_names,
        dropdown_components[0], dropdown_components[1], dropdown_components[2],
        dropdown_components[3], dropdown_components[4], dropdown_components[5],
        gr.Button("🔍 Validate Voice Assignments", interactive=True),
        "✅ Analysis complete - assign voices above"
    )

def validate_dropdown_voice_assignments(text_content, voice_library_path, project_name, voice_counts, character_names, 
                                       char1_voice, char2_voice, char3_voice, char4_voice, char5_voice, char6_voice):
    """
    Validate voice assignments from character dropdowns
    """
    if not voice_counts or "No Voice Tag" in voice_counts:
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            "❌ Invalid text or voice tags",
            {},
            gr.Audio(visible=False)
        )
    
    if not project_name or not project_name.strip():
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            "❌ Project name is required",
            {},
            gr.Audio(visible=False)
        )
    
    if not character_names:
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            "❌ No characters found in text",
            {},
            gr.Audio(visible=False)
        )
    
    # Collect dropdown values
    dropdown_values = [char1_voice, char2_voice, char3_voice, char4_voice, char5_voice, char6_voice]
    
    # Create voice assignments mapping
    voice_assignments = {}
    missing_assignments = []
    
    for i, character_name in enumerate(character_names):
        if i < len(dropdown_values):
            assigned_voice = dropdown_values[i]
            if not assigned_voice:
                missing_assignments.append(character_name)
            else:
                voice_assignments[character_name] = assigned_voice
        else:
            missing_assignments.append(character_name)
    
    if missing_assignments:
        return (
            gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=False),
            f"❌ Please assign voices for: {', '.join(missing_assignments)}",
            voice_assignments,
            gr.Audio(visible=False)
        )
    
    # All assignments valid
    total_words = sum(voice_counts.values())
    assignment_summary = "\n".join([f"🎭 [{char}] → {voice_assignments[char]}" for char in character_names])
    
    return (
        gr.Button("🎵 Create Multi-Voice Audiobook", variant="primary", size="lg", interactive=True),
        f"✅ All characters assigned!\n📊 {total_words:,} words total\n📁 Project: {project_name.strip()}\n\nAssignments:\n{assignment_summary}",
        voice_assignments,
        gr.Audio(visible=True)
    )

# Custom CSS for better styling - Fixed to preserve existing UI while targeting white backgrounds
css = """
.voice-card {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
    background: #f9f9f9;
}

.tab-nav {
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 10px;
    border-radius: 8px 8px 0 0;
}

.voice-library-header {
    background: linear-gradient(90deg, #f093fb 0%, #f5576c 100%);
    color: white;
    padding: 15px;
    border-radius: 8px;
    margin-bottom: 15px;
    text-align: center;
}

.voice-status {
    background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
    color: white;
    border-radius: 6px;
    padding: 12px;
    margin: 5px 0;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    font-weight: 500;
}

.config-status {
    background: linear-gradient(135deg, #059669 0%, #047857 100%);
    color: white;
    border-radius: 6px;
    padding: 10px;
    margin: 5px 0;
    font-size: 0.9em;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    font-weight: 500;
}

.audiobook-header {
    background: linear-gradient(90deg, #8b5cf6 0%, #06b6d4 100%);
    color: white;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 15px;
    text-align: center;
}

.file-status {
    background: linear-gradient(135deg, #b45309 0%, #92400e 100%);
    color: white;
    border-radius: 6px;
    padding: 12px;
    margin: 5px 0;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    font-weight: 500;
}

.audiobook-status {
    background: linear-gradient(135deg, #6d28d9 0%, #5b21b6 100%);
    color: white;
    border-radius: 6px;
    padding: 15px;
    margin: 10px 0;
    text-align: center;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    font-weight: 500;
}

/* Target specific instruction boxes that had white backgrounds */
.instruction-box {
    background: linear-gradient(135deg, #374151 0%, #1f2937 100%) !important;
    color: white !important;
    border-left: 4px solid #3b82f6 !important;
    padding: 15px;
    border-radius: 8px;
    margin-top: 20px;
}
"""

# Load the saved voice library path
SAVED_VOICE_LIBRARY_PATH = load_config()

# Project metadata and regeneration functionality
def save_project_metadata(project_dir: str, project_name: str, text_content: str, 
                         voice_info: dict, chunks: list, project_type: str = "single_voice") -> None:
    """Save project metadata for regeneration purposes"""
    metadata = {
        "project_name": project_name,
        "project_type": project_type,  # "single_voice" or "multi_voice"
        "creation_date": str(time.time()),
        "text_content": text_content,
        "chunks": chunks,
        "voice_info": voice_info,
        "sample_rate": 24000,  # Default sample rate for ChatterboxTTS
        "version": "1.0"
    }
    
    metadata_file = os.path.join(project_dir, "project_metadata.json")
    try:
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Warning: Could not save project metadata: {str(e)}")

def load_project_metadata(project_dir: str) -> dict:
    """Load project metadata from directory"""
    metadata_file = os.path.join(project_dir, "project_metadata.json")
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Warning: Could not load project metadata: {str(e)}")
    return None

def get_existing_projects(output_dir: str = "audiobook_projects") -> list:
    """Get list of existing projects with their metadata"""
    projects = []
    
    if not os.path.exists(output_dir):
        return projects
    
    for project_name in os.listdir(output_dir):
        project_path = os.path.join(output_dir, project_name)
        if os.path.isdir(project_path):
            # Get only the actual chunk files (not complete, backup, or temp files)
            all_audio_files = [f for f in os.listdir(project_path) if f.endswith('.wav')]
            
            # Filter to only count actual chunk files
            chunk_files = []
            for wav_file in all_audio_files:
                # Skip complete files, backup files, and temp files
                if (wav_file.endswith('_complete.wav') or 
                    '_backup_' in wav_file or 
                    'temp_regenerated_' in wav_file):
                    continue
                
                # Check if it matches the chunk pattern: projectname_XXX.wav or projectname_XXX_character.wav
                import re
                # Pattern for single voice: projectname_001.wav
                pattern1 = rf'^{re.escape(project_name)}_(\d{{3}})\.wav$'
                # Pattern for multi-voice: projectname_001_character.wav  
                pattern2 = rf'^{re.escape(project_name)}_(\d{{3}})_.+\.wav$'
                
                if re.match(pattern1, wav_file) or re.match(pattern2, wav_file):
                    chunk_files.append(wav_file)
            
            # Try to load metadata
            metadata = load_project_metadata(project_path)
            
            project_info = {
                "name": project_name,
                "path": project_path,
                "audio_files": chunk_files,  # Only actual chunk files
                "audio_count": len(chunk_files),
                "has_metadata": metadata is not None,
                "metadata": metadata
            }
            
            # If no metadata, try to infer some info
            if not metadata and chunk_files:
                project_info["creation_date"] = os.path.getctime(project_path)
                project_info["estimated_type"] = "unknown"
            
            projects.append(project_info)
    
    # Sort by creation date (newest first) - handle mixed types safely
    def get_sort_key(project):
        if project.get("metadata"):
            creation_date = project["metadata"].get("creation_date", 0)
            # Convert string timestamps to float for sorting
            if isinstance(creation_date, str):
                try:
                    return float(creation_date)
                except (ValueError, TypeError):
                    return 0.0
            return float(creation_date) if creation_date else 0.0
        else:
            return float(project.get("creation_date", 0))
    
    projects.sort(key=get_sort_key, reverse=True)
    
    return projects

def force_refresh_all_project_dropdowns():
    """Force refresh all project dropdowns to ensure new projects appear"""
    try:
        # Clear any potential caches and get fresh project list
        projects = get_existing_projects()
        choices = get_project_choices()
        # Return the same choices for all three dropdowns that might need updating
        return (
            gr.Dropdown(choices=choices, value=None),
            gr.Dropdown(choices=choices, value=None), 
            gr.Dropdown(choices=choices, value=None)
        )
    except Exception as e:
        print(f"Error refreshing project dropdowns: {str(e)}")
        error_choices = [("Error loading projects", None)]
        return (
            gr.Dropdown(choices=error_choices, value=None),
            gr.Dropdown(choices=error_choices, value=None),
            gr.Dropdown(choices=error_choices, value=None)
        )

def force_refresh_single_project_dropdown():
    """Force refresh a single project dropdown"""
    try:
        choices = get_project_choices()
        # Return a new dropdown with updated choices and no selected value
        return gr.Dropdown(choices=choices, value=None)
    except Exception as e:
        print(f"Error refreshing project dropdown: {str(e)}")
        error_choices = [("Error loading projects", None)]
        return gr.Dropdown(choices=error_choices, value=None)

def get_project_choices() -> list:
    """Get project choices for dropdown - always fresh data"""
    try:
        projects = get_existing_projects()  # This should always get fresh data
        if not projects:
            return [("No projects found", None)]
        
        choices = []
        for project in projects:
            metadata = project.get("metadata")
            if metadata:
                project_type = metadata.get('project_type', 'unknown')
                display_name = f"📁 {project['name']} ({project_type}) - {project['audio_count']} files"
            else:
                display_name = f"📁 {project['name']} (no metadata) - {project['audio_count']} files"
            choices.append((display_name, project['name']))
        
        return choices
        
    except Exception as e:
        print(f"Error getting project choices: {str(e)}")
        return [("Error loading projects", None)]

def load_project_for_regeneration(project_name: str) -> tuple:
    """Load a project for regeneration"""
    if not project_name:
        return "", "", "", None, "No project selected"
    
    projects = get_existing_projects()
    project = next((p for p in projects if p['name'] == project_name), None)
    
    if not project:
        return "", "", "", None, f"❌ Project '{project_name}' not found"
    
    metadata = project.get('metadata')
    if not metadata:
        # Legacy project without metadata
        audio_files = project['audio_files']
        if audio_files:
            # Load first audio file for waveform
            first_audio = os.path.join(project['path'], audio_files[0])
            return ("", 
                    "⚠️ Legacy project - no original text available", 
                    "⚠️ Voice information not available",
                    first_audio,
                    f"⚠️ Legacy project loaded. Found {len(audio_files)} audio files but no metadata.")
        else:
            return "", "", "", None, f"❌ No audio files found in project '{project_name}'"
    
    # Project with metadata
    text_content = metadata.get('text_content', '')
    voice_info = metadata.get('voice_info', {})
    
    # Format voice info display
    if metadata.get('project_type') == 'multi_voice':
        voice_display = "🎭 Multi-voice project:\n"
        for voice_name, info in voice_info.items():
            voice_display += f"  • {voice_name}: {info.get('display_name', voice_name)}\n"
    else:
        voice_display = f"🎤 Single voice: {voice_info.get('display_name', 'Unknown')}"
    
    # Load first audio file for waveform
    audio_files = project['audio_files']
    first_audio = os.path.join(project['path'], audio_files[0]) if audio_files else None
    
    creation_date = metadata.get('creation_date', '')
    if creation_date:
        try:
            import datetime
            date_obj = datetime.datetime.fromtimestamp(float(creation_date))
            date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        except:
            date_str = creation_date
    else:
        date_str = "Unknown"
    
    status_msg = f"✅ Project loaded successfully!\n📅 Created: {date_str}\n🎵 Audio files: {len(audio_files)}\n📝 Text length: {len(text_content)} characters"
    
    return text_content, voice_display, project_name, first_audio, status_msg

def create_continuous_playback_audio(project_name: str) -> tuple:
    """Create a single continuous audio file from all project chunks for Listen & Edit mode"""
    if not project_name:
        return None, "❌ No project selected"
    
    chunks = get_project_chunks(project_name)
    if not chunks:
        return None, f"❌ No audio chunks found in project '{project_name}'"
    
    try:
        combined_audio = []
        sample_rate = 24000  # Default sample rate
        chunk_timings = []  # Store start/end times for each chunk
        current_time = 0.0
        
        # Sort chunks by chunk number to ensure correct order
        def extract_chunk_number(chunk_info):
            return chunk_info.get('chunk_num', 0)
        
        chunks_sorted = sorted(chunks, key=extract_chunk_number)
        
        # Load and combine all audio files in order
        for chunk in chunks_sorted:
            audio_file = chunk['audio_file']
            
            if os.path.exists(audio_file):
                try:
                    with wave.open(audio_file, 'rb') as wav_file:
                        sample_rate = wav_file.getframerate()
                        frames = wav_file.readframes(wav_file.getnframes())
                        audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
                        
                        # Record timing info for this chunk
                        chunk_duration = len(audio_data) / sample_rate
                        chunk_timings.append({
                            'chunk_num': chunk['chunk_num'],
                            'start_time': current_time,
                            'end_time': current_time + chunk_duration,
                            'text': chunk.get('text', ''),
                            'audio_file': audio_file
                        })
                        
                        combined_audio.append(audio_data)
                        current_time += chunk_duration
                        
                except Exception as e:
                    print(f"⚠️ Error reading chunk {chunk['chunk_num']}: {str(e)}")
            else:
                print(f"⚠️ Warning: Audio file not found: {audio_file}")
        
        if not combined_audio:
            return None, f"❌ No valid audio files found in project '{project_name}'"
        
        # Concatenate all audio
        full_audio = np.concatenate(combined_audio)
        
        # Create temporary combined file
        temp_filename = f"temp_continuous_{project_name}_{int(time.time())}.wav"
        temp_file_path = os.path.join("audiobook_projects", project_name, temp_filename)
        
        # Save as WAV file
        with wave.open(temp_file_path, 'wb') as output_wav:
            output_wav.setnchannels(1)  # Mono
            output_wav.setsampwidth(2)  # 16-bit
            output_wav.setframerate(sample_rate)
            audio_int16 = (full_audio * 32767).astype(np.int16)
            output_wav.writeframes(audio_int16.tobytes())
        
        # Calculate total duration
        total_duration = len(full_audio) / sample_rate
        duration_minutes = int(total_duration // 60)
        duration_seconds = int(total_duration % 60)
        
        success_msg = f"✅ Continuous audio created: {duration_minutes}:{duration_seconds:02d} ({len(chunks_sorted)} chunks)"
        
        # Return audio file path and timing data
        return (temp_file_path, chunk_timings), success_msg
        
    except Exception as e:
        return None, f"❌ Error creating continuous audio: {str(e)}"

def get_current_chunk_from_time(chunk_timings: list, current_time: float) -> dict:
    """Get the current chunk information based on playback time"""
    if not chunk_timings or current_time is None:
        return {}
    
    for chunk_timing in chunk_timings:
        if chunk_timing['start_time'] <= current_time < chunk_timing['end_time']:
            return chunk_timing
    
    # If we're past the end, return the last chunk
    if chunk_timings and current_time >= chunk_timings[-1]['end_time']:
        return chunk_timings[-1]
    
    # If we're before the start, return the first chunk
    if chunk_timings and current_time < chunk_timings[0]['start_time']:
        return chunk_timings[0]
    
    return {}

def regenerate_chunk_and_update_continuous(model, project_name: str, chunk_num: int, voice_library_path: str, 
                                         custom_text: str = None) -> tuple:
    """Regenerate a chunk and update the continuous audio file"""
    # First regenerate the chunk
    result = regenerate_single_chunk(model, project_name, chunk_num, voice_library_path, custom_text)
    
    if result[0] is None:  # Error occurred
        return None, result[1], None
    
    temp_file_path, status_msg = result
    
    # Accept the regenerated chunk immediately (auto-accept for continuous mode)
    chunks = get_project_chunks(project_name)
    accept_result = accept_regenerated_chunk(project_name, chunk_num, temp_file_path, chunks)
    
    if "✅" not in accept_result[0]:  # Error in acceptance
        return None, f"❌ Regeneration succeeded but failed to update: {accept_result[0]}", None
    
    # Recreate the continuous audio with the updated chunk
    continuous_result = create_continuous_playback_audio(project_name)
    
    if continuous_result[0] is None:  # Error creating continuous audio
        return None, f"✅ Chunk regenerated but failed to update continuous audio: {continuous_result[1]}", None
    
    continuous_data, continuous_msg = continuous_result
    
    return continuous_data, f"✅ Chunk {chunk_num} regenerated and continuous audio updated!", status_msg

def cleanup_temp_continuous_files(project_name: str) -> None:
    """Clean up temporary continuous audio files"""
    if not project_name:
        return
    
    project_path = os.path.join("audiobook_projects", project_name)
    if not os.path.exists(project_path):
        return
    
    try:
        for file in os.listdir(project_path):
            if file.startswith("temp_continuous_") and file.endswith('.wav'):
                file_path = os.path.join(project_path, file)
                try:
                    os.remove(file_path)
                    print(f"🗑️ Cleaned up: {file}")
                except Exception as e:
                    print(f"⚠️ Could not remove {file}: {str(e)}")
    except Exception as e:
        print(f"⚠️ Error cleaning temp files: {str(e)}")

def regenerate_project_sample(model, project_name: str, voice_library_path: str, sample_text: str = None) -> tuple:
    """Regenerate a sample from an existing project"""
    if not project_name:
        return None, "❌ No project selected"
    
    projects = get_existing_projects()
    project = next((p for p in projects if p['name'] == project_name), None)
    
    if not project:
        return None, f"❌ Project '{project_name}' not found"
    
    metadata = project.get('metadata')
    if not metadata:
        return None, "❌ Cannot regenerate - project has no metadata (legacy project)"
    
    # Use provided sample text or take first chunk from original
    if sample_text and sample_text.strip():
        text_to_regenerate = sample_text.strip()
    else:
        chunks = metadata.get('chunks', [])
        if not chunks:
            original_text = metadata.get('text_content', '')
            if original_text:
                chunks = chunk_text_by_sentences(original_text, max_words=50)
                text_to_regenerate = chunks[0] if chunks else original_text[:200]
            else:
                return None, "❌ No text content available for regeneration"
        else:
            text_to_regenerate = chunks[0]
    
    # Get voice information
    voice_info = metadata.get('voice_info', {})
    project_type = metadata.get('project_type', 'single_voice')
    
    try:
        if project_type == 'single_voice':
            # Single voice regeneration
            voice_config = voice_info
            if not voice_config or not voice_config.get('audio_file'):
                return None, "❌ Voice configuration not available"
            
            # Generate audio
            wav = generate_with_retry(
                model,
                text_to_regenerate,
                voice_config['audio_file'],
                voice_config.get('exaggeration', 0.5),
                voice_config.get('temperature', 0.8),
                voice_config.get('cfg_weight', 0.5)
            )
            
            audio_output = wav.squeeze(0).cpu().numpy()
            status_msg = f"✅ Sample regenerated successfully!\n🎭 Voice: {voice_config.get('display_name', 'Unknown')}\n📝 Text: {text_to_regenerate[:100]}..."
            
            return (model.sr, audio_output), status_msg
            
        else:
            # Multi-voice regeneration - use first voice
            first_voice = list(voice_info.keys())[0] if voice_info else None
            if not first_voice:
                return None, "❌ No voice information available for multi-voice project"
            
            voice_config = voice_info[first_voice]
            if not voice_config or not voice_config.get('audio_file'):
                return None, f"❌ Voice configuration not available for '{first_voice}'"
            
            wav = generate_with_retry(
                model,
                text_to_regenerate,
                voice_config['audio_file'],
                voice_config.get('exaggeration', 0.5),
                voice_config.get('temperature', 0.8),
                voice_config.get('cfg_weight', 0.5)
            )
            
            audio_output = wav.squeeze(0).cpu().numpy()
            status_msg = f"✅ Sample regenerated successfully!\n🎭 Voice: {voice_config.get('display_name', first_voice)}\n📝 Text: {text_to_regenerate[:100]}..."
            
            return (model.sr, audio_output), status_msg
            
    except Exception as e:
        clear_gpu_memory()
        return None, f"❌ Error regenerating sample: {str(e)}"

def get_project_chunks(project_name: str) -> list:
    """Get all chunks from a project with audio files and text"""
    if not project_name:
        return []
    
    projects = get_existing_projects()
    project = next((p for p in projects if p['name'] == project_name), None)
    
    if not project:
        return []
    
    project_path = project['path']
    
    # Get only the actual chunk files (not complete, backup, or temp files)
    all_wav_files = [f for f in os.listdir(project_path) if f.endswith('.wav')]
    
    # Filter to only get numbered chunk files in format: projectname_001.wav, projectname_002.wav etc.
    chunk_files = []
    for wav_file in all_wav_files:
        # Skip complete files, backup files, and temp files
        if (wav_file.endswith('_complete.wav') or 
            '_backup_' in wav_file or 
            'temp_regenerated_' in wav_file):
            continue
        
        # Check if it matches the pattern: projectname_XXX.wav
        import re
        pattern = rf'^{re.escape(project_name)}_(\d{{3}})\.wav$'
        if re.match(pattern, wav_file):
            chunk_files.append(wav_file)
    
    # Sort by chunk number (numerically, not lexicographically)
    def extract_chunk_num_from_filename(filename: str) -> int:
        import re
        match = re.search(r'_(\d{3})\.wav$', filename)
        if not match:
            match = re.search(r'_(\d+)\.wav$', filename)
        if match:
            return int(match.group(1))
        return 0
    chunk_files = sorted(chunk_files, key=extract_chunk_num_from_filename)
    
    chunks = []
    metadata = project.get('metadata')
    
    if metadata and metadata.get('chunks'):
        # Project with metadata - get original text chunks
        original_chunks = metadata.get('chunks', [])
        project_type = metadata.get('project_type', 'single_voice')
        voice_info = metadata.get('voice_info', {})
        
        # For multi-voice, also load the project_info.json to get voice assignments
        voice_assignments = {}
        if project_type == 'multi_voice':
            project_info_file = os.path.join(project_path, "project_info.json")
            if os.path.exists(project_info_file):
                try:
                    with open(project_info_file, 'r') as f:
                        project_info = json.load(f)
                        voice_assignments = project_info.get('voice_assignments', {})
                except Exception as e:
                    print(f"⚠️ Warning: Could not load voice assignments: {str(e)}")
        
        for i, audio_file in enumerate(chunk_files):
            # Extract the actual chunk number from the filename instead of using the enumerate index
            actual_chunk_num = extract_chunk_num_from_filename(audio_file)
            
            chunk_info = {
                'chunk_num': actual_chunk_num,  # Use actual chunk number from filename
                'audio_file': os.path.join(project_path, audio_file),
                'audio_filename': audio_file,
                'text': original_chunks[i] if i < len(original_chunks) else "Text not available",
                'has_metadata': True,
                'project_type': project_type,
                'voice_info': voice_info
            }
            
            # For multi-voice, try to extract character and find assigned voice
            if project_type == 'multi_voice':
                # Filename format: project_001_character.wav
                parts = audio_file.replace('.wav', '').split('_')
                if len(parts) >= 3:
                    character_name = '_'.join(parts[2:])  # Everything after project_XXX_
                    chunk_info['character'] = character_name
                    
                    # Look up the actual voice assigned to this character
                    assigned_voice = voice_assignments.get(character_name, character_name)
                    chunk_info['assigned_voice'] = assigned_voice
                    
                    # Get the voice config for the assigned voice
                    chunk_info['voice_config'] = voice_info.get(assigned_voice, {})
                    
                else:
                    chunk_info['character'] = 'unknown'
                    chunk_info['assigned_voice'] = 'unknown'
                    chunk_info['voice_config'] = {}
            
            chunks.append(chunk_info)
    
    else:
        # Legacy project without metadata
        for i, audio_file in enumerate(chunk_files):
            # Extract the actual chunk number from the filename instead of using the enumerate index
            actual_chunk_num = extract_chunk_num_from_filename(audio_file)
            
            chunk_info = {
                'chunk_num': actual_chunk_num,  # Use actual chunk number from filename
                'audio_file': os.path.join(project_path, audio_file),
                'audio_filename': audio_file,
                'text': "Legacy project - original text not available",
                'has_metadata': False,
                'project_type': 'unknown',
                'voice_info': {}
            }
            chunks.append(chunk_info)
    
    return chunks

def regenerate_single_chunk(model, project_name: str, chunk_num: int, voice_library_path: str, custom_text: str = None) -> tuple:
    """Regenerate a single chunk from a project"""
    chunks = get_project_chunks(project_name)
    
    if not chunks or chunk_num < 1 or chunk_num > len(chunks):
        return None, f"❌ Invalid chunk number {chunk_num}"
    
    chunk = chunks[chunk_num - 1]  # Convert to 0-based index
    
    if not chunk['has_metadata']:
        return None, "❌ Cannot regenerate - legacy project has no voice metadata"
    
    # Use custom text or original text
    text_to_regenerate = custom_text.strip() if custom_text and custom_text.strip() else chunk['text']
    
    if not text_to_regenerate:
        return None, "❌ No text available for regeneration"
    
    try:
        project_type = chunk['project_type']
        
        if project_type == 'single_voice':
            # Single voice project
            voice_config = chunk['voice_info']
            if not voice_config or not voice_config.get('audio_file'):
                return None, "❌ Voice configuration not available"
            
            wav = generate_with_retry(
                model,
                text_to_regenerate,
                voice_config['audio_file'],
                voice_config.get('exaggeration', 0.5),
                voice_config.get('temperature', 0.8),
                voice_config.get('cfg_weight', 0.5)
            )
            
            voice_display = voice_config.get('display_name', 'Unknown')
            
        elif project_type == 'multi_voice':
            # Multi-voice project - use the voice config from the chunk
            voice_config = chunk.get('voice_config', {})
            character_name = chunk.get('character', 'unknown')
            assigned_voice = chunk.get('assigned_voice', 'unknown')
            
            if not voice_config:
                return None, f"❌ Voice configuration not found for character '{character_name}' (assigned voice: '{assigned_voice}')"
            
            if not voice_config.get('audio_file'):
                return None, f"❌ Audio file not found for character '{character_name}' (assigned voice: '{assigned_voice}')"
            
            # Check if audio file actually exists
            audio_file_path = voice_config.get('audio_file')
            if not os.path.exists(audio_file_path):
                return None, f"❌ Audio file does not exist: {audio_file_path}"
            
            wav = generate_with_retry(
                model,
                text_to_regenerate,
                voice_config['audio_file'],
                voice_config.get('exaggeration', 0.5),
                voice_config.get('temperature', 0.8),
                voice_config.get('cfg_weight', 0.5)
            )
            
            voice_display = f"{voice_config.get('display_name', assigned_voice)} (Character: {character_name})"
            
        else:
            return None, f"❌ Unknown project type: {project_type}"
        
        # Save regenerated audio to a temporary file
        audio_output = wav.squeeze(0).cpu().numpy()
        
        # Apply volume normalization if enabled in voice profile
        if voice_config.get('normalization_enabled', False):
            target_level = voice_config.get('target_level_db', -18.0)
            try:
                # Analyze current audio level
                level_info = analyze_audio_level(audio_output, model.sr)
                current_level = level_info['rms_db']
                
                # Normalize audio
                audio_output = normalize_audio_to_target(audio_output, current_level, target_level)
                print(f"🎚️ Regenerated chunk {chunk_num}: Volume normalized from {current_level:.1f}dB to {target_level:.1f}dB")
            except Exception as e:
                print(f"⚠️ Volume normalization failed for regenerated chunk {chunk_num}: {str(e)}")
        
        # Create temporary file path
        project_dir = os.path.dirname(chunk['audio_file'])
        temp_filename = f"temp_regenerated_chunk_{chunk_num}_{int(time.time())}.wav"
        temp_file_path = os.path.join(project_dir, temp_filename)
        
        # Save as WAV file
        with wave.open(temp_file_path, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(model.sr)
            # Convert float32 to int16
            audio_int16 = (audio_output * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        
        status_msg = f"✅ Chunk {chunk_num} regenerated successfully!\n🎭 Voice: {voice_display}\n📝 Text: {text_to_regenerate[:100]}{'...' if len(text_to_regenerate) > 100 else ''}\n💾 Temp file: {temp_filename}"
        
        # Return the temp file path instead of the audio tuple
        return temp_file_path, status_msg
        
    except Exception as e:
        clear_gpu_memory()
        return None, f"❌ Error regenerating chunk {chunk_num}: {str(e)}"

def load_project_chunks_for_interface(project_name: str, page_num: int = 1, chunks_per_page: int = 50) -> tuple:
    """Load project chunks and return data for interface components with pagination support"""
    if not project_name:
        # Hide all chunk interfaces
        empty_returns = []
        for i in range(MAX_CHUNKS_FOR_INTERFACE):
            empty_returns.extend([
                gr.Group(visible=False),  # group
                None,  # audio
                "",  # text
                "<div class='voice-status'>No chunk loaded</div>",  # voice_info
                gr.Button(f"🎵 Regenerate Chunk {i+1}", interactive=False),  # button
                gr.Audio(visible=False),  # regenerated_audio
                "<div class='voice-status'>No chunk</div>"  # status
            ])
        
        return (
            "<div class='voice-status'>📝 Select a project first</div>",  # project_info_summary
            [],  # current_project_chunks (all chunks, not just displayed)
            project_name,  # current_project_name
            "<div class='audiobook-status'>📁 No project loaded</div>",  # project_status
            gr.Button("📥 Download Full Project Audio", variant="primary", size="lg", interactive=False),  # download_project_btn
            "<div class='voice-status'>📁 Load a project first to enable download</div>",  # download_status
            1,  # current_page_state
            1,  # total_pages_state
            gr.Button("⬅️ Previous Page", size="sm", interactive=False),  # prev_page_btn
            gr.Button("➡️ Next Page", size="sm", interactive=False),  # next_page_btn
            "<div class='voice-status'>📄 No project loaded</div>",  # page_info
            *empty_returns
        )
    
    all_chunks = get_project_chunks(project_name)
    
    if not all_chunks:
        # Hide all chunk interfaces
        empty_returns = []
        for i in range(MAX_CHUNKS_FOR_INTERFACE):
            empty_returns.extend([
                gr.Group(visible=False),
                None,
                "",
                "<div class='voice-status'>No chunk found</div>",
                gr.Button(f"🎵 Regenerate Chunk {i+1}", interactive=False),
                gr.Audio(visible=False),
                "<div class='voice-status'>No chunk</div>"
            ])
        
        return (
            f"<div class='voice-status'>❌ No chunks found in project '{project_name}'</div>",
            [],
            project_name,
            f"❌ No audio files found in project '{project_name}'",
            gr.Button("📥 Download Full Project Audio", variant="primary", size="lg", interactive=False),
            f"❌ No audio files found in project '{project_name}'",
            1,  # current_page_state
            1,  # total_pages_state
            gr.Button("⬅️ Previous Page", size="sm", interactive=False),  # prev_page_btn
            gr.Button("➡️ Next Page", size="sm", interactive=False),  # next_page_btn
            f"❌ No chunks found in project '{project_name}'",  # page_info
            *empty_returns
        )
    
    # Calculate pagination
    total_chunks = len(all_chunks)
    total_pages = max(1, (total_chunks + chunks_per_page - 1) // chunks_per_page)  # Ceiling division
    page_num = max(1, min(page_num, total_pages))  # Clamp page number
    
    start_idx = (page_num - 1) * chunks_per_page
    end_idx = min(start_idx + chunks_per_page, total_chunks)
    chunks_for_current_page = all_chunks[start_idx:end_idx]
    
    # Create project summary
    project_info = f"""
    <div class='audiobook-status'>
        📁 <strong>Project:</strong> {project_name}<br/>
        🎵 <strong>Total Chunks:</strong> {total_chunks}<br/>
        📄 <strong>Showing:</strong> {len(chunks_for_current_page)} chunks (Page {page_num} of {total_pages})<br/>
        📝 <strong>Type:</strong> {all_chunks[0]['project_type'].replace('_', ' ').title()}<br/>
        ✅ <strong>Metadata:</strong> {'Available' if all_chunks[0]['has_metadata'] else 'Legacy Project'}
    </div>
    """
    
    status_msg = f"✅ Loaded page {page_num} of {total_pages} ({len(chunks_for_current_page)} chunks shown, {total_chunks} total) from project '{project_name}'"
    
    # Page info
    page_info_html = f"<div class='voice-status'>📄 Page {page_num} of {total_pages} | Chunks {start_idx + 1}-{end_idx} of {total_chunks}</div>"
    
    # Navigation buttons
    prev_btn = gr.Button("⬅️ Previous Page", size="sm", interactive=(page_num > 1))
    next_btn = gr.Button("➡️ Next Page", size="sm", interactive=(page_num < total_pages))
    
    # Prepare interface updates
    interface_updates = []
    
    for i in range(MAX_CHUNKS_FOR_INTERFACE):
        if i < len(chunks_for_current_page):
            chunk = chunks_for_current_page[i]
            
            # Voice info display
            if chunk['project_type'] == 'multi_voice':
                character_name = chunk.get('character', 'unknown')
                assigned_voice = chunk.get('assigned_voice', 'unknown')
                voice_config = chunk.get('voice_config', {})
                voice_display_name = voice_config.get('display_name', assigned_voice)
                
                voice_info_html = f"<div class='voice-status'>🎭 Character: {character_name}<br/>🎤 Voice: {voice_display_name}</div>"
            elif chunk['project_type'] == 'single_voice':
                voice_name = chunk['voice_info'].get('display_name', 'Unknown') if chunk.get('voice_info') else 'Unknown'
                voice_info_html = f"<div class='voice-status'>🎤 Voice: {voice_name}</div>"
            else:
                voice_info_html = "<div class='voice-status'>⚠️ Legacy project - limited info</div>"
            
            # Status message
            chunk_status = f"<div class='voice-status'>📄 Chunk {chunk['chunk_num']} ready to regenerate</div>"
            
            interface_updates.extend([
                gr.Group(visible=True),  # group
                chunk['audio_file'],  # audio
                chunk['text'],  # text
                voice_info_html,  # voice_info
                gr.Button(f"🎵 Regenerate Chunk {chunk['chunk_num']}", interactive=chunk['has_metadata']),  # button
                gr.Audio(visible=False),  # regenerated_audio
                chunk_status  # status
            ])
        else:
            # Hide unused interfaces
            interface_updates.extend([
                gr.Group(visible=False),
                None,
                "",
                "<div class='voice-status'>No chunk</div>",
                gr.Button(f"🎵 Regenerate Chunk {i+1}", interactive=False),
                gr.Audio(visible=False),
                "<div class='voice-status'>No chunk</div>"
            ])
    
    return (
        project_info,  # project_info_summary
        all_chunks,  # current_project_chunks (ALL chunks, not just displayed)
        project_name,  # current_project_name
        status_msg,  # project_status
        gr.Button("📥 Download Full Project Audio", variant="primary", size="lg", interactive=bool(all_chunks)),  # download_project_btn
        f"<div class='voice-status'>✅ Ready to download complete project audio ({total_chunks} chunks)</div>" if all_chunks else "<div class='voice-status'>📁 Load a project first to enable download</div>",  # download_status
        page_num,  # current_page_state
        total_pages,  # total_pages_state
        prev_btn,  # prev_page_btn
        next_btn,  # next_page_btn
        page_info_html,  # page_info
        *interface_updates
    )

def combine_project_audio_chunks(project_name: str, output_format: str = "wav") -> tuple:
    """Combine all audio chunks from a project into a single downloadable file"""
    if not project_name:
        return None, "❌ No project selected"
    
    chunks = get_project_chunks(project_name)
    
    if not chunks:
        return None, f"❌ No audio chunks found in project '{project_name}'"
    
    try:
        combined_audio = []
        sample_rate = 24000  # Default sample rate
        total_samples_processed = 0
        
        # Sort chunks by chunk number to ensure correct order (not alphabetical)
        def extract_chunk_number(chunk_info):
            """Extract chunk number from chunk info for proper numerical sorting"""
            try:
                # First try to get chunk_num directly from the chunk info
                chunk_num = chunk_info.get('chunk_num')
                if chunk_num is not None:
                    return int(chunk_num)  # Ensure it's an integer
            except (ValueError, TypeError):
                pass
            
            # Fallback: try to extract from filename
            try:
                filename = chunk_info.get('audio_filename', '') or chunk_info.get('audio_file', '')
                if filename:
                    import re
                    # Look for patterns like "_123.wav" or "_chunk_123.wav"
                    match = re.search(r'_(\d+)\.wav$', filename)
                    if match:
                        return int(match.group(1))
                    
                    # Try other patterns like "projectname_123.wav"
                    match = re.search(r'(\d+)\.wav$', filename)
                    if match:
                        return int(match.group(1))
            except (ValueError, TypeError, AttributeError):
                pass
            
            # Last resort: return 0 (should sort first)
            print(f"[WARNING] Could not extract chunk number from: {chunk_info}")
            return 0
        
        chunks_sorted = sorted(chunks, key=extract_chunk_number)
        
        print(f"[INFO] Combining {len(chunks_sorted)} chunks for project '{project_name}'")
        chunk_numbers = [extract_chunk_number(c) for c in chunks_sorted[:5]]
        print(f"[DEBUG] First few chunks: {chunk_numbers}")
        chunk_numbers = [extract_chunk_number(c) for c in chunks_sorted[-5:]]
        print(f"[DEBUG] Last few chunks: {chunk_numbers}")
        
        # Process chunks in batches to manage memory better
        batch_size = 50
        for batch_start in range(0, len(chunks_sorted), batch_size):
            batch_end = min(batch_start + batch_size, len(chunks_sorted))
            batch_chunks = chunks_sorted[batch_start:batch_end]
            
            print(f"[INFO] Processing batch {batch_start//batch_size + 1}/{(len(chunks_sorted) + batch_size - 1)//batch_size} (chunks {batch_start+1}-{batch_end})")
            
            for chunk_info in batch_chunks:
                chunk_path = chunk_info.get('audio_file')  # Use 'audio_file' instead of 'audio_path'
                chunk_num = extract_chunk_number(chunk_info)
                
                if not chunk_path or not os.path.exists(chunk_path):
                    print(f"⚠️ Warning: Chunk {chunk_num} file not found: {chunk_path}")
                    continue
                
                try:
                    with wave.open(chunk_path, 'rb') as wav_file:
                        chunk_sample_rate = wav_file.getframerate()
                        chunk_frames = wav_file.getnframes()
                        chunk_audio_data = wav_file.readframes(chunk_frames)
                        
                        # Convert to numpy array (16-bit to float32 for better precision)
                        chunk_audio_array = np.frombuffer(chunk_audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                        
                        if sample_rate != chunk_sample_rate:
                            print(f"⚠️ Warning: Sample rate mismatch in chunk {chunk_num}: {chunk_sample_rate} vs {sample_rate}")
                            sample_rate = chunk_sample_rate  # Use the chunk's sample rate
                        
                        combined_audio.append(chunk_audio_array)
                        total_samples_processed += len(chunk_audio_array)
                        
                        if chunk_num <= 5 or chunk_num % 100 == 0 or chunk_num > len(chunks_sorted) - 5:
                            print(f"✅ Added chunk {chunk_num}: {os.path.basename(chunk_path)} ({len(chunk_audio_array)} samples)")
                        
                except Exception as e:
                    print(f"❌ Error reading chunk {chunk_num} ({chunk_path}): {e}")
                    continue
        
        if not combined_audio:
            return None, "❌ No valid audio chunks found to combine"
        
        print(f"[INFO] Concatenating {len(combined_audio)} chunks...")
        print(f"[INFO] Total samples to process: {total_samples_processed}")
        
        # Concatenate all audio using numpy for efficiency
        final_audio = np.concatenate(combined_audio, axis=0)
        
        print(f"[INFO] Final audio array shape: {final_audio.shape}")
        print(f"[INFO] Final audio duration: {len(final_audio) / sample_rate / 60:.2f} minutes")
        
        # Convert back to int16 for WAV format
        final_audio_int16 = (final_audio * 32767).astype(np.int16)
        
        # Create output filename
        output_filename = f"{project_name}_complete.{output_format}"
        output_path = os.path.join("audiobook_projects", project_name, output_filename)
        
        # Save the combined audio file with proper WAV encoding
        print(f"[INFO] Saving combined audio to: {output_path}")
        with wave.open(output_path, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(final_audio_int16.tobytes())
        
        # Verify the saved file
        if os.path.exists(output_path):
            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            
            # Check the saved file duration
            with wave.open(output_path, 'rb') as verify_wav:
                saved_frames = verify_wav.getnframes()
                saved_rate = verify_wav.getframerate()
                saved_duration_minutes = saved_frames / saved_rate / 60
            
            print(f"[INFO] Saved file size: {file_size_mb:.2f} MB")
            print(f"[INFO] Saved file duration: {saved_duration_minutes:.2f} minutes")
            
            if saved_duration_minutes < (len(final_audio) / sample_rate / 60 * 0.95):  # Allow 5% tolerance
                print(f"⚠️ WARNING: Saved file duration ({saved_duration_minutes:.2f} min) is significantly shorter than expected ({len(final_audio) / sample_rate / 60:.2f} min)")
        
        # Calculate total duration
        total_duration_seconds = len(final_audio) / sample_rate
        duration_hours = int(total_duration_seconds // 3600)
        duration_minutes = int((total_duration_seconds % 3600) // 60)
        
        success_message = (
            f"✅ Combined {len(chunks_sorted)} chunks successfully! "
            f"🎵 Total duration: {duration_hours}:{duration_minutes:02d} "
            f"📁 File: {output_filename} "
            f"🔄 Fresh combination of current chunk files"
        )
        
        return output_path, success_message
        
    except Exception as e:
        error_msg = f"❌ Error combining audio chunks: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return None, error_msg

def load_previous_project_audio(project_name: str) -> tuple:
    """Load a previous project's combined audio for download in creation tabs"""
    if not project_name:
        return None, None, "📁 Select a project to load its audio"
    
    # Check if combined file already exists
    safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')
    combined_file = os.path.join("audiobook_projects", project_name, f"{safe_project_name}_complete.wav")
    
    if os.path.exists(combined_file):
        # File already exists, load it
        return combined_file, combined_file, f"✅ Loaded existing combined audio for '{project_name}'"
    else:
        # Create combined file
        audio_path, status = combine_project_audio_chunks(project_name)
        return audio_path, audio_path, status

def save_trimmed_audio(audio_data, original_file_path: str, chunk_num: int) -> tuple:
    """Save trimmed audio data to replace the original file"""
    if not audio_data or not original_file_path:
        return "❌ No audio data to save", None
    
    print(f"[DEBUG] save_trimmed_audio called for chunk {chunk_num}")
    print(f"[DEBUG] audio_data type: {type(audio_data)}")
    print(f"[DEBUG] original_file_path: {original_file_path}")
    
    try:
        # Get project directory and create backup
        project_dir = os.path.dirname(original_file_path)
        backup_file = original_file_path.replace('.wav', f'_backup_original_{int(time.time())}.wav')
        
        # Backup original file
        if os.path.exists(original_file_path):
            shutil.copy2(original_file_path, backup_file)
            print(f"[DEBUG] Created backup: {os.path.basename(backup_file)}")
        
        # Handle different types of audio data from Gradio
        audio_saved = False
        
        if isinstance(audio_data, tuple) and len(audio_data) == 2:
            # Tuple format: (sample_rate, audio_array)
            sample_rate, audio_array = audio_data
            print(f"[DEBUG] Tuple format - sample_rate: {sample_rate}, audio_array shape: {getattr(audio_array, 'shape', 'unknown')}")
            
            # Ensure audio_array is numpy array
            if not isinstance(audio_array, np.ndarray):
                audio_array = np.array(audio_array)
            
            # Handle multi-dimensional arrays
            if len(audio_array.shape) > 1:
                # If stereo, take first channel
                audio_array = audio_array[:, 0] if audio_array.shape[1] > 0 else audio_array.flatten()
            
            # Save trimmed audio as WAV file
            with wave.open(original_file_path, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                
                # Convert to int16 if needed
                if audio_array.dtype != np.int16:
                    if audio_array.dtype == np.float32 or audio_array.dtype == np.float64:
                        # Ensure values are in range [-1, 1] before converting
                        audio_array = np.clip(audio_array, -1.0, 1.0)
                        audio_int16 = (audio_array * 32767).astype(np.int16)
                    else:
                        audio_int16 = audio_array.astype(np.int16)
                else:
                    audio_int16 = audio_array
                
                wav_file.writeframes(audio_int16.tobytes())
            
            audio_saved = True
            print(f"[DEBUG] Saved audio from tuple format: {len(audio_int16)} samples")
            
        elif isinstance(audio_data, str):
            # File path - copy the trimmed file over
            print(f"[DEBUG] String format (file path): {audio_data}")
            if os.path.exists(audio_data):
                shutil.copy2(audio_data, original_file_path)
                audio_saved = True
                print(f"[DEBUG] Copied file from: {audio_data}")
            else:
                print(f"[DEBUG] File not found: {audio_data}")
                return f"❌ Trimmed audio file not found: {audio_data}", None
                
        elif hasattr(audio_data, 'name'):  # Gradio file object
            # Handle Gradio uploaded file
            print(f"[DEBUG] Gradio file object: {audio_data.name}")
            if os.path.exists(audio_data.name):
                shutil.copy2(audio_data.name, original_file_path)
                audio_saved = True
                print(f"[DEBUG] Copied from Gradio file: {audio_data.name}")
            else:
                return f"❌ Gradio file not found: {audio_data.name}", None
                
        else:
            print(f"[DEBUG] Unexpected audio data format: {type(audio_data)}")
            # Try to handle as raw audio data
            try:
                if hasattr(audio_data, '__iter__'):
                    audio_array = np.array(audio_data)
                    sample_rate = 24000  # Default sample rate
                    
                    with wave.open(original_file_path, 'wb') as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(sample_rate)
                        
                        if audio_array.dtype != np.int16:
                            if np.max(np.abs(audio_array)) <= 1.0:
                                audio_int16 = (audio_array * 32767).astype(np.int16)
                            else:
                                audio_int16 = audio_array.astype(np.int16)
                        else:
                            audio_int16 = audio_array
                        
                        wav_file.writeframes(audio_int16.tobytes())
                    
                    audio_saved = True
                    print(f"[DEBUG] Saved as raw audio data: {len(audio_int16)} samples")
                else:
                    return f"❌ Cannot process audio data type: {type(audio_data)}", None
            except Exception as e:
                print(f"[DEBUG] Failed to process as raw audio: {str(e)}")
                return f"❌ Cannot process audio data: {str(e)}", None
        
        if audio_saved:
            status_msg = f"✅ Chunk {chunk_num} trimmed and saved!\n💾 Original backed up as: {os.path.basename(backup_file)}\n🎵 Audio file updated successfully"
            print(f"[DEBUG] Successfully saved trimmed audio for chunk {chunk_num}")
            return status_msg, original_file_path
        else:
            return f"❌ Failed to save trimmed audio for chunk {chunk_num}", None
            
    except Exception as e:
        print(f"[DEBUG] Exception in save_trimmed_audio: {str(e)}")
        return f"❌ Error saving trimmed audio for chunk {chunk_num}: {str(e)}", None

def accept_regenerated_chunk(project_name: str, actual_chunk_num_to_accept: int, regenerated_audio_path: str, current_project_chunks_list: list) -> tuple:
    """Accept the regenerated chunk by replacing the original audio file and deleting the temp file."""
    if not project_name or not regenerated_audio_path:
        return "❌ No regenerated audio to accept", None
    
    try:
        # We already have the correct actual_chunk_num_to_accept and the full list of chunks
        if actual_chunk_num_to_accept < 1 or actual_chunk_num_to_accept > len(current_project_chunks_list):
            return f"❌ Invalid actual chunk number {actual_chunk_num_to_accept}", None
        
        # Find the specific chunk_info using the actual_chunk_num_to_accept
        # This assumes current_project_chunks_list is sorted and chunk_num is 1-based and matches index+1
        # More robust: find it by matching 'chunk_num' field
        chunk_info_to_update = next((c for c in current_project_chunks_list if c['chunk_num'] == actual_chunk_num_to_accept), None)
        
        if not chunk_info_to_update:
            return f"❌ Could not find info for actual chunk {actual_chunk_num_to_accept} in project data.", None
            
        original_audio_file = chunk_info_to_update['audio_file']
        
        # Check if temp file exists
        if not os.path.exists(regenerated_audio_path):
            return f"❌ Regenerated audio file not found: {regenerated_audio_path}", None
        
        # Backup original file (optional, with timestamp)
        backup_file = original_audio_file.replace('.wav', f'_backup_{int(time.time())}.wav')
        if os.path.exists(original_audio_file):
            shutil.copy2(original_audio_file, backup_file)
        
        # Replace original with regenerated
        shutil.move(regenerated_audio_path, original_audio_file)
        
        # Clean up any other temp files for this chunk (in case there are multiple)
        project_dir = os.path.dirname(original_audio_file)
        temp_files = []
        try:
            for file in os.listdir(project_dir):
                # Match temp_regenerated_chunk_ACTUALCHUNKNUM_timestamp.wav
                if file.startswith(f"temp_regenerated_chunk_{actual_chunk_num_to_accept}_") and file.endswith('.wav'):
                    temp_path = os.path.join(project_dir, file)
                    try:
                        os.remove(temp_path)
                        temp_files.append(file)
                        print(f"🗑️ Cleaned up temp file: {file}")
                    except:
                        pass  # Ignore errors when cleaning up
        except Exception as e:
            print(f"⚠️ Warning during temp file cleanup: {str(e)}")
        
        status_msg = f"✅ Chunk {actual_chunk_num_to_accept} regeneration accepted!\n💾 Original backed up as: {os.path.basename(backup_file)}\n🗑️ Cleaned up {len(temp_files)} temporary file(s)"
        
        # Return both status message and the path to the NEW audio file (for interface update)
        return status_msg, original_audio_file
        
    except Exception as e:
        return f"❌ Error accepting chunk {actual_chunk_num_to_accept}: {str(e)}", None

def decline_regenerated_chunk(actual_chunk_num_to_decline: int, regenerated_audio_path: str = None) -> tuple:
    """Decline the regenerated chunk and clean up the temporary file."""
    
    actual_file_path = None
    
    if regenerated_audio_path:
        if isinstance(regenerated_audio_path, tuple):
            print(f"⚠️ Warning: Received tuple instead of file path for chunk {actual_chunk_num_to_decline} decline")
            actual_file_path = None
        elif isinstance(regenerated_audio_path, str):
            actual_file_path = regenerated_audio_path
        else:
            print(f"⚠️ Warning: Unexpected type for regenerated_audio_path: {type(regenerated_audio_path)}")
            actual_file_path = None
    
    if actual_file_path and os.path.exists(actual_file_path):
        try:
            os.remove(actual_file_path)
            print(f"🗑️ Cleaned up declined regeneration for chunk {actual_chunk_num_to_decline}: {os.path.basename(actual_file_path)}")
        except Exception as e:
            print(f"⚠️ Warning: Could not clean up temp file for chunk {actual_chunk_num_to_decline}: {str(e)}")
    
    return (
        gr.Audio(visible=False),  # Hide regenerated audio
        gr.Row(visible=False),    # Hide accept/decline buttons
        f"❌ Chunk {actual_chunk_num_to_decline} regeneration declined. Keeping original audio."
    )

def force_complete_project_refresh():
    """Force a complete refresh of project data, clearing any potential caches"""
    try:
        # Force reload of projects from filesystem
        import importlib
        import sys
        
        # Clear any module-level caches
        if hasattr(sys.modules[__name__], '_project_cache'):
            delattr(sys.modules[__name__], '_project_cache')
        
        # Get fresh project list
        projects = get_existing_projects()
        choices = get_project_choices()
        
        print(f"🔄 Complete refresh: Found {len(projects)} projects")
        for project in projects[:5]:  # Show first 5 projects
            print(f"  - {project['name']} ({project.get('audio_count', 0)} files)")
        
        return gr.Dropdown(choices=choices, value=None)
        
    except Exception as e:
        print(f"Error in complete refresh: {str(e)}")
        error_choices = [("Error loading projects", None)]
        return gr.Dropdown(choices=error_choices, value=None)

def cleanup_project_temp_files(project_name: str) -> str:
    """Clean up any temporary files in a project directory"""
    if not project_name:
        return "❌ No project name provided"
    
    try:
        project_dir = os.path.join("audiobook_projects", project_name)
        if not os.path.exists(project_dir):
            return f"❌ Project directory not found: {project_dir}"
        
        temp_files_removed = 0
        temp_patterns = ['temp_regenerated_', '_backup_original_']
        
        for file in os.listdir(project_dir):
            if any(pattern in file for pattern in temp_patterns) and file.endswith('.wav'):
                file_path = os.path.join(project_dir, file)
                try:
                    os.remove(file_path)
                    temp_files_removed += 1
                    print(f"🗑️ Removed temp file: {file}")
                except Exception as e:
                    print(f"⚠️ Could not remove {file}: {str(e)}")
        
        if temp_files_removed > 0:
            return f"✅ Cleaned up {temp_files_removed} temporary file(s) from project '{project_name}'"
        else:
            return f"✅ No temporary files found in project '{project_name}'"
            
    except Exception as e:
        return f"❌ Error cleaning up temp files: {str(e)}"

def handle_audio_trimming(audio_data) -> tuple:
    """Handle audio trimming from Gradio audio component
    
    When users select a portion of audio in Gradio's waveform, we need to extract 
    that specific segment. This function attempts to work with Gradio's trimming data.
    """
    if not audio_data:
        return None, "❌ No audio data provided"
    
    print(f"[DEBUG] handle_audio_trimming called with data type: {type(audio_data)}")
    
    try:
        if isinstance(audio_data, tuple) and len(audio_data) == 2:
            # Standard format: (sample_rate, audio_array)
            sample_rate, audio_array = audio_data
            
            # Check if this is the full audio or a trimmed segment
            if hasattr(audio_array, 'shape'):
                print(f"[DEBUG] Audio shape: {audio_array.shape}, sample_rate: {sample_rate}")
                # For now, return the audio as-is since Gradio trimming is complex
                return audio_data, f"✅ Audio loaded - {len(audio_array)} samples at {sample_rate}Hz"
            else:
                return None, "❌ Invalid audio array format"
        else:
            return None, "❌ Invalid audio data format"
            
    except Exception as e:
        print(f"[DEBUG] Error in handle_audio_trimming: {str(e)}")
        return None, f"❌ Error processing audio: {str(e)}"

def extract_audio_segment(audio_data, start_time: float = None, end_time: float = None) -> tuple:
    """Extract a specific time segment from audio data
    
    Args:
        audio_data: Tuple of (sample_rate, audio_array)
        start_time: Start time in seconds (None = beginning)
        end_time: End time in seconds (None = end)
    """
    if not audio_data or not isinstance(audio_data, tuple) or len(audio_data) != 2:
        return None, "❌ Invalid audio data"
    
    try:
        sample_rate, audio_array = audio_data
        
        if not hasattr(audio_array, 'shape'):
            return None, "❌ Invalid audio array"
        
        # Handle multi-dimensional arrays
        if len(audio_array.shape) > 1:
            # Take first channel if stereo
            audio_array = audio_array[:, 0] if audio_array.shape[1] > 0 else audio_array.flatten()
        
        total_samples = len(audio_array)
        total_duration = total_samples / sample_rate
        
        # Calculate sample indices
        start_sample = 0 if start_time is None else int(start_time * sample_rate)
        end_sample = total_samples if end_time is None else int(end_time * sample_rate)
        
        # Ensure valid bounds
        start_sample = max(0, min(start_sample, total_samples))
        end_sample = max(start_sample, min(end_sample, total_samples))
        
        # Extract segment
        trimmed_audio = audio_array[start_sample:end_sample]
        
        trimmed_duration = len(trimmed_audio) / sample_rate
        
        status_msg = f"✅ Extracted segment: {trimmed_duration:.2f}s (from {start_time or 0:.2f}s to {end_time or total_duration:.2f}s)"
        
        return (sample_rate, trimmed_audio), status_msg
        
    except Exception as e:
        return None, f"❌ Error extracting segment: {str(e)}"

def save_visual_trim_to_file(audio_data, original_file_path: str, chunk_num: int) -> tuple:
    """Save visually trimmed audio from Gradio audio component to file, directly overwriting the original chunk file."""
    import wave
    import numpy as np
    import os

    if not audio_data or not original_file_path:
        return "❌ No audio data to save", None

    print(f"[DEBUG] Direct save_visual_trim_to_file called for chunk {chunk_num}")
    print(f"[DEBUG] Audio data type: {type(audio_data)}")
    print(f"[DEBUG] Original file path: {original_file_path}")

    try:
        if not os.path.exists(os.path.dirname(original_file_path)):
            return f"❌ Error: Directory for original file does not exist: {os.path.dirname(original_file_path)}", None

        if isinstance(audio_data, tuple) and len(audio_data) == 2:
            sample_rate, audio_array = audio_data
            if not isinstance(audio_array, np.ndarray):
                audio_array = np.array(audio_array)
            if len(audio_array.shape) > 1:
                audio_array = audio_array[:, 0] if audio_array.shape[1] > 0 else audio_array.flatten()

            print(f"[DEBUG] Saving chunk {chunk_num} - Sample rate: {sample_rate}, Trimmed array length: {len(audio_array)}")

            with wave.open(original_file_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                if audio_array.dtype != np.int16:
                    if audio_array.dtype == np.float32 or audio_array.dtype == np.float64:
                        audio_array = np.clip(audio_array, -1.0, 1.0)
                        audio_int16 = (audio_array * 32767).astype(np.int16)
                    else:
                        audio_int16 = audio_array.astype(np.int16)
                else:
                    audio_int16 = audio_array
                wav_file.writeframes(audio_int16.tobytes())
            
            duration_seconds = len(audio_int16) / sample_rate
            status_msg = f"✅ Chunk {chunk_num} trimmed & directly saved! New duration: {duration_seconds:.2f}s. Original overwritten."
            print(f"[INFO] Chunk {chunk_num} saved to {original_file_path}, duration {duration_seconds:.2f}s.")
            return status_msg, original_file_path
        else:
            print(f"[ERROR] Invalid audio format for chunk {chunk_num}: expected (sample_rate, array) tuple, got {type(audio_data)}")
            return f"❌ Invalid audio format for chunk {chunk_num}: expected (sample_rate, array) tuple", None
    except Exception as e:
        print(f"[ERROR] Exception in save_visual_trim_to_file for chunk {chunk_num}: {str(e)}")
        return f"❌ Error saving audio for chunk {chunk_num}: {str(e)}", None

def auto_save_visual_trims_and_download(project_name: str) -> tuple:
    """Enhanced download that attempts to save any pending visual trims and then downloads"""
    if not project_name:
        return None, "❌ No project selected"
    
    # Standard download functionality
    download_result = combine_project_audio_chunks(project_name)
    
    if download_result[0]:  # If download was successful
        success_msg = download_result[1] + "\n\n🎵 Note: If you made visual trims but didn't save them, use the 'Save Trimmed Chunk' buttons first, then refresh download"
        return download_result[0], success_msg
    else:
        return download_result

def save_all_pending_trims_and_combine(project_name: str, loaded_chunks_data: list, *all_audio_component_values) -> str:
    """
    Automatically saves visual trims from displayed audio components for the current project,
    then creates split downloadable files.
    """
    if not project_name:
        return "❌ No project selected for download."
    if not loaded_chunks_data:
        return "❌ No chunks loaded for the project to save or combine."

    print(f"[INFO] Auto-saving trims for project '{project_name}' before creating split files.")
    auto_save_reports = []

    num_loaded_chunks = len(loaded_chunks_data)
    num_audio_components_passed = len(all_audio_component_values)
    
    # Only process chunks that have corresponding audio players in the interface
    max_chunks_to_process = min(num_loaded_chunks, num_audio_components_passed, MAX_CHUNKS_FOR_INTERFACE)
    
    print(f"[INFO] Project has {num_loaded_chunks} total chunks, processing first {max_chunks_to_process} for auto-save.")

    for i in range(max_chunks_to_process):
        chunk_info = loaded_chunks_data[i]
        chunk_num = chunk_info['chunk_num']
        original_file_path = chunk_info['audio_file']

        current_audio_data_from_player = all_audio_component_values[i]
        if current_audio_data_from_player:  # If there's audio in the player (e.g., (sample_rate, data))
            print(f"[DEBUG] Auto-saving trim for chunk {chunk_num} (Audio data type: {type(current_audio_data_from_player)})")
            status_msg, _ = save_visual_trim_to_file(current_audio_data_from_player, original_file_path, chunk_num)
            auto_save_reports.append(f"Chunk {chunk_num}: {status_msg.splitlines()[0]}") # Take first line of status
        else:
            auto_save_reports.append(f"Chunk {chunk_num}: No audio data in player; skipping auto-save.")

    # After attempting to save all trims from displayed chunks, create split files instead of one massive file
    print(f"[INFO] Creating split MP3 files for project '{project_name}' after auto-save attempts.")
    split_result = combine_project_audio_chunks_split(project_name)
    
    final_status_message = split_result
    if auto_save_reports:
        auto_save_summary = f"Auto-saved trims for {max_chunks_to_process} displayed chunks out of {num_loaded_chunks} total chunks."
        final_status_message = f"--- Auto-Save Report ---\n{auto_save_summary}\n" + "\n".join(auto_save_reports[:10])  # Show first 10 reports
        if len(auto_save_reports) > 10:
            final_status_message += f"\n... and {len(auto_save_reports) - 10} more auto-saves."
        final_status_message += f"\n\n{split_result}"
        
    return final_status_message

def combine_project_audio_chunks_split(project_name: str, chunks_per_file: int = 50, output_format: str = "mp3") -> str:
    """Create multiple smaller downloadable MP3 files from project chunks"""
    if not project_name:
        return "❌ No project selected"
    
    chunks = get_project_chunks(project_name)
    
    if not chunks:
        return f"❌ No audio chunks found in project '{project_name}'"
    
    try:
        # Check if pydub is available for MP3 export
        try:
            from pydub import AudioSegment
            mp3_available = True
        except ImportError:
            mp3_available = False
            output_format = "wav"  # Fallback to WAV
            print("[WARNING] pydub not available, using WAV format instead of MP3")
        
        sample_rate = 24000  # Default sample rate
        
        # Sort chunks by chunk number to ensure correct order
        def extract_chunk_number(chunk_info):
            """Extract chunk number from chunk info for proper numerical sorting"""
            try:
                # First try to get chunk_num directly from the chunk info
                chunk_num = chunk_info.get('chunk_num')
                if chunk_num is not None:
                    return int(chunk_num)  # Ensure it's an integer
            except (ValueError, TypeError):
                pass
            
            # Fallback: try to extract from filename
            try:
                filename = chunk_info.get('audio_filename', '') or chunk_info.get('audio_file', '')
                if filename:
                    import re
                    # Look for patterns like "_123.wav" or "_chunk_123.wav"
                    match = re.search(r'_(\d+)\.wav$', filename)
                    if match:
                        return int(match.group(1))
                    
                    # Try other patterns like "projectname_123.wav"
                    match = re.search(r'(\d+)\.wav$', filename)
                    if match:
                        return int(match.group(1))
            except (ValueError, TypeError, AttributeError):
                pass
            
            # Last resort: return 0 (should sort first)
            print(f"[WARNING] Could not extract chunk number from: {chunk_info}")
            return 0
        
        chunks_sorted = sorted(chunks, key=extract_chunk_number)
        
        # Debug: Show first and last few chunk numbers to verify sorting
        if len(chunks_sorted) > 0:
            first_few = [extract_chunk_number(c) for c in chunks_sorted[:5]]
            last_few = [extract_chunk_number(c) for c in chunks_sorted[-5:]]
            print(f"[DEBUG] First 5 chunk numbers after sorting: {first_few}")
            print(f"[DEBUG] Last 5 chunk numbers after sorting: {last_few}")
            
            # NEW: Also show the actual filenames to verify they match the chunk numbers
            first_few_files = [os.path.basename(c.get('audio_file', 'unknown')) for c in chunks_sorted[:5]]
            last_few_files = [os.path.basename(c.get('audio_file', 'unknown')) for c in chunks_sorted[-5:]]
            print(f"[DEBUG] First 5 filenames after sorting: {first_few_files}")
            print(f"[DEBUG] Last 5 filenames after sorting: {last_few_files}")
        
        print(f"[INFO] Creating {len(chunks_sorted)} chunks into multiple {output_format.upper()} files ({chunks_per_file} chunks per file)")
        
        created_files = []
        total_duration_seconds = 0
        
        # Process chunks in groups
        for file_index in range(0, len(chunks_sorted), chunks_per_file):
            file_end = min(file_index + chunks_per_file, len(chunks_sorted))
            file_chunks = chunks_sorted[file_index:file_end]
            
            file_number = (file_index // chunks_per_file) + 1
            
            # Use actual chunk numbers from the files, not array indices
            chunk_start = extract_chunk_number(file_chunks[0]) if file_chunks else file_index + 1
            chunk_end = extract_chunk_number(file_chunks[-1]) if file_chunks else file_end
            
            print(f"[INFO] Creating file {file_number}: chunks {chunk_start}-{chunk_end}")
            
            # Debug: Show which files will be processed for this part
            if len(file_chunks) > 0:
                first_files = [os.path.basename(c.get('audio_file', 'unknown')) for c in file_chunks[:3]]
                last_files = [os.path.basename(c.get('audio_file', 'unknown')) for c in file_chunks[-3:]]
                print(f"[DEBUG] Part {file_number} - First 3 files: {first_files}")
                print(f"[DEBUG] Part {file_number} - Last 3 files: {last_files}")
            
            combined_audio = []
            
            for chunk_info in file_chunks:
                chunk_path = chunk_info.get('audio_file')
                chunk_num = extract_chunk_number(chunk_info)
                
                if not chunk_path or not os.path.exists(chunk_path):
                    print(f"⚠️ Warning: Chunk {chunk_num} file not found: {chunk_path}")
                    continue
                
                try:
                    with wave.open(chunk_path, 'rb') as wav_file:
                        chunk_sample_rate = wav_file.getframerate()
                        chunk_frames = wav_file.getnframes()
                        chunk_audio_data = wav_file.readframes(chunk_frames)
                        
                        # Convert to numpy array
                        chunk_audio_array = np.frombuffer(chunk_audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                        
                        if sample_rate != chunk_sample_rate:
                            sample_rate = chunk_sample_rate
                        
                        combined_audio.append(chunk_audio_array)
                        
                except Exception as e:
                    print(f"❌ Error reading chunk {chunk_num} ({chunk_path}): {e}")
                    continue
            
            if not combined_audio:
                print(f"⚠️ No valid chunks found for file {file_number}")
                continue
            
            # Concatenate audio for this file
            file_audio = np.concatenate(combined_audio, axis=0)
            file_duration_seconds = len(file_audio) / sample_rate
            total_duration_seconds += file_duration_seconds
            
            # Convert back to int16 for audio processing
            file_audio_int16 = (file_audio * 32767).astype(np.int16)
            
            # Create output filename
            output_filename = f"{project_name}_part{file_number:02d}_chunks{chunk_start:03d}-{chunk_end:03d}.{output_format}"
            output_path = os.path.join("audiobook_projects", project_name, output_filename)
            
            if mp3_available and output_format == "mp3":
                # Use pydub to create MP3 with good compression
                audio_segment = AudioSegment(
                    file_audio_int16.tobytes(),
                    frame_rate=sample_rate,
                    sample_width=2,
                    channels=1
                )
                # Export as MP3 with good quality settings
                audio_segment.export(output_path, format="mp3", bitrate="128k")
            else:
                # Save as WAV file
                with wave.open(output_path, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(file_audio_int16.tobytes())
            
            if os.path.exists(output_path):
                file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                file_duration_minutes = file_duration_seconds / 60
                
                created_files.append({
                    'filename': output_filename,
                    'chunks': f"{chunk_start}-{chunk_end}",
                    'duration_minutes': file_duration_minutes,
                    'size_mb': file_size_mb
                })
                
                print(f"✅ Created {output_filename}: {file_duration_minutes:.2f} minutes, {file_size_mb:.2f} MB")
        
        if not created_files:
            return "❌ No files were created"
        
        # Calculate total statistics
        total_duration_minutes = total_duration_seconds / 60
        total_duration_hours = int(total_duration_minutes // 60)
        remaining_minutes = int(total_duration_minutes % 60)
        total_size_mb = sum(f['size_mb'] for f in created_files)
        
        # Create a summary of all created files
        file_list = "\n".join([
            f"📁 {f['filename']} - Chunks {f['chunks']} - {f['duration_minutes']:.1f} min - {f['size_mb']:.1f} MB"
            for f in created_files
        ])
        
        format_display = output_format.upper()
        size_comparison = f"📦 Total size: {total_size_mb:.1f} MB ({format_display} format" + (f" - ~70% smaller than WAV!" if output_format == "mp3" else "") + ")"
        
        success_message = (
            f"✅ Created {len(created_files)} downloadable {format_display} files from {len(chunks_sorted)} chunks!\n"
            f"🎵 Total duration: {total_duration_hours}h {remaining_minutes}m\n"
            f"{size_comparison}\n\n"
            f"📁 **Files are saved in your project folder:**\n"
            f"📂 Navigate to: audiobook_projects/{project_name}/\n\n"
            f"📋 Files created:\n{file_list}\n\n"
            f"💡 **Tip:** Browse to your project folder to download individual {format_display} files!"
        )
        
        return success_message
        
    except Exception as e:
        error_msg = f"❌ Error creating split audio files: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return error_msg

# =============================================================================
# VOLUME NORMALIZATION SYSTEM
# =============================================================================

def analyze_audio_level(audio_data, sample_rate=24000):
    """
    Analyze the audio level and return various volume metrics.
    
    Args:
        audio_data: Audio array (numpy array)
        sample_rate: Sample rate of the audio
        
    Returns:
        dict: Dictionary with volume metrics
    """
    try:
        # Convert to numpy if it's a tensor
        if hasattr(audio_data, 'cpu'):
            audio_data = audio_data.cpu().numpy()
        
        # Ensure it's 1D
        if len(audio_data.shape) > 1:
            audio_data = audio_data.flatten()
        
        # RMS (Root Mean Square) level
        rms = np.sqrt(np.mean(audio_data**2))
        rms_db = 20 * np.log10(rms + 1e-10)  # Add small value to avoid log(0)
        
        # Peak level
        peak = np.max(np.abs(audio_data))
        peak_db = 20 * np.log10(peak + 1e-10)
        
        # LUFS (Loudness Units relative to Full Scale) - approximation
        # Apply K-weighting filter (simplified)
        try:
            # High-shelf filter at 4kHz
            sos_high = signal.butter(2, 4000, 'highpass', fs=sample_rate, output='sos')
            filtered_high = signal.sosfilt(sos_high, audio_data)
            
            # High-frequency emphasis
            sos_shelf = signal.butter(2, 1500, 'highpass', fs=sample_rate, output='sos')
            filtered_shelf = signal.sosfilt(sos_shelf, filtered_high)
            
            # Mean square and convert to LUFS
            ms = np.mean(filtered_shelf**2)
            lufs = -0.691 + 10 * np.log10(ms + 1e-10)
        except:
            # Fallback if filtering fails
            lufs = rms_db
        
        return {
            'rms_db': float(rms_db),
            'peak_db': float(peak_db),
            'lufs': float(lufs),
            'duration': len(audio_data) / sample_rate
        }
        
    except Exception as e:
        print(f"⚠️ Error analyzing audio level: {str(e)}")
        return {'rms_db': -40.0, 'peak_db': -20.0, 'lufs': -23.0, 'duration': 0.0}

def normalize_audio_to_target(audio_data, current_level_db, target_level_db, method='rms'):
    """
    Normalize audio to a target decibel level.
    
    Args:
        audio_data: Audio array to normalize
        current_level_db: Current level in dB
        target_level_db: Target level in dB
        method: Method to use ('rms', 'peak', or 'lufs')
        
    Returns:
        numpy.ndarray: Normalized audio data
    """
    try:
        # Convert to numpy if it's a tensor
        if hasattr(audio_data, 'cpu'):
            audio_data = audio_data.cpu().numpy()
        
        # Calculate gain needed
        gain_db = target_level_db - current_level_db
        gain_linear = 10 ** (gain_db / 20)
        
        # Apply gain with limiting to prevent clipping
        normalized_audio = audio_data * gain_linear
        
        # Soft limiting to prevent clipping
        max_val = np.max(np.abs(normalized_audio))
        if max_val > 0.95:  # Leave some headroom
            limiter_gain = 0.95 / max_val
            normalized_audio = normalized_audio * limiter_gain
            print(f"🔧 Applied soft limiting (gain: {limiter_gain:.3f}) to prevent clipping")
        
        return normalized_audio
        
    except Exception as e:
        print(f"⚠️ Error normalizing audio: {str(e)}")
        return audio_data

def apply_volume_preset(preset_name: str, target_level: float):
    """Apply professional volume preset and return updated target level with status"""
    presets = {
        "audiobook": -18.0,
        "podcast": -16.0,
        "broadcast": -23.0,
        "custom": target_level
    }
    
    new_target = presets.get(preset_name, target_level)
    
    status_messages = {
        "audiobook": f"📚 Audiobook Standard: {new_target} dB RMS (Professional audiobook level)",
        "podcast": f"🎙️ Podcast Standard: {new_target} dB RMS (Optimized for streaming)",
        "broadcast": f"📺 Broadcast Standard: {new_target} dB RMS (TV/Radio compliance)",
        "custom": f"🎛️ Custom Level: {new_target} dB RMS (User-defined)"
    }
    
    status = status_messages.get(preset_name, f"Custom: {new_target} dB")
    
    return new_target, f"<div class='voice-status'>{status}</div>"

def get_volume_normalization_status(enable_norm, target_db, audio_file):
    """Get status message for volume normalization settings"""
    if not enable_norm:
        return "<div class='voice-status'>🔧 Volume normalization disabled</div>"
    
    if not audio_file:
        return f"<div class='voice-status'>🎯 Will normalize to {target_db:.0f} dB when audio is uploaded</div>"
    
    try:
        audio_data, sample_rate = librosa.load(audio_file, sr=24000)
        level_info = analyze_audio_level(audio_data, sample_rate)
        current_rms = level_info['rms_db']
        gain_needed = target_db - current_rms
        
        if abs(gain_needed) < 1:
            return f"<div class='voice-status'>✅ Audio already close to target ({current_rms:.1f} dB)</div>"
        elif gain_needed > 0:
            return f"<div class='voice-status'>⬆️ Will boost by {gain_needed:.1f} dB ({current_rms:.1f} → {target_db:.0f} dB)</div>"
        else:
            return f"<div class='voice-status'>⬇️ Will reduce by {abs(gain_needed):.1f} dB ({current_rms:.1f} → {target_db:.0f} dB)</div>"
    except:
        return f"<div class='voice-status'>🎯 Will normalize to {target_db:.0f} dB</div>"

# =============================================================================
# END VOLUME NORMALIZATION SYSTEM
# =============================================================================

# =============================================================================
# VOLUME NORMALIZATION WRAPPER FUNCTIONS
# =============================================================================

def create_audiobook_with_volume_settings(model, text_content, voice_library_path, selected_voice, project_name, 
                                         enable_norm=True, target_level=-18.0):
    """Wrapper for create_audiobook that applies volume normalization settings"""
    # Get the voice config and temporarily apply volume settings
    voice_config = get_voice_config(voice_library_path, selected_voice)
    if voice_config:
        # Temporarily override volume settings
        voice_config['normalization_enabled'] = enable_norm
        voice_config['target_level_db'] = target_level
        
        # Save temporarily modified config
        temp_voice_name = selected_voice + "_temp_volume"
        save_voice_profile(
            voice_library_path, temp_voice_name, 
            voice_config.get('display_name', selected_voice),
            voice_config.get('description', ''),
            voice_config['audio_file'],
            voice_config.get('exaggeration', 0.5),
            voice_config.get('cfg_weight', 0.5), 
            voice_config.get('temperature', 0.8),
            enable_norm, target_level
        )
        
        # Use the temporary voice for audiobook creation
        result = create_audiobook(model, text_content, voice_library_path, temp_voice_name, project_name)
        
        # Clean up temporary voice
        try:
            delete_voice_profile(voice_library_path, temp_voice_name)
        except:
            pass
        
        return result
    else:
        return create_audiobook(model, text_content, voice_library_path, selected_voice, project_name)

def create_multi_voice_audiobook_with_volume_settings(model, text_content, voice_library_path, project_name, 
                                                     voice_assignments, enable_norm=True, target_level=-18.0):
    """Wrapper for multi-voice audiobook creation that applies volume normalization settings"""
    # Apply volume settings to all voice assignments
    if enable_norm:
        temp_assignments = {}
        for character, voice_name in voice_assignments.items():
            voice_config = get_voice_config(voice_library_path, voice_name)
            if voice_config:
                # Create temporary voice with volume settings
                temp_voice_name = voice_name + "_temp_volume"
                save_voice_profile(
                    voice_library_path, temp_voice_name,
                    voice_config.get('display_name', voice_name),
                    voice_config.get('description', ''),
                    voice_config['audio_file'],
                    voice_config.get('exaggeration', 0.5),
                    voice_config.get('cfg_weight', 0.5),
                    voice_config.get('temperature', 0.8),
                    enable_norm, target_level
                )
                temp_assignments[character] = temp_voice_name
            else:
                temp_assignments[character] = voice_name
        
        # Use temporary voices for audiobook creation
        result = create_multi_voice_audiobook_with_assignments(
            model, text_content, voice_library_path, project_name, temp_assignments
        )
        
        # Clean up temporary voices
        for character, temp_voice_name in temp_assignments.items():
            if temp_voice_name.endswith("_temp_volume"):
                try:
                    delete_voice_profile(voice_library_path, temp_voice_name)
                except:
                    pass
        
        return result
    else:
        return create_multi_voice_audiobook_with_assignments(
            model, text_content, voice_library_path, project_name, voice_assignments
        )

# =============================================================================
# END VOLUME NORMALIZATION WRAPPER FUNCTIONS  
# =============================================================================

with gr.Blocks(css=css, title="Chatterbox TTS - Audiobook Edition") as demo:
    model_state = gr.State(None)
    voice_library_path_state = gr.State(SAVED_VOICE_LIBRARY_PATH)
    
    gr.HTML("""
    <div class="voice-library-header">
        <h1>🎧 Chatterbox TTS - Audiobook Edition</h1>
        <p>Professional voice cloning for audiobook creation</p>
    </div>
    """)
    
    with gr.Tabs():
        
        # Enhanced TTS Tab with Voice Selection
        with gr.TabItem("🎤 Text-to-Speech", id="tts"):
            with gr.Row():
                with gr.Column():
                    text = gr.Textbox(
                        value="Welcome to Chatterbox TTS Audiobook Edition. This tool will help you create amazing audiobooks with consistent character voices.",
                        label="Text to synthesize",
                        lines=3
                    )
                    
                    # Voice Selection Section
                    with gr.Group():
                        gr.HTML("<h4>🎭 Voice Selection</h4>")
                        tts_voice_selector = gr.Dropdown(
                            choices=get_voice_choices(SAVED_VOICE_LIBRARY_PATH),
                            label="Choose Voice",
                            value=None,
                            info="Select a saved voice profile or use manual input"
                        )
                        
                        # Voice status display
                        tts_voice_status = gr.HTML(
                            "<div class='voice-status'>📝 Manual input mode - upload your own audio file below</div>"
                        )
                    
                    # Audio input (conditionally visible)
                    ref_wav = gr.Audio(
                        sources=["upload", "microphone"], 
                        type="filepath", 
                        label="Reference Audio File (Manual Input)", 
                        value=None,
                        visible=True
                    )
                    
                    with gr.Row():
                        exaggeration = gr.Slider(
                            0.25, 2, step=.05, 
                            label="Exaggeration (Neutral = 0.5)", 
                            value=.5
                        )
                        cfg_weight = gr.Slider(
                            0.2, 1, step=.05, 
                            label="CFG/Pace", 
                            value=0.5
                        )

                    with gr.Accordion("⚙️ Advanced Options", open=False):
                        seed_num = gr.Number(value=0, label="Random seed (0 for random)")
                        temp = gr.Slider(0.05, 5, step=.05, label="Temperature", value=.8)

                    with gr.Row():
                        run_btn = gr.Button("🎵 Generate Speech", variant="primary", size="lg")
                        refresh_voices_btn = gr.Button("🔄 Refresh Voices", size="sm")

                with gr.Column():
                    audio_output = gr.Audio(label="Generated Audio")
                    
                    gr.HTML("""
                    <div class="instruction-box">
                        <h4>💡 TTS Tips:</h4>
                        <ul>
                            <li><strong>Voice Selection:</strong> Choose a saved voice for consistent character voices</li>
                            <li><strong>Reference Audio:</strong> 10-30 seconds of clear speech works best</li>
                            <li><strong>Exaggeration:</strong> 0.3-0.7 for most voices, higher for dramatic effect</li>
                            <li><strong>CFG/Pace:</strong> Lower values = slower, more deliberate speech</li>
                            <li><strong>Temperature:</strong> Higher values = more variation, lower = more consistent</li>
                        </ul>
                    </div>
                    """)

        # Voice Library Tab
        with gr.TabItem("📚 Voice Library", id="voices"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.HTML("<h3>🎭 Voice Management</h3>")
                    
                    # Voice Library Settings
                    with gr.Group():
                        gr.HTML("<h4>📁 Library Settings</h4>")
                        voice_library_path = gr.Textbox(
                            value=SAVED_VOICE_LIBRARY_PATH,
                            label="Voice Library Folder",
                            placeholder="Enter path to voice library folder",
                            info="This path will be remembered between sessions"
                        )
                        update_path_btn = gr.Button("💾 Save & Update Library Path", size="sm")
                        
                        # Configuration status
                        config_status = gr.HTML(
                            f"<div class='config-status'>📂 Current library: {SAVED_VOICE_LIBRARY_PATH}</div>"
                        )
                    
                    # Voice Selection
                    with gr.Group():
                        gr.HTML("<h4>🎯 Select Voice</h4>")
                        voice_dropdown = gr.Dropdown(
                            choices=[],
                            label="Saved Voice Profiles",
                            value=None
                        )
                        
                        with gr.Row():
                            load_voice_btn = gr.Button("📥 Load Voice", size="sm")
                            refresh_btn = gr.Button("🔄 Refresh", size="sm")
                            delete_voice_btn = gr.Button("🗑️ Delete", size="sm", variant="stop")
                
                with gr.Column(scale=2):
                    # Voice Testing & Saving
                    gr.HTML("<h3>🎙️ Voice Testing & Configuration</h3>")
                    
                    with gr.Group():
                        gr.HTML("<h4>📝 Voice Details</h4>")
                        voice_name = gr.Textbox(label="Voice Name", placeholder="e.g., narrator_male_deep")
                        voice_display_name = gr.Textbox(label="Display Name", placeholder="e.g., Deep Male Narrator")
                        voice_description = gr.Textbox(
                            label="Description", 
                            placeholder="e.g., Deep, authoritative voice for main character",
                            lines=2
                        )
                    
                    with gr.Group():
                        gr.HTML("<h4>🎵 Voice Settings</h4>")
                        voice_audio = gr.Audio(
                            sources=["upload", "microphone"],
                            type="filepath",
                            label="Reference Audio"
                        )
                        
                        with gr.Row():
                            voice_exaggeration = gr.Slider(
                                0.25, 2, step=.05,
                                label="Exaggeration",
                                value=0.5
                            )
                            voice_cfg = gr.Slider(
                                0.2, 1, step=.05,
                                label="CFG/Pace",
                                value=0.5
                            )
                            voice_temp = gr.Slider(
                                0.05, 5, step=.05,
                                label="Temperature",
                                value=0.8
                            )
                    
                    # Volume Normalization Section
                    with gr.Group():
                        gr.HTML("<h4>🎚️ Volume Normalization</h4>")
                        
                        enable_voice_normalization = gr.Checkbox(
                            label="Enable Volume Normalization",
                            value=False,
                            info="Automatically adjust audio level to professional standards"
                        )
                        
                        with gr.Row():
                            volume_preset_dropdown = gr.Dropdown(
                                choices=[
                                    ("📚 Audiobook Standard (-18 dB)", "audiobook"),
                                    ("🎙️ Podcast Standard (-16 dB)", "podcast"),
                                    ("📺 Broadcast Standard (-23 dB)", "broadcast"),
                                    ("🎛️ Custom Level", "custom")
                                ],
                                label="Volume Preset",
                                value="audiobook",
                                interactive=True
                            )
                            
                            target_volume_level = gr.Slider(
                                -30.0, -6.0, 
                                step=0.5,
                                label="Target Level (dB RMS)",
                                value=-18.0,
                                interactive=True,
                                info="Professional audiobook: -18dB, Podcast: -16dB"
                            )
                        
                        # Volume status display
                        volume_status = gr.HTML(
                            "<div class='voice-status'>🔧 Volume normalization disabled</div>"
                        )
                    
                    # Test Voice
                    with gr.Group():
                        gr.HTML("<h4>🧪 Test Voice</h4>")
                        test_text = gr.Textbox(
                            value="Hello, this is a test of the voice settings. How does this sound?",
                            label="Test Text",
                            lines=2
                        )
                        
                        with gr.Row():
                            test_voice_btn = gr.Button("🎵 Test Voice", variant="secondary")
                            save_voice_btn = gr.Button("💾 Save Voice Profile", variant="primary")
                        
                        test_audio_output = gr.Audio(label="Test Audio Output")
                        
                        # Status messages
                        voice_status = gr.HTML("<div class='voice-status'>Ready to test and save voices...</div>")

        # Enhanced Audiobook Creation Tab
        with gr.TabItem("📖 Audiobook Creation - Single Sample", id="audiobook_single"):
            gr.HTML("""
            <div class="audiobook-header">
                <h2>📖 Audiobook Creation Studio - Single Voice</h2>
                <p>Transform your text into professional audiobooks with one consistent voice</p>
            </div>
            """)
            
            with gr.Row():
                with gr.Column(scale=2):
                    # Text Input Section
                    with gr.Group():
                        gr.HTML("<h3>📝 Text Content</h3>")
                        
                        with gr.Row():
                            with gr.Column(scale=3):
                                audiobook_text = gr.Textbox(
                                    label="Audiobook Text",
                                    placeholder="Paste your text here or upload a file below...",
                                    lines=12,
                                    max_lines=20,
                                    info="Text will be split into chunks at sentence boundaries"
                                )
                            
                            with gr.Column(scale=1):
                                # File upload
                                text_file = gr.File(
                                    label="📄 Upload Text File",
                                    file_types=[".txt", ".md", ".rtf"],
                                    type="filepath"
                                )
                                
                                load_file_btn = gr.Button(
                                    "📂 Load File", 
                                    size="sm",
                                    variant="secondary"
                                )
                                
                                # File status
                                file_status = gr.HTML(
                                    "<div class='file-status'>📄 No file loaded</div>"
                                )
                    # NEW: Project Management Section
                    with gr.Group():
                        gr.HTML("<h3>📁 Project Management</h3>")
                        single_project_dropdown = gr.Dropdown(
                            choices=get_project_choices(),
                            label="Select Existing Project",
                            value=None,
                            info="Load or resume an existing project"
                        )
                        with gr.Row():
                            load_project_btn = gr.Button("📂 Load Project", size="sm", variant="secondary")
                            resume_project_btn = gr.Button("▶️ Resume Project", size="sm", variant="primary")
                        single_project_progress = gr.HTML("<div class='voice-status'>No project loaded</div>")
                
                with gr.Column(scale=1):
                    # Voice Selection & Project Settings
                    with gr.Group():
                        gr.HTML("<h3>🎭 Voice Configuration</h3>")
                        
                        audiobook_voice_selector = gr.Dropdown(
                            choices=get_audiobook_voice_choices(SAVED_VOICE_LIBRARY_PATH),
                            label="Select Voice",
                            value=None,
                            info="Choose from your saved voice profiles"
                        )
                        
                        refresh_audiobook_voices_btn = gr.Button(
                            "🔄 Refresh Voices", 
                            size="sm"
                        )
                        
                        # Voice info display
                        audiobook_voice_info = gr.HTML(
                            "<div class='voice-status'>🎭 Select a voice to see details</div>"
                        )
                    
                    # Project Settings
                    with gr.Group():
                        gr.HTML("<h3>📁 Project Settings</h3>")
                        
                        project_name = gr.Textbox(
                            label="Project Name",
                            placeholder="e.g., my_first_audiobook",
                            info="Used for naming output files (project_001.wav, project_002.wav, etc.)"
                        )
                        
                        # Volume Normalization Controls
                        with gr.Group():
                            gr.HTML("<h4>🎚️ Volume Normalization</h4>")
                            
                            enable_volume_norm = gr.Checkbox(
                                label="Enable Volume Normalization",
                                value=True,
                                info="Automatically adjust all chunks to consistent volume levels"
                            )
                            
                            volume_preset = gr.Dropdown(
                                label="Volume Preset",
                                choices=[
                                    ("📚 Audiobook Standard (-18dB)", "audiobook"),
                                    ("🎙️ Podcast Standard (-16dB)", "podcast"), 
                                    ("📺 Broadcast Standard (-23dB)", "broadcast"),
                                    ("🎛️ Custom Level", "custom")
                                ],
                                value="audiobook",
                                info="Professional volume standards for different content types"
                            )
                            
                            target_volume_level = gr.Slider(
                                label="Target Volume Level (dB)",
                                minimum=-30,
                                maximum=-6,
                                value=-18,
                                step=1,
                                info="Target RMS level in decibels (lower = quieter)"
                            )
                            
                            volume_status = gr.HTML(
                                "<div class='voice-status'>📚 Audiobook Standard: -18 dB RMS (Professional audiobook level)</div>"
                            )
                        
                        # Previous Projects Section
                        with gr.Group():
                            gr.HTML("<h4>📚 Previous Projects</h4>")
                            
                            previous_project_dropdown = gr.Dropdown(
                                choices=get_project_choices(),
                                label="Load Previous Project Audio",
                                value=None,
                                info="Select a previous project to download its complete audio"
                            )
                            
                            with gr.Row():
                                load_previous_btn = gr.Button(
                                    "📂 Load Project Audio",
                                    size="sm",
                                    variant="secondary"
                                )
                                refresh_previous_btn = gr.Button(
                                    "🔄 Refresh",
                                    size="sm"
                                )
                            
                            # Previous project audio and download
                            previous_project_audio = gr.Audio(
                                label="Previous Project Audio",
                                visible=False
                            )
                            
                            previous_project_download = gr.File(
                                label="📁 Download Previous Project",
                                visible=False
                            )
                            
                            previous_project_status = gr.HTML(
                                "<div class='voice-status'>📁 Select a previous project to load its audio</div>"
                            )
            
            # Processing Section
            with gr.Group():
                gr.HTML("<h3>🚀 Audiobook Processing</h3>")
                
                with gr.Row():
                    validate_btn = gr.Button(
                        "🔍 Validate Input", 
                        variant="secondary",
                        size="lg"
                    )
                    
                    process_btn = gr.Button(
                        "🎵 Create Audiobook", 
                        variant="primary",
                        size="lg",
                        interactive=False
                    )
                
                # Status and progress
                audiobook_status = gr.HTML(
                    "<div class='audiobook-status'>📋 Ready to create audiobooks! Load text, select voice, and set project name.</div>"
                )
                
                # Preview/Output area
                audiobook_output = gr.Audio(
                    label="Generated Audiobook (Preview - Full files saved to project folder)",
                    visible=False
                )
            
            # Instructions
            gr.HTML("""
            <div class="instruction-box">
                <h4>📋 How to Create Single-Voice Audiobooks:</h4>
                <ol>
                    <li><strong>Add Text:</strong> Paste text or upload a .txt file</li>
                    <li><strong>Select Voice:</strong> Choose from your saved voice profiles</li>
                    <li><strong>Set Project Name:</strong> This will be used for output file naming</li>
                    <li><strong>Validate:</strong> Check that everything is ready</li>
                    <li><strong>Create:</strong> Generate your audiobook with smart chunking!</li>
                </ol>
                <p><strong>🎯 Smart Chunking:</strong> Text is automatically split at sentence boundaries after ~50 words for optimal processing.</p>
                <p><strong>📁 File Output:</strong> Individual chunks saved as project_001.wav, project_002.wav, etc.</p>
            </div>
            """)

        # NEW: Multi-Voice Audiobook Creation Tab
        with gr.TabItem("🎭 Audiobook Creation - Multi-Sample", id="audiobook_multi"):
            gr.HTML("""
            <div class="audiobook-header">
                <h2>🎭 Multi-Voice Audiobook Creation Studio</h2>
                <p>Create dynamic audiobooks with multiple character voices using voice tags</p>
            </div>
            """)
            
            with gr.Row():
                with gr.Column(scale=2):
                    # Text Input Section with Voice Tags
                    with gr.Group():
                        gr.HTML("<h3>📝 Multi-Voice Text Content</h3>")
                        
                        with gr.Row():
                            with gr.Column(scale=3):
                                multi_audiobook_text = gr.Textbox(
                                    label="Multi-Voice Audiobook Text",
                                    placeholder='Use voice tags like: [narrator] Once upon a time... [character1] "Hello!" said the princess. [narrator] She walked away...',
                                    lines=12,
                                    max_lines=20,
                                    info="Use [voice_name] tags to assign text to different voices"
                                )
                            
                            with gr.Column(scale=1):
                                # File upload
                                multi_text_file = gr.File(
                                    label="📄 Upload Text File",
                                    file_types=[".txt", ".md", ".rtf"],
                                    type="filepath"
                                )
                                
                                load_multi_file_btn = gr.Button(
                                    "📂 Load File", 
                                    size="sm",
                                    variant="secondary"
                                )
                                
                                # File status
                                multi_file_status = gr.HTML(
                                    "<div class='file-status'>📄 No file loaded</div>"
                                )
                    # NEW: Project Management Section
                    with gr.Group():
                        gr.HTML("<h3>📁 Project Management</h3>")
                        multi_project_dropdown = gr.Dropdown(
                            choices=get_project_choices(),
                            label="Select Existing Project",
                            value=None,
                            info="Load or resume an existing project"
                        )
                        with gr.Row():
                            load_multi_project_btn = gr.Button("📂 Load Project", size="sm", variant="secondary")
                            resume_multi_project_btn = gr.Button("▶️ Resume Project", size="sm", variant="primary")
                        multi_project_progress = gr.HTML("<div class='voice-status'>No project loaded</div>")
                
                with gr.Column(scale=1):
                    # Voice Analysis & Project Settings
                    with gr.Group():
                        gr.HTML("<h3>🔍 Text Analysis</h3>")
                        
                        analyze_text_btn = gr.Button(
                            "🔍 Analyze Text & Find Characters",
                            variant="secondary",
                            size="lg"
                        )
                        
                        # Voice breakdown display
                        voice_breakdown_display = gr.HTML(
                            "<div class='voice-status'>📝 Click 'Analyze Text' to find characters in your text</div>"
                        )
                        
                        refresh_multi_voices_btn = gr.Button(
                            "🔄 Refresh Available Voices", 
                            size="sm"
                        )
                    
                    # Voice Assignment Section
                    with gr.Group():
                        gr.HTML("<h3>🎭 Voice Assignments</h3>")
                        
                        # Character assignment dropdowns (max 6 common characters)
                        with gr.Column():
                            char1_dropdown = gr.Dropdown(
                                choices=[("No character found", None)],
                                label="Character 1",
                                visible=False,
                                interactive=True
                            )
                            char2_dropdown = gr.Dropdown(
                                choices=[("No character found", None)],
                                label="Character 2", 
                                visible=False,
                                interactive=True
                            )
                            char3_dropdown = gr.Dropdown(
                                choices=[("No character found", None)],
                                label="Character 3",
                                visible=False,
                                interactive=True
                            )
                            char4_dropdown = gr.Dropdown(
                                choices=[("No character found", None)],
                                label="Character 4",
                                visible=False,
                                interactive=True
                            )
                            char5_dropdown = gr.Dropdown(
                                choices=[("No character found", None)],
                                label="Character 5",
                                visible=False,
                                interactive=True
                            )
                            char6_dropdown = gr.Dropdown(
                                choices=[("No character found", None)],
                                label="Character 6",
                                visible=False,
                                interactive=True
                            )
                    
                    # Project Settings
                    with gr.Group():
                        gr.HTML("<h3>📁 Project Settings</h3>")
                        
                        multi_project_name = gr.Textbox(
                            label="Project Name",
                            placeholder="e.g., my_multi_voice_story",
                            info="Used for naming output files (project_001_character.wav, etc.)"
                        )
                        
                        # Volume Normalization Controls
                        with gr.Group():
                            gr.HTML("<h4>🎚️ Volume Normalization</h4>")
                            
                            multi_enable_volume_norm = gr.Checkbox(
                                label="Enable Volume Normalization",
                                value=True,
                                info="Automatically adjust all chunks to consistent volume levels across characters"
                            )
                            
                            multi_volume_preset = gr.Dropdown(
                                label="Volume Preset",
                                choices=[
                                    ("📚 Audiobook Standard (-18dB)", "audiobook"),
                                    ("🎙️ Podcast Standard (-16dB)", "podcast"), 
                                    ("📺 Broadcast Standard (-23dB)", "broadcast"),
                                    ("🎛️ Custom Level", "custom")
                                ],
                                value="audiobook",
                                info="Professional volume standards for different content types"
                            )
                            
                            multi_target_volume_level = gr.Slider(
                                label="Target Volume Level (dB)",
                                minimum=-30,
                                maximum=-6,
                                value=-18,
                                step=1,
                                info="Target RMS level in decibels (lower = quieter)"
                            )
                            
                            multi_volume_status = gr.HTML(
                                "<div class='voice-status'>📚 Audiobook Standard: -18 dB RMS (Professional audiobook level)</div>"
                            )
                        
                        # Previous Projects Section
                        with gr.Group():
                            gr.HTML("<h4>📚 Previous Projects</h4>")
                            
                            multi_previous_project_dropdown = gr.Dropdown(
                                choices=get_project_choices(),
                                label="Load Previous Project Audio",
                                value=None,
                                info="Select a previous project to download its complete audio"
                            )
                            
                            with gr.Row():
                                load_multi_previous_btn = gr.Button(
                                    "📂 Load Project Audio",
                                    size="sm",
                                    variant="secondary"
                                )
                                refresh_multi_previous_btn = gr.Button(
                                    "🔄 Refresh",
                                    size="sm"
                                )
                            
                            # Previous project audio and download
                            multi_previous_project_audio = gr.Audio(
                                label="Previous Project Audio",
                                visible=False
                            )
                            
                            multi_previous_project_download = gr.File(
                                label="📁 Download Previous Project",
                                visible=False
                            )
                            
                            multi_previous_project_status = gr.HTML(
                                "<div class='voice-status'>📁 Select a previous project to load its audio</div>"
                            )
            
            # Processing Section
            with gr.Group():
                gr.HTML("<h3>🚀 Multi-Voice Processing</h3>")
                
                with gr.Row():
                    validate_multi_btn = gr.Button(
                        "🔍 Validate Voice Assignments", 
                        variant="secondary",
                        size="lg",
                        interactive=False
                    )
                    
                    process_multi_btn = gr.Button(
                        "🎵 Create Multi-Voice Audiobook", 
                        variant="primary",
                        size="lg",
                        interactive=False
                    )
                
                # Status and progress
                multi_audiobook_status = gr.HTML(
                    "<div class='audiobook-status'>📋 Step 1: Analyze text to find characters<br/>📋 Step 2: Assign voices to each character<br/>📋 Step 3: Validate and create audiobook</div>"
                )
                
                # Preview/Output area
                multi_audiobook_output = gr.Audio(
                    label="Generated Multi-Voice Audiobook (Preview - Full files saved to project folder)",
                    visible=False
                )
            
            # Hidden state to store voice counts and assignments
            voice_counts_state = gr.State({})
            voice_assignments_state = gr.State({})
            character_names_state = gr.State([])
            
            # Instructions for Multi-Voice
            gr.HTML("""
            <div class="instruction-box">
                <h4>📋 How to Create Multi-Voice Audiobooks:</h4>
                <ol>
                    <li><strong>Add Voice Tags:</strong> Use [character_name] before text for that character</li>
                    <li><strong>Analyze Text:</strong> Click 'Analyze Text' to find all characters</li>
                    <li><strong>Assign Voices:</strong> Choose voices from your library for each character</li>
                    <li><strong>Set Project Name:</strong> Used for output file naming</li>
                    <li><strong>Validate & Create:</strong> Generate your multi-voice audiobook!</li>
                </ol>
                <h4>🎯 Voice Tag Format:</h4>
                <p><code>[narrator] The story begins here...</code></p>
                <p><code>[princess] "Hello there!" she said cheerfully.</code></p>
                <p><code>[narrator] The mysterious figure walked away.</code></p>
                <p><strong>📁 File Output:</strong> Files named with character: project_001_narrator.wav, project_002_princess.wav, etc.</p>
                <p><strong>🎭 New Workflow:</strong> Characters in [brackets] can be mapped to any voice in your library!</p>
                <p><strong>💡 Smart Processing:</strong> Tries GPU first for speed, automatically falls back to CPU if CUDA errors occur (your 3090 should handle most cases!).</p>
            </div>
            """)

        # NEW: Regenerate Sample Tab with Sub-tabs
        with gr.TabItem("🎬 Production Studio", id="production_studio"):
            with gr.Tabs():
                # NEW: Clean Samples Sub-tab (first tab)
                with gr.TabItem("🧹 Clean Samples", id="clean_samples"):
                    gr.HTML("""
                    <div class="audiobook-header">
                        <h3>🧹 Audio Cleanup & Quality Control</h3>
                        <p>Automatically detect and remove dead space, silence, and audio artifacts from your projects</p>
                    </div>
                    """)
                    
                    with gr.Row():
                        with gr.Column(scale=1):
                            # Project Selection for Clean Samples
                            with gr.Group():
                                gr.HTML("<h4>📁 Project Selection</h4>")
                                
                                clean_project_dropdown = gr.Dropdown(
                                    choices=get_project_choices(),
                                    label="Select Project",
                                    value=None,
                                    info="Choose project to analyze and clean"
                                )
                                
                                with gr.Row():
                                    load_clean_project_btn = gr.Button(
                                        "📂 Load Project",
                                        variant="secondary",
                                        size="lg"
                                    )
                                    refresh_clean_projects_btn = gr.Button(
                                        "🔄 Refresh",
                                        size="sm"
                                    )
                                
                                clean_project_status = gr.HTML(
                                    "<div class='audiobook-status'>📁 Select a project to start cleaning</div>"
                                )
                            
                            # Audio Quality Analysis
                            with gr.Group():
                                gr.HTML("<h4>📊 Audio Quality Analysis</h4>")
                                
                                analyze_audio_btn = gr.Button(
                                    "🔍 Analyze Audio Quality",
                                    variant="secondary",
                                    size="lg",
                                    interactive=False
                                )
                                
                                audio_analysis_results = gr.HTML(
                                    "<div class='voice-status'>📊 Load a project to see analysis</div>"
                                )
                        
                        with gr.Column(scale=2):
                            # Auto Remove Dead Space Section
                            with gr.Group():
                                gr.HTML("<h4>🧹 Auto Remove Dead Space</h4>")
                                
                                with gr.Row():
                                    silence_threshold = gr.Slider(
                                        minimum=-80,
                                        maximum=-20,
                                        value=-50,
                                        step=5,
                                        label="Silence Threshold (dB)",
                                        info="Audio below this level is considered silence"
                                    )
                                    min_silence_duration = gr.Slider(
                                        minimum=0.1,
                                        maximum=2.0,
                                        value=0.5,
                                        step=0.1,
                                        label="Min Silence Duration (s)",
                                        info="Minimum silence length to remove"
                                    )
                                
                                with gr.Row():
                                    auto_clean_btn = gr.Button(
                                        "🧹 Auto Remove Dead Space",
                                        variant="primary",
                                        size="lg",
                                        interactive=False
                                    )
                                    preview_clean_btn = gr.Button(
                                        "👁️ Preview Changes",
                                        variant="secondary",
                                        size="lg",
                                        interactive=False
                                    )
                                
                                cleanup_status = gr.HTML(
                                    "<div class='audiobook-status'>🧹 Load a project to start automatic cleanup</div>"
                                )
                                
                                cleanup_results = gr.HTML(
                                    "<div class='voice-status'>📝 Cleanup results will appear here</div>"
                                )
                            
                            # Add hidden state for clean samples
                            clean_project_state = gr.State("")
                    
                    # Instructions for Clean Samples
                    gr.HTML("""
                    <div class="instruction-box">
                        <h4>🧹 Audio Cleanup Workflow:</h4>
                        <ol>
                            <li><strong>Select Project:</strong> Choose a project to analyze and clean</li>
                            <li><strong>Analyze Quality:</strong> Run audio quality analysis to identify issues</li>
                            <li><strong>Preview Changes:</strong> See what will be cleaned before applying</li>
                            <li><strong>Auto Clean:</strong> Automatically remove dead space and silence</li>
                            <li><strong>Review Results:</strong> Check the cleanup summary and any errors</li>
                        </ol>
                        <p><strong>🔧 Features:</strong></p>
                        <ul>
                            <li><strong>🔍 Smart Detection:</strong> Identifies silence, artifacts, and problematic audio</li>
                            <li><strong>💾 Automatic Backup:</strong> Creates backups before any changes</li>
                            <li><strong>⚙️ Configurable:</strong> Adjust thresholds for your specific needs</li>
                            <li><strong>📊 Detailed Reports:</strong> See exactly what was cleaned and why</li>
                        </ul>
                        <p><strong>⚠️ Note:</strong> This feature requires librosa and soundfile libraries for audio processing.</p>
                    </div>
                    """)
                # End of Clean Samples TabItem

                # New Empty Listen & Edit Tab
                with gr.TabItem("🎧 Listen & Edit", id="listen_edit_prod"): 
                    # REPLACING PLACEHOLDER WITH ACTUAL CONTENT
                    gr.HTML("""
                    <div class="audiobook-header">
                        <h3>🎧 Continuous Playback Editor</h3>
                        <p>Listen to your entire audiobook and regenerate chunks in real-time</p>
                    </div>
                    """)
                    
                    with gr.Row():
                        with gr.Column(scale=1):
                            # Project Selection for Listen & Edit
                            with gr.Group():
                                gr.HTML("<h4>📁 Project Selection</h4>")
                                
                                listen_project_dropdown = gr.Dropdown(
                                    choices=get_project_choices(),
                                    label="Select Project",
                                    value=None,
                                    info="Choose project for continuous editing"
                                )
                                
                                with gr.Row():
                                    load_listen_project_btn = gr.Button(
                                        "🎧 Load for Listen & Edit", # Changed button text for clarity
                                        variant="primary",
                                        size="lg"
                                    )
                                    refresh_listen_projects_btn = gr.Button(
                                        "🔄 Refresh",
                                        size="sm"
                                    )
                                
                                listen_project_status = gr.HTML(
                                    "<div class='audiobook-status'>📁 Select a project to start listening</div>"
                                )
                            
                            # Current Chunk Tracker
                            with gr.Group():
                                gr.HTML("<h4>📍 Current Position</h4>")
                                
                                current_chunk_info = gr.HTML(
                                    "<div class='voice-status'>🎵 No audio loaded</div>"
                                )
                                
                                current_chunk_text = gr.Textbox(
                                    label="Current Chunk Text",
                                    lines=3,
                                    max_lines=6,
                                    interactive=True,
                                    info="Edit text and regenerate current chunk"
                                )
                                
                                with gr.Row():
                                    regenerate_current_btn = gr.Button(
                                        "🔄 Regenerate Current Chunk",
                                        variant="secondary",
                                        size="lg",
                                        interactive=False
                                    )
                                    jump_to_start_btn = gr.Button(
                                        "⏮️ Jump to Start",
                                        size="sm"
                                    )
                        
                        with gr.Column(scale=2):
                            # Continuous Audio Player
                            with gr.Group():
                                gr.HTML("<h4>🎧 Continuous Playback</h4>")
                                
                                continuous_audio_player = gr.Audio(
                                    label="Full Project Audio",
                                    interactive=True,
                                    show_download_button=True,
                                    show_share_button=False,
                                    waveform_options=gr.WaveformOptions(
                                        waveform_color="#01C6FF",
                                        waveform_progress_color="#0066B4",
                                        trim_region_color="#FF6B6B",
                                        show_recording_waveform=True,
                                        skip_length=10,
                                        sample_rate=24000
                                    )
                                )
                                
                                listen_edit_status = gr.HTML( # This was likely a typo and should be listen_project_status or a new one
                                    "<div class='audiobook-status'>📁 Load a project to start continuous editing</div>"
                                )
                            
                            # Audio Cutting Tools (for future implementation)
                            with gr.Group():
                                gr.HTML("<h4>✂️ Audio Editing Tools</h4>")
                                
                                with gr.Row():
                                    cut_selection_btn = gr.Button(
                                        "✂️ Cut Selected Audio",
                                        variant="secondary",
                                        size="sm",
                                        interactive=False,
                                    )
                                    undo_cut_btn = gr.Button(
                                        "↩️ Undo Last Cut",
                                        size="sm",
                                        interactive=False
                                    )
                                
                                cutting_status = gr.HTML(
                                    "<div class='voice-status'>📝 Audio cutting tools (coming soon)</div>"
                                )
                    
                    # Instructions for Listen & Edit
                    gr.HTML("""
                    <div class="instruction-box">
                        <h4>🎧 Listen & Edit Workflow:</h4>
                        <ol>
                            <li><strong>Load Project:</strong> Select and load a project for continuous editing</li>
                            <li><strong>Listen:</strong> Play the continuous audio and listen for issues</li>
                            <li><strong>Edit Text:</strong> When you hear a problem, edit the text in the current chunk</li>
                            <li><strong>Regenerate:</strong> Click "🔄 Regenerate Current Chunk" to fix the issue</li>
                            <li><strong>Auto-restart:</strong> Audio will automatically restart from the beginning with your fix applied</li>
                            <li><strong>Repeat:</strong> Continue listening and fixing until satisfied</li>
                        </ol>
                        <p><strong>💡 Features:</strong></p>
                        <ul>
                            <li><strong>🎯 Real-time Tracking:</strong> See which chunk is currently playing</li>
                            <li><strong>🔄 Instant Regeneration:</strong> Fix chunks without manual file management</li>
                            <li><strong>⏮️ Auto-restart:</strong> Playback automatically restarts after changes</li>
                            <li><strong>✂️ Audio Cutting:</strong> Remove unwanted sections (coming soon)</li>
                        </ul>
                    </div>
                    """)
                    # Hidden states for Listen & Edit mode
                    continuous_audio_data = gr.State(None)
                    current_chunk_state = gr.State({})
                    listen_edit_project_name = gr.State("")

                # New Empty Batch Processing Tab
                with gr.TabItem("🔁 Batch Processing", id="batch_processing_prod"):
                    # REPLACING PLACEHOLDER WITH ACTUAL CONTENT
                    gr.HTML("""
                    <div class="audiobook-header">
                        <h3>🔁 Batch Chunk Editor & Processor</h3>
                        <p>Detailed chunk-by-chunk editing, regeneration, and trimming</p>
                    </div>
                    """)
                    
                    with gr.Row():
                        with gr.Column(scale=1):
                            # Project Selection
                            with gr.Group():
                                gr.HTML("<h4>📁 Project Selection</h4>")
                                
                                project_dropdown = gr.Dropdown( # This is for this specific sub-tab
                                    choices=get_project_choices(),
                                    label="Select Project",
                                    value=None,
                                    info="Choose from your existing audiobook projects"
                                )
                                
                                with gr.Row():
                                    load_project_btn = gr.Button( 
                                        "📂 Load Project Chunks",
                                        variant="secondary",
                                        size="lg"
                                    )
                                    refresh_projects_btn = gr.Button(
                                        "🔄 Refresh Projects",
                                        size="sm"
                                    )
                                
                                # Project status
                                project_status = gr.HTML(
                                    "<div class='audiobook-status'>📁 Select a project to view all chunks</div>"
                                )
                            
                            # NEW: Pagination Controls
                            with gr.Group():
                                gr.HTML("<h4>📄 Chunk Navigation</h4>")
                                
                                with gr.Row():
                                    chunks_per_page = gr.Dropdown(
                                        choices=[("25 chunks", 25), ("50 chunks", 50), ("100 chunks", 100)],
                                        label="Chunks per page",
                                        value=50,
                                        info="How many chunks to show at once"
                                    )
                                    
                                    current_page = gr.Number(
                                        label="Current Page",
                                        value=1,
                                        minimum=1,
                                        step=1,
                                        interactive=True,
                                        info="Current page number"
                                    )
                                
                                with gr.Row():
                                    prev_page_btn = gr.Button("⬅️ Previous Page", size="sm", interactive=False)
                                    next_page_btn = gr.Button("➡️ Next Page", size="sm", interactive=False)
                                    go_to_page_btn = gr.Button("🔄 Go to Page", size="sm")
                                
                                # Page info display
                                page_info = gr.HTML("<div class='voice-status'>📄 Load a project to see pagination info</div>")
                        
                        with gr.Column(scale=2):
                            # Project Information Display
                            with gr.Group():
                                gr.HTML("<h4>📋 Project Overview</h4>")
                                
                                # Project info summary
                                project_info_summary = gr.HTML(
                                    "<div class='voice-status'>📝 Load a project to see details</div>"
                                )
                                
                                # Chunks container - this will be populated dynamically
                                chunks_container = gr.HTML( 
                                    "<div class='audiobook-status'>📚 Project chunks will appear here after loading</div>"
                                )
                                
                                # Download Section - Simplified 
                                with gr.Group():
                                    gr.HTML("<h4>💾 Download Project</h4>")
                                    
                                    download_project_btn = gr.Button(
                                        "📥 Download Project as Split MP3 Files",
                                        variant="primary",
                                        size="lg",
                                        interactive=False
                                    )
                                    
                                    # Download status
                                    download_status = gr.HTML(
                                        "<div class='voice-status'>📁 Load a project first to enable download</div>"
                                    )
            
                    # Dynamic chunk interface - created when project is loaded
                    chunk_interfaces = [] 
                    
                    # Create interface for up to MAX_CHUNKS_FOR_INTERFACE chunks
                    for i in range(MAX_CHUNKS_FOR_INTERFACE):
                        with gr.Group(visible=False) as chunk_group:
                            with gr.Row():
                                with gr.Column(scale=1):
                                    chunk_audio = gr.Audio(
                                        label=f"Chunk {i+1} Audio",
                                        interactive=True,  # Enable trimming
                                        show_download_button=True,
                                        show_share_button=False,
                                        waveform_options=gr.WaveformOptions(
                                            waveform_color="#01C6FF",
                                            waveform_progress_color="#0066B4", 
                                            trim_region_color="#FF6B6B",
                                            show_recording_waveform=True,
                                            skip_length=5,
                                            sample_rate=24000
                                        )
                                    )
                                    
                                    save_original_trim_btn = gr.Button(
                                        f"💾 Save Trimmed Chunk {i+1}",
                                        variant="secondary",
                                        size="sm",
                                        visible=True 
                                    )
                                
                                with gr.Column(scale=2):
                                    chunk_text_input = gr.Textbox( 
                                        label=f"Chunk {i+1} Text",
                                        lines=3,
                                        max_lines=6,
                                        info="Edit this text and regenerate to create a new version"
                                    )
                                    
                                    with gr.Row():
                                        chunk_voice_info = gr.HTML(
                                            "<div class='voice-status'>Voice info</div>"
                                        )
                                        
                                        regenerate_chunk_btn = gr.Button(
                                            f"🎵 Regenerate Chunk {i+1}",
                                            variant="primary",
                                            size="sm"
                                        )
                                    
                                    regenerated_chunk_audio = gr.Audio(
                                        label=f"Regenerated Chunk {i+1}",
                                        visible=False,
                                        interactive=True,  # Enable trimming
                                        show_download_button=True,
                                        show_share_button=False,
                                        waveform_options=gr.WaveformOptions(
                                            waveform_color="#FF6B6B",
                                            waveform_progress_color="#FF4444",
                                            trim_region_color="#FFB6C1",
                                            show_recording_waveform=True,
                                            skip_length=5,
                                            sample_rate=24000
                                        )
                                    )
                                    
                                    with gr.Row(visible=False) as accept_decline_row:
                                        accept_chunk_btn = gr.Button(
                                            "✅ Accept Regeneration",
                                            variant="primary",
                                            size="sm"
                                        )
                                        decline_chunk_btn = gr.Button(
                                            "❌ Decline Regeneration", 
                                            variant="stop",
                                            size="sm"
                                        )
                                        save_regen_trim_btn = gr.Button(
                                            "💾 Save Trimmed Regeneration",
                                            variant="secondary",
                                            size="sm"
                                        )
                                    
                                    chunk_status = gr.HTML(
                                        "<div class='voice-status'>Ready to regenerate</div>"
                                    )
                        
                        chunk_interfaces.append({
                            'group': chunk_group,
                            'audio': chunk_audio,
                            'text': chunk_text_input, 
                            'voice_info': chunk_voice_info,
                            'button': regenerate_chunk_btn,
                            'regenerated_audio': regenerated_chunk_audio,
                            'accept_decline_row': accept_decline_row,
                            'accept_btn': accept_chunk_btn,
                            'decline_btn': decline_chunk_btn,
                            'save_original_trim_btn': save_original_trim_btn,
                            'save_regen_trim_btn': save_regen_trim_btn,
                            'status': chunk_status,
                            'chunk_num': i + 1 
                        })
                    
                    gr.HTML("""
                    <div class="instruction-box">
                        <h4>📋 How to Use Batch Chunk Processing:</h4>
                        <ol>
                            <li><strong>Select Project:</strong> Choose from your existing audiobook projects</li>
                            <li><strong>Load Project:</strong> View all audio chunks with their original text</li>
                            <li><strong>Review & Trim:</strong> Listen to each chunk and trim if needed using the waveform controls</li>
                            <li><strong>Save Trimmed Audio:</strong> Click "💾 Save Trimmed Chunk" to save your trimmed version</li>
                            <li><strong>Edit & Regenerate:</strong> Modify text if needed and regenerate individual chunks</li>
                            <li><strong>Trim Regenerated:</strong> Use trim controls on regenerated audio and save with "💾 Save Trimmed Regeneration"</li>
                            <li><strong>Accept/Decline:</strong> Accept regenerated chunks or decline to keep originals</li>
                        </ol>
                        <p><strong>⚠️ Note:</strong> Gradio\'s visual trimming is just for selection - you must click \"Save Trimmed\" to actually apply the changes to the downloadable file!</p>
                        <p><strong>💡 Note:</strong> Only projects created with metadata support can be fully regenerated. Legacy projects will show limited information.</p>
                    </div>
                    """)
            
                    current_project_chunks = gr.State([]) 
                    current_project_name = gr.State("")   
                    current_page_state = gr.State(1)    
                    total_pages_state = gr.State(1)     

            # End of Production Studio Tabs

    # Load initial voice list and model
    demo.load(fn=load_model, inputs=[], outputs=model_state)
    demo.load(
        fn=lambda: refresh_voice_list(SAVED_VOICE_LIBRARY_PATH),
        inputs=[],
        outputs=voice_dropdown
    )
    demo.load(
        fn=lambda: refresh_voice_choices(SAVED_VOICE_LIBRARY_PATH),
        inputs=[],
        outputs=tts_voice_selector
    )
    demo.load(
        fn=lambda: refresh_audiobook_voice_choices(SAVED_VOICE_LIBRARY_PATH),
        inputs=[],
        outputs=audiobook_voice_selector
    )
    demo.load(
        fn=lambda: get_project_choices(),
        inputs=[],
        outputs=previous_project_dropdown
    )
    demo.load(
        fn=lambda: get_project_choices(),
        inputs=[],
        outputs=multi_previous_project_dropdown
    )
    
    # Load project dropdowns for regenerate tabs
    demo.load(
        fn=lambda: get_project_choices(),
        inputs=[],
        outputs=listen_project_dropdown
    )
    demo.load(
        fn=lambda: get_project_choices(),
        inputs=[],
        outputs=project_dropdown
    )

    # TTS Voice Selection
    tts_voice_selector.change(
        fn=lambda path, voice: load_voice_for_tts(path, voice),
        inputs=[voice_library_path_state, tts_voice_selector],
        outputs=[ref_wav, exaggeration, cfg_weight, temp, ref_wav, tts_voice_status]
    )

    # Refresh voices in TTS tab
    refresh_voices_btn.click(
        fn=lambda path: refresh_voice_choices(path),
        inputs=voice_library_path_state,
        outputs=tts_voice_selector
    )

    # TTS Generation
    run_btn.click(
        fn=generate,
        inputs=[
            model_state,
            text,
            ref_wav,
            exaggeration,
            temp,
            seed_num,
            cfg_weight,
        ],
        outputs=audio_output,
    )

    # Voice Library Functions
    update_path_btn.click(
        fn=update_voice_library_path,
        inputs=voice_library_path,
        outputs=[voice_library_path_state, config_status, voice_dropdown, tts_voice_selector, audiobook_voice_selector]
    )

    refresh_btn.click(
        fn=lambda path: (refresh_voice_list(path), refresh_voice_choices(path), refresh_audiobook_voice_choices(path)),
        inputs=voice_library_path_state,
        outputs=[voice_dropdown, tts_voice_selector, audiobook_voice_selector]
    )

    load_voice_btn.click(
        fn=lambda path, name: load_voice_profile(path, name),
        inputs=[voice_library_path_state, voice_dropdown],
        outputs=[voice_audio, voice_exaggeration, voice_cfg, voice_temp, voice_status]
    )

    test_voice_btn.click(
        fn=lambda model, text, audio, exag, temp, cfg: generate(model, text, audio, exag, temp, 0, cfg),
        inputs=[model_state, test_text, voice_audio, voice_exaggeration, voice_temp, voice_cfg],
        outputs=test_audio_output
    )

    save_voice_btn.click(
        fn=lambda path, name, display, desc, audio, exag, cfg, temp, enable_norm, target_level: save_voice_profile(
            path, name, display, desc, audio, exag, cfg, temp, enable_norm, target_level
        ),
        inputs=[
            voice_library_path_state, voice_name, voice_display_name, voice_description,
            voice_audio, voice_exaggeration, voice_cfg, voice_temp, 
            enable_voice_normalization, target_volume_level
        ],
        outputs=voice_status
    ).then(
        fn=lambda path: (refresh_voice_list(path), refresh_voice_choices(path), refresh_audiobook_voice_choices(path)),
        inputs=voice_library_path_state,
        outputs=[voice_dropdown, tts_voice_selector, audiobook_voice_selector]
    )

    delete_voice_btn.click(
        fn=lambda path, name: delete_voice_profile(path, name),
        inputs=[voice_library_path_state, voice_dropdown],
        outputs=[voice_status, voice_dropdown]
    ).then(
        fn=lambda path: (refresh_voice_choices(path), refresh_audiobook_voice_choices(path)),
        inputs=voice_library_path_state,
        outputs=[tts_voice_selector, audiobook_voice_selector]
    )

    # NEW: Multi-Voice Audiobook Creation Functions
    
    # Multi-voice file loading
    load_multi_file_btn.click(
        fn=load_text_file,
        inputs=multi_text_file,
        outputs=[multi_audiobook_text, multi_file_status]
    )
    
    # Single-voice audiobook functions (restored)
    # File loading
    load_file_btn.click(
        fn=load_text_file,
        inputs=text_file,
        outputs=[audiobook_text, file_status]
    )
    
    # Voice selection for audiobook
    refresh_audiobook_voices_btn.click(
        fn=lambda path: refresh_audiobook_voice_choices(path),
        inputs=voice_library_path_state,
        outputs=audiobook_voice_selector
    )
    
    # Enhanced Validation with project name
    validate_btn.click(
        fn=validate_audiobook_input,
        inputs=[audiobook_text, audiobook_voice_selector, project_name],
        outputs=[process_btn, audiobook_status, audiobook_output]
    )
    
    # Enhanced Audiobook Creation with chunking and saving
    process_btn.click(
        fn=create_audiobook_with_volume_settings,
        inputs=[model_state, audiobook_text, voice_library_path_state, audiobook_voice_selector, project_name, enable_volume_norm, target_volume_level],
        outputs=[audiobook_output, audiobook_status]
    ).then(
        fn=force_refresh_all_project_dropdowns,
        inputs=[],
        outputs=[previous_project_dropdown, multi_previous_project_dropdown, project_dropdown]
    )
    
    # Text analysis to find characters and populate dropdowns
    analyze_text_btn.click(
        fn=handle_multi_voice_analysis,
        inputs=[multi_audiobook_text, voice_library_path_state],
        outputs=[voice_breakdown_display, voice_counts_state, character_names_state, 
                char1_dropdown, char2_dropdown, char3_dropdown, char4_dropdown, char5_dropdown, char6_dropdown,
                validate_multi_btn, multi_audiobook_status]
    )
    
    # Multi-voice validation using dropdown values
    validate_multi_btn.click(
        fn=validate_dropdown_voice_assignments,
        inputs=[multi_audiobook_text, voice_library_path_state, multi_project_name, voice_counts_state, character_names_state,
               char1_dropdown, char2_dropdown, char3_dropdown, char4_dropdown, char5_dropdown, char6_dropdown],
        outputs=[process_multi_btn, multi_audiobook_status, voice_assignments_state, multi_audiobook_output]
    )
    
    # Multi-voice audiobook creation (using voice assignments)
    process_multi_btn.click(
        fn=create_multi_voice_audiobook_with_volume_settings,
        inputs=[model_state, multi_audiobook_text, voice_library_path_state, multi_project_name, voice_assignments_state, multi_enable_volume_norm, multi_target_volume_level],
        outputs=[multi_audiobook_output, multi_audiobook_status]
    ).then(
        fn=force_refresh_all_project_dropdowns,
        inputs=[],
        outputs=[previous_project_dropdown, multi_previous_project_dropdown, project_dropdown]
    )
    
    # Refresh voices for multi-voice (updates dropdown choices)
    refresh_multi_voices_btn.click(
        fn=lambda path: f"<div class='voice-status'>🔄 Available voices refreshed from: {path}<br/>📚 Re-analyze your text to update character assignments</div>",
        inputs=voice_library_path_state,
        outputs=voice_breakdown_display
    )

    # NEW: Regenerate Sample Tab Functions
    
    # Load projects on tab initialization
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=project_dropdown
    )
    
    # Refresh projects dropdown
    refresh_projects_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=project_dropdown
    )
    
    # Create output list for all chunk interface components
    chunk_outputs = []
    for i in range(MAX_CHUNKS_FOR_INTERFACE):
        chunk_outputs.extend([
            chunk_interfaces[i]['group'],
            chunk_interfaces[i]['audio'],
            chunk_interfaces[i]['text'],
            chunk_interfaces[i]['voice_info'],
            chunk_interfaces[i]['button'],
            chunk_interfaces[i]['regenerated_audio'],
            chunk_interfaces[i]['status']
        ])
    
    # Load project chunks
    load_project_btn.click(
        fn=load_project_chunks_for_interface,
        inputs=[project_dropdown, current_page, chunks_per_page],
        outputs=[project_info_summary, current_project_chunks, current_project_name, project_status, download_project_btn, download_status, current_page_state, total_pages_state, prev_page_btn, next_page_btn, page_info] + chunk_outputs
    )
    
    # Pagination controls
    def go_to_previous_page(current_project_name_val, current_page_val, chunks_per_page_val):
        if not current_project_name_val:
            return load_project_chunks_for_interface("", 1, chunks_per_page_val)
        new_page = max(1, current_page_val - 1)
        return load_project_chunks_for_interface(current_project_name_val, new_page, chunks_per_page_val)
    
    def go_to_next_page(current_project_name_val, current_page_val, chunks_per_page_val, total_pages_val):
        if not current_project_name_val:
            return load_project_chunks_for_interface("", 1, chunks_per_page_val)
        new_page = min(total_pages_val, current_page_val + 1)
        return load_project_chunks_for_interface(current_project_name_val, new_page, chunks_per_page_val)
    
    def go_to_specific_page(current_project_name_val, page_num, chunks_per_page_val):
        if not current_project_name_val:
            return load_project_chunks_for_interface("", 1, chunks_per_page_val)
        return load_project_chunks_for_interface(current_project_name_val, page_num, chunks_per_page_val)
    
    def change_chunks_per_page(current_project_name_val, chunks_per_page_val):
        if not current_project_name_val:
            return load_project_chunks_for_interface("", 1, chunks_per_page_val)
        return load_project_chunks_for_interface(current_project_name_val, 1, chunks_per_page_val)  # Reset to page 1
    
    prev_page_btn.click(
        fn=go_to_previous_page,
        inputs=[current_project_name, current_page_state, chunks_per_page],
        outputs=[project_info_summary, current_project_chunks, current_project_name, project_status, download_project_btn, download_status, current_page_state, total_pages_state, prev_page_btn, next_page_btn, page_info] + chunk_outputs
    )
    
    next_page_btn.click(
        fn=go_to_next_page,
        inputs=[current_project_name, current_page_state, chunks_per_page, total_pages_state],
        outputs=[project_info_summary, current_project_chunks, current_project_name, project_status, download_project_btn, download_status, current_page_state, total_pages_state, prev_page_btn, next_page_btn, page_info] + chunk_outputs
    )
    
    go_to_page_btn.click(
        fn=go_to_specific_page,
        inputs=[current_project_name, current_page, chunks_per_page],
        outputs=[project_info_summary, current_project_chunks, current_project_name, project_status, download_project_btn, download_status, current_page_state, total_pages_state, prev_page_btn, next_page_btn, page_info] + chunk_outputs
    )
    
    chunks_per_page.change(
        fn=change_chunks_per_page,
        inputs=[current_project_name, chunks_per_page],
        outputs=[project_info_summary, current_project_chunks, current_project_name, project_status, download_project_btn, download_status, current_page_state, total_pages_state, prev_page_btn, next_page_btn, page_info] + chunk_outputs
    )

    # Add regeneration handlers for each chunk
    for i, chunk_interface in enumerate(chunk_interfaces):
        chunk_num = i + 1
        
        # Create state to store regenerated file path for this chunk
        chunk_regen_file_state = gr.State("")
        
        # Use closure to capture chunk_num properly
        def make_regenerate_handler(chunk_num_ui_slot): # This is the 1-based UI slot index
            def regenerate_handler(model, project_name_state, voice_lib_path, custom_text, current_project_chunks_state, current_page_val, chunks_per_page_val):
                if not project_name_state:
                    return None, "❌ No project selected.", ""
                if not current_project_chunks_state:
                    return None, "❌ Project chunks not loaded.", ""

                actual_chunk_list_idx = (current_page_val - 1) * chunks_per_page_val + chunk_num_ui_slot - 1

                if actual_chunk_list_idx < 0 or actual_chunk_list_idx >= len(current_project_chunks_state):
                    return None, f"❌ Calculated chunk index {actual_chunk_list_idx} for UI slot {chunk_num_ui_slot} (Page {current_page_val}) is out of bounds.", ""
                
                target_chunk_info = current_project_chunks_state[actual_chunk_list_idx]
                actual_chunk_number = target_chunk_info['chunk_num'] # The true 1-based chunk number

                print(f"[DEBUG] Regenerate UI Slot {chunk_num_ui_slot} -> Actual Chunk {actual_chunk_number}")

                result = regenerate_single_chunk(model, project_name_state, actual_chunk_number, voice_lib_path, custom_text)
                if result and len(result) == 2:
                    temp_file_path, status_msg = result
                    if temp_file_path and isinstance(temp_file_path, str):
                        return temp_file_path, status_msg, temp_file_path
                    else:
                        return None, status_msg, ""
                else:
                    error_detail = result[1] if result and len(result) > 1 else "Unknown error"
                    return None, f"❌ Error regenerating chunk {actual_chunk_number}: {error_detail}", ""
            return regenerate_handler
        
        # Use closure for accept/decline handlers
        def make_accept_handler(chunk_num_ui_slot): # This is the 1-based UI slot index
            def accept_handler(project_name_state, regen_file_path, current_project_chunks_state, current_page_val, chunks_per_page_val):
                if not project_name_state:
                    return f"❌ No project selected to accept chunk for.", None
                if not regen_file_path:
                    return f"❌ No regenerated file to accept for UI slot {chunk_num_ui_slot}", None
                if not current_project_chunks_state:
                     return f"❌ Project chunks not loaded, cannot accept for UI slot {chunk_num_ui_slot}", None

                actual_chunk_list_idx = (current_page_val - 1) * chunks_per_page_val + chunk_num_ui_slot - 1
                if actual_chunk_list_idx < 0 or actual_chunk_list_idx >= len(current_project_chunks_state):
                    return f"❌ Calculated chunk index {actual_chunk_list_idx} for UI slot {chunk_num_ui_slot} (Page {current_page_val}) is out of bounds.", None
                
                target_chunk_info = current_project_chunks_state[actual_chunk_list_idx]
                actual_chunk_number = target_chunk_info['chunk_num']
                
                print(f"[DEBUG] Accept UI Slot {chunk_num_ui_slot} -> Actual Chunk {actual_chunk_number}")
                return accept_regenerated_chunk(project_name_state, actual_chunk_number, regen_file_path, current_project_chunks_state)
            return accept_handler
        
        def make_decline_handler(chunk_num_ui_slot): # This is the 1-based UI slot index
            def decline_handler(regen_file_path, current_project_chunks_state, current_page_val, chunks_per_page_val):
                actual_chunk_number = -1 # Default if not found
                if current_project_chunks_state:
                    actual_chunk_list_idx = (current_page_val - 1) * chunks_per_page_val + chunk_num_ui_slot - 1
                    if 0 <= actual_chunk_list_idx < len(current_project_chunks_state):
                        target_chunk_info = current_project_chunks_state[actual_chunk_list_idx]
                        actual_chunk_number = target_chunk_info['chunk_num']
                print(f"[DEBUG] Decline UI Slot {chunk_num_ui_slot} -> Actual Chunk {actual_chunk_number if actual_chunk_number !=-1 else 'Unknown'}")
                return decline_regenerated_chunk(actual_chunk_number, regen_file_path)
            return decline_handler
        
        chunk_interface['button'].click(
            fn=make_regenerate_handler(chunk_num),
            inputs=[model_state, current_project_name, voice_library_path_state, chunk_interface['text'], current_project_chunks, current_page_state, chunks_per_page],
            outputs=[chunk_interface['regenerated_audio'], chunk_interface['status'], chunk_regen_file_state]
        ).then(
            fn=lambda audio: (gr.Audio(visible=bool(audio)), gr.Row(visible=bool(audio))),
            inputs=chunk_interface['regenerated_audio'],
            outputs=[chunk_interface['regenerated_audio'], chunk_interface['accept_decline_row']]
        )
        
        # Accept button handler
        chunk_interface['accept_btn'].click(
            fn=make_accept_handler(chunk_num),
            inputs=[current_project_name, chunk_regen_file_state, current_project_chunks, current_page_state, chunks_per_page],
            outputs=[chunk_interface['status'], chunk_interface['audio']]
        ).then(
            fn=lambda: (gr.Audio(visible=False), gr.Row(visible=False), ""),
            inputs=[],
            outputs=[chunk_interface['regenerated_audio'], chunk_interface['accept_decline_row'], chunk_regen_file_state]
        )
        
        # Decline button handler  
        chunk_interface['decline_btn'].click(
            fn=make_decline_handler(chunk_num),
            inputs=[chunk_regen_file_state, current_project_chunks, current_page_state, chunks_per_page],
            outputs=[chunk_interface['regenerated_audio'], chunk_interface['accept_decline_row'], chunk_interface['status']]
        ).then(
            fn=lambda: "",
            inputs=[],
            outputs=chunk_regen_file_state
        )
        
        # Save original trimmed audio handler
        def make_save_original_trim_handler(chunk_num_captured): # Renamed to avoid conflict, will be repurposed or removed
            # This function's logic will be moved into make_audio_change_handler
            def save_original_trim(trimmed_audio_data_from_event, current_project_chunks_state_value):
                print(f"[DEBUG] save_original_trim (now part of audio_change) called for chunk {chunk_num_captured}")
                print(f"[DEBUG] trimmed_audio_data_from_event type: {type(trimmed_audio_data_from_event)}")

                if not trimmed_audio_data_from_event:
                    return f"<div class='voice-status'>Chunk {chunk_num_captured} - No audio data to save.</div>", None 

                if not current_project_chunks_state_value or chunk_num_captured > len(current_project_chunks_state_value):
                    return f"❌ No project loaded or invalid chunk number {chunk_num_captured} for saving.", None

                chunk_info = current_project_chunks_state_value[chunk_num_captured - 1]
                original_file_path = chunk_info['audio_file']
                
                status_msg, new_file_path_or_none = save_visual_trim_to_file(
                    trimmed_audio_data_from_event, 
                    original_file_path, 
                    chunk_num_captured
                )
                
                print(f"[DEBUG] save_original_trim for chunk {chunk_num_captured} - save status: {status_msg}, new_file_path: {new_file_path_or_none}")
                return status_msg, new_file_path_or_none # This will update status and the audio player
            return save_original_trim
        
        # Audio change handler to provide feedback about trimming AND SAVE
        def make_audio_change_handler(chunk_num_captured): # chunk_num_captured is the 1-based UI slot index
            def audio_change_handler(trimmed_audio_data_from_event, current_project_chunks_state_value, current_page_val, chunks_per_page_val):
                # This is triggered when the Gradio audio component's value changes,
                # which includes after its internal "Trim" button is pressed.
                
                print(f"[DEBUG] audio_change_handler (for saving) triggered for UI slot {chunk_num_captured}, page {current_page_val}")
                print(f"[DEBUG] trimmed_audio_data_from_event type: {type(trimmed_audio_data_from_event)}")

                if not trimmed_audio_data_from_event:
                    # This can happen if the audio is cleared or fails to load
                    return f"<div class='voice-status'>UI Slot {chunk_num_captured} - Audio cleared or no data.</div>", None 

                if not current_project_chunks_state_value:
                    return f"❌ Cannot save: No project chunks loaded.", None

                # Calculate actual chunk index in the full project list (0-based)
                actual_chunk_list_idx = (current_page_val - 1) * chunks_per_page_val + chunk_num_captured - 1
                
                if actual_chunk_list_idx < 0 or actual_chunk_list_idx >= len(current_project_chunks_state_value):
                    return f"❌ Cannot save: Calculated chunk index {actual_chunk_list_idx} is out of bounds for project with {len(current_project_chunks_state_value)} chunks. UI Slot: {chunk_num_captured}, Page: {current_page_val}", None

                chunk_info = current_project_chunks_state_value[actual_chunk_list_idx]
                original_file_path = chunk_info['audio_file']
                actual_chunk_number_for_saving = chunk_info['chunk_num'] # This is the true, 1-based chunk number
                
                print(f"[DEBUG] UI Slot {chunk_num_captured} corresponds to Actual Chunk Number: {actual_chunk_number_for_saving}, File: {original_file_path}")

                # Call the save function directly
                status_msg, new_file_path_or_none = save_visual_trim_to_file(
                    trimmed_audio_data_from_event, 
                    original_file_path, 
                    actual_chunk_number_for_saving # Use the actual chunk number for saving and logging
                )
                
                print(f"[DEBUG] audio_change_handler save for actual chunk {actual_chunk_number_for_saving} - status: {status_msg}, new_file_path: {new_file_path_or_none}")
                
                # The gr.Audio component should be updated with new_file_path_or_none.
                # If saving failed, new_file_path_or_none will be None, and the audio player will reflect this.
                return status_msg, new_file_path_or_none 
            return audio_change_handler
        
        chunk_interface['audio'].change(
            fn=make_audio_change_handler(chunk_num), # Use the new handler that saves
            inputs=[chunk_interface['audio'], current_project_chunks, current_page_state, chunks_per_page], # Pass states
            outputs=[chunk_interface['status'], chunk_interface['audio']] # Update status AND the audio component
        )
        
        # Save regenerated trimmed audio handler
        def make_save_regen_trim_handler(chunk_num_ui_slot): # This is the 1-based UI slot index
            def save_regen_trim(trimmed_regenerated_audio_data, project_name_state, current_project_chunks_state, current_page_val, chunks_per_page_val):
                if not project_name_state:
                    return "❌ No project selected.", None
                if not trimmed_regenerated_audio_data:
                    return "❌ No trimmed regenerated audio data to save.", None
                if not current_project_chunks_state:
                    return "❌ Project chunks not loaded.", None

                actual_chunk_list_idx = (current_page_val - 1) * chunks_per_page_val + chunk_num_ui_slot - 1
                if actual_chunk_list_idx < 0 or actual_chunk_list_idx >= len(current_project_chunks_state):
                    return f"❌ Calculated chunk index {actual_chunk_list_idx} for UI slot {chunk_num_ui_slot} (Page {current_page_val}) is out of bounds.", None
                
                target_chunk_info = current_project_chunks_state[actual_chunk_list_idx]
                original_file_path_to_overwrite = target_chunk_info['audio_file']
                actual_chunk_number = target_chunk_info['chunk_num']

                print(f"[DEBUG] SaveRegenTrim UI Slot {chunk_num_ui_slot} -> Actual Chunk {actual_chunk_number}, Overwriting: {original_file_path_to_overwrite}")

                # Save the trimmed regenerated audio, OVERWRITING the original chunk's file.
                # This is effectively "accepting" the trimmed regeneration.
                status_msg, new_file_path = save_visual_trim_to_file(
                    trimmed_regenerated_audio_data, 
                    original_file_path_to_overwrite, 
                    actual_chunk_number
                )
                
                # Also, attempt to clean up any temp_regenerated files for this chunk, as this action replaces it.
                project_dir = os.path.dirname(original_file_path_to_overwrite)
                try:
                    for file_in_dir in os.listdir(project_dir):
                        if file_in_dir.startswith(f"temp_regenerated_chunk_{actual_chunk_number}_") and file_in_dir.endswith('.wav'):
                            temp_path_to_remove = os.path.join(project_dir, file_in_dir)
                            os.remove(temp_path_to_remove)
                            print(f"🗑️ Cleaned up old temp regen file: {file_in_dir} after saving trimmed regen.")
                except Exception as e_cleanup:
                    print(f"⚠️ Warning during temp file cleanup in SaveRegenTrim: {str(e_cleanup)}")

                return status_msg, new_file_path # new_file_path will be the original_file_path if successful
            return save_regen_trim
        
        chunk_interface['save_regen_trim_btn'].click(
            fn=make_save_regen_trim_handler(chunk_num),
            inputs=[chunk_interface['regenerated_audio'], current_project_name, current_project_chunks, current_page_state, chunks_per_page],
            outputs=[chunk_interface['status'], chunk_interface['audio']] # Updates original audio player
        ).then(
            fn=lambda: (gr.Audio(visible=False), gr.Row(visible=False), ""),
            inputs=[],
            outputs=[chunk_interface['regenerated_audio'], chunk_interface['accept_decline_row'], chunk_regen_file_state]
        )
    
        # Manual trimming handlers for this chunk
        def make_get_duration_handler(chunk_num):
            def get_duration_handler():
                if not current_project_chunks.value or chunk_num > len(current_project_chunks.value):
                    return 0, f"❌ No project loaded or invalid chunk number {chunk_num}"
                
                chunk_info = current_project_chunks.value[chunk_num - 1]
                audio_file = chunk_info['audio_file']
                
                try:
                    with wave.open(audio_file, 'rb') as wav_file:
                        frames = wav_file.getnframes()
                        sample_rate = wav_file.getframerate()
                        duration = frames / sample_rate
                        
                        return duration, f"<div class='voice-status'>🎵 Chunk {chunk_num} duration: {duration:.2f} seconds</div>"
                except Exception as e:
                    return 0, f"<div class='voice-status'>❌ Error reading audio: {str(e)}</div>"
            return get_duration_handler
        
        def make_apply_manual_trim_handler(chunk_num):
            def apply_manual_trim(start_time, end_time):
                if not current_project_chunks.value or chunk_num > len(current_project_chunks.value):
                    return f"❌ No project loaded or invalid chunk number {chunk_num}", None
                
                chunk_info = current_project_chunks.value[chunk_num - 1]
                audio_file = chunk_info['audio_file']
                
                try:
                    # Load the audio file
                    with wave.open(audio_file, 'rb') as wav_file:
                        sample_rate = wav_file.getframerate()
                        frames = wav_file.readframes(wav_file.getnframes())
                        audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
                    
                    # Apply manual trimming
                    audio_tuple = (sample_rate, audio_data)
                    end_time_actual = None if end_time <= 0 else end_time
                    trimmed_audio, status_msg = extract_audio_segment(audio_tuple, start_time, end_time_actual)
                    
                    if trimmed_audio:
                        # Save the trimmed audio
                        save_status, new_file_path = save_trimmed_audio(trimmed_audio, audio_file, chunk_num)
                        combined_status = f"{status_msg}\n{save_status}"
                        return combined_status, new_file_path
                    else:
                        return status_msg, None
                        
                except Exception as e:
                    return f"❌ Error applying manual trim to chunk {chunk_num}: {str(e)}", None
            return apply_manual_trim
        
    
    # Download full project audio - Simplified to one button that does everything
    audio_player_components_for_download = [ci['audio'] for ci in chunk_interfaces[:MAX_CHUNKS_FOR_AUTO_SAVE]]

    download_project_btn.click(
        fn=combine_project_audio_chunks_split,  # Use new split function for better file management
        inputs=[current_project_name],
        outputs=[download_status]
    )
    
    # Previous Projects - Single Voice Tab
    refresh_previous_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=previous_project_dropdown
    )
    
    load_previous_btn.click(
        fn=load_previous_project_audio,
        inputs=previous_project_dropdown,
        outputs=[previous_project_audio, previous_project_download, previous_project_status]
    ).then(
        fn=lambda audio_path, download_path: (gr.Audio(visible=bool(audio_path)), gr.File(visible=bool(download_path))),
        inputs=[previous_project_audio, previous_project_download],
        outputs=[previous_project_audio, previous_project_download]
    )
    
    # Previous Projects - Multi-Voice Tab
    refresh_multi_previous_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=multi_previous_project_dropdown
    )
    
    load_multi_previous_btn.click(
        fn=load_previous_project_audio,
        inputs=multi_previous_project_dropdown,
        outputs=[multi_previous_project_audio, multi_previous_project_download, multi_previous_project_status]
    ).then(
        fn=lambda audio_path, download_path: (gr.Audio(visible=bool(audio_path)), gr.File(visible=bool(download_path))),
        inputs=[multi_previous_project_audio, multi_previous_project_download],
        outputs=[multi_previous_project_audio, multi_previous_project_download]
    )

    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=previous_project_dropdown
    )
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=multi_previous_project_dropdown
    )
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=project_dropdown
    )

    # --- Add these handlers after the main UI definition, before __main__ ---

    # Handler to load a single-voice project and populate fields

    def load_single_voice_project(project_name: str):
        """Load project info and update UI fields for single-voice tab."""
        text, voice_info, proj_name, _, status = load_project_for_regeneration(project_name)
        # Try to extract voice name from voice_info string
        import re
        voice_match = re.search(r'\(([^)]+)\)', voice_info)
        selected_voice = None
        if voice_match:
            selected_voice = voice_match.group(1)
        return text, selected_voice, proj_name, status

    # Handler to resume single-voice project generation

    def resume_single_voice_project(model, project_name, voice_library_path):
        # Load metadata to get text and voice
        projects = get_existing_projects()
        project = next((p for p in projects if p['name'] == project_name), None)
        if not project or not project.get('metadata'):
            return None, f"❌ Project '{project_name}' not found or missing metadata."
        metadata = project['metadata']
        text_content = metadata.get('text_content', '')
        voice_info = metadata.get('voice_info', {})
        selected_voice = voice_info.get('voice_name')
        if not text_content or not selected_voice:
            return None, "❌ Project metadata incomplete."
        return create_audiobook(model, text_content, voice_library_path, selected_voice, project_name, resume=True)

    # --- Wire up the buttons in the UI logic ---

    load_project_btn.click(
        fn=load_single_voice_project,
        inputs=single_project_dropdown,
        outputs=[audiobook_text, audiobook_voice_selector, project_name, single_project_progress]
    )

    resume_project_btn.click(
        fn=resume_single_voice_project,
        inputs=[model_state, single_project_dropdown, voice_library_path_state],
        outputs=[audiobook_output, single_project_progress]
    )

    # Download project button
    download_project_btn.click(
        fn=combine_project_audio_chunks_split,  # Use the new split function  
        inputs=[current_project_name],
        outputs=[download_status]
    )

    # NEW: Regenerate Sample Tab Functions
    
    # NEW: Listen & Edit Event Handlers
    def load_project_for_listen_edit(project_name: str) -> tuple:
        """Load a project for continuous Listen & Edit mode"""
        if not project_name:
            return None, "<div class='audiobook-status'>📁 Select a project to start listening</div>", {}, "", False, project_name
        
        # Clean up any previous continuous files
        cleanup_temp_continuous_files(project_name)
        
        # Create continuous audio
        result = create_continuous_playback_audio(project_name)
        
        if result[0] is None:
            return None, f"❌ {result[1]}", {}, "", False, project_name
        
        audio_data, status_msg = result
        audio_file_path, chunk_timings = audio_data
        
        # Get initial chunk info
        initial_chunk = chunk_timings[0] if chunk_timings else {}
        current_chunk_text = initial_chunk.get('text', '')
        
        success_status = f"✅ {status_msg}<br/>🎵 Ready for continuous editing!"
        regenerate_enabled = bool(initial_chunk)
        
        return audio_file_path, success_status, initial_chunk, current_chunk_text, regenerate_enabled, project_name
    
    def track_current_chunk(chunk_timings: list, audio_time: float) -> tuple:
        """Track which chunk is currently playing based on audio position"""
        if not chunk_timings or audio_time is None:
            return {}, "", False
        
        current_chunk = get_current_chunk_from_time(chunk_timings, audio_time)
        
        if not current_chunk:
            return {}, "", False
        
        chunk_info_html = f"""
        <div class='voice-status'>
            🎵 <strong>Chunk {current_chunk.get('chunk_num', 'N/A')}</strong><br/>
            ⏰ <strong>Time:</strong> {audio_time:.1f}s ({current_chunk.get('start_time', 0):.1f}s - {current_chunk.get('end_time', 0):.1f}s)<br/>
            📝 <strong>Duration:</strong> {current_chunk.get('end_time', 0) - current_chunk.get('start_time', 0):.1f}s
        </div>
        """
        
        chunk_text = current_chunk.get('text', '')
        regenerate_enabled = bool(current_chunk)
        
        return current_chunk, chunk_info_html, chunk_text, regenerate_enabled
    
    def regenerate_current_chunk_in_listen_mode(model, project_name: str, current_chunk: dict, custom_text: str, voice_library_path: str) -> tuple:
        """Regenerate the current chunk in Listen & Edit mode"""
        if not project_name or not current_chunk:
            return None, "❌ No chunk selected for regeneration", {}, "", False
        
        chunk_num = current_chunk.get('chunk_num')
        if not chunk_num:
            return None, "❌ Invalid chunk selected", {}, "", False
        
        # Clean up previous continuous files
        cleanup_temp_continuous_files(project_name)
        
        # Regenerate and update continuous audio
        result = regenerate_chunk_and_update_continuous(model, project_name, chunk_num, voice_library_path, custom_text)
        
        if result[0] is None:
            return None, f"❌ {result[1]}", {}, "", False
        
        continuous_data, status_msg, _ = result
        audio_file_path, chunk_timings = continuous_data
        
        # Update current chunk info
        updated_chunk = None
        for chunk_timing in chunk_timings:
            if chunk_timing['chunk_num'] == chunk_num:
                updated_chunk = chunk_timing
                break
        
        if not updated_chunk:
            updated_chunk = current_chunk
        
        chunk_info_html = f"""
        <div class='voice-status'>
            🎵 <strong>Chunk {updated_chunk.get('chunk_num', 'N/A')}</strong> (Regenerated)<br/>
            ⏰ <strong>Time:</strong> {updated_chunk.get('start_time', 0):.1f}s - {updated_chunk.get('end_time', 0):.1f}s<br/>
            📝 <strong>Duration:</strong> {updated_chunk.get('end_time', 0) - updated_chunk.get('start_time', 0):.1f}s
        </div>
        """
        
        success_status = f"✅ {status_msg}<br/>🎵 Audio will restart from beginning with your changes!"
        chunk_text = updated_chunk.get('text', custom_text)
        
        return audio_file_path, success_status, updated_chunk, chunk_info_html, chunk_text, True
    
    # Listen & Edit event handlers
    refresh_listen_projects_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=listen_project_dropdown
    )
    
    load_listen_project_btn.click(
        fn=load_project_for_listen_edit,
        inputs=[listen_project_dropdown],
        outputs=[continuous_audio_player, listen_edit_status, current_chunk_state, current_chunk_text, regenerate_current_btn, listen_edit_project_name]
    )
    
    # Note: Audio time tracking would need to be implemented with JavaScript for real-time tracking
    # For now, we'll implement basic regeneration functionality
    
    regenerate_current_btn.click(
        fn=regenerate_current_chunk_in_listen_mode,
        inputs=[model_state, listen_edit_project_name, current_chunk_state, current_chunk_text, voice_library_path_state],
        outputs=[continuous_audio_player, listen_edit_status, current_chunk_state, current_chunk_info, current_chunk_text, regenerate_current_btn]
    )
    
    jump_to_start_btn.click(
        fn=lambda audio_data: audio_data,  # This would reset the audio player position in a full implementation
        inputs=[continuous_audio_data],
        outputs=[continuous_audio_player]
    )
    
    # Load projects on tab initialization
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=listen_project_dropdown
    )
    
    # Load projects on tab initialization  
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=project_dropdown
    )
    
    # Refresh projects dropdown
    refresh_projects_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=project_dropdown
    )

    def auto_remove_dead_space(project_name: str, silence_threshold: float = -50.0, min_silence_duration: float = 0.5) -> tuple:
        """
        Automatically detect and remove dead space/silence from all audio chunks in a project.
        
        Args:
            project_name: Name of the project to process
            silence_threshold: Volume threshold in dB below which audio is considered silence
            min_silence_duration: Minimum duration in seconds for silence to be considered removable
        
        Returns:
            Tuple of (success_message, processed_files_count, errors_list)
        """
        try:
            import librosa
            import numpy as np
            from scipy.io import wavfile
            import soundfile as sf
            import os
            
            project_dir = os.path.join("audiobook_projects", project_name)
            if not os.path.exists(project_dir):
                return f"❌ Project '{project_name}' not found", 0, []
            
            chunk_files = [f for f in os.listdir(project_dir) if f.startswith(project_name + "_") and f.endswith(".wav") and not f.startswith("temp_")]
            if not chunk_files:
                return f"❌ No audio chunks found in project '{project_name}'", 0, []
            
            processed_count = 0
            errors = []
            backup_dir = os.path.join(project_dir, "backup_before_cleanup")
            os.makedirs(backup_dir, exist_ok=True)
            
            for chunk_file in chunk_files:
                try:
                    chunk_path = os.path.join(project_dir, chunk_file)
                    backup_path = os.path.join(backup_dir, chunk_file)
                    
                    # Create backup
                    import shutil
                    shutil.copy2(chunk_path, backup_path)
                    
                    # Load audio
                    audio, sr = librosa.load(chunk_path, sr=None)
                    
                    # Convert to dB
                    audio_db = librosa.amplitude_to_db(np.abs(audio), ref=np.max)
                    
                    # Find non-silent regions
                    non_silent = audio_db > silence_threshold
                    
                    # Find the start and end of non-silent regions
                    if np.any(non_silent):
                        non_silent_indices = np.where(non_silent)[0]
                        start_idx = non_silent_indices[0]
                        end_idx = non_silent_indices[-1] + 1
                        
                        # Trim the audio
                        trimmed_audio = audio[start_idx:end_idx]
                        
                        # Only save if we actually trimmed something significant
                        original_duration = len(audio) / sr
                        trimmed_duration = len(trimmed_audio) / sr
                        
                        if original_duration - trimmed_duration > min_silence_duration:
                            # Save the trimmed audio
                            sf.write(chunk_path, trimmed_audio, sr)
                            processed_count += 1
                            print(f"Trimmed {chunk_file}: {original_duration:.2f}s -> {trimmed_duration:.2f}s")
                        else:
                            # Remove backup if no significant change
                            os.remove(backup_path)
                    else:
                        errors.append(f"{chunk_file}: Appears to be completely silent")
                        
                except Exception as e:
                    errors.append(f"{chunk_file}: {str(e)}")
                    continue
            
            if processed_count > 0:
                success_msg = f"✅ Successfully processed {processed_count} chunks. Backups saved in backup_before_cleanup folder."
            else:
                success_msg = f"ℹ️ No dead space found to remove in {len(chunk_files)} chunks."
                
            return success_msg, processed_count, errors
            
        except ImportError as e:
            return f"❌ Missing required library for audio processing: {str(e)}", 0, []
        except Exception as e:
            return f"❌ Error processing project: {str(e)}", 0, []


    def analyze_project_audio_quality(project_name: str) -> tuple:
        """
        Analyze audio quality metrics for all chunks in a project.
        
        Returns:
            Tuple of (analysis_report, metrics_dict)
        """
        try:
            import librosa
            import numpy as np
            import os
            
            project_dir = os.path.join("audiobook_projects", project_name)
            if not os.path.exists(project_dir):
                return f"❌ Project '{project_name}' not found", {}
            
            chunk_files = [f for f in os.listdir(project_dir) if f.startswith(project_name + "_") and f.endswith(".wav") and not f.startswith("temp_")]
            if not chunk_files:
                return f"❌ No audio chunks found in project '{project_name}'", {}
            
            metrics = {
                'total_chunks': len(chunk_files),
                'silent_chunks': 0,
                'short_chunks': 0,
                'long_silence_chunks': 0,
                'avg_duration': 0,
                'total_duration': 0
            }
            
            durations = []
            problematic_chunks = []
            
            for chunk_file in chunk_files:
                try:
                    chunk_path = os.path.join(project_dir, chunk_file)
                    audio, sr = librosa.load(chunk_path, sr=None)
                    duration = len(audio) / sr
                    durations.append(duration)
                    
                    # Check for silence
                    audio_db = librosa.amplitude_to_db(np.abs(audio), ref=np.max)
                    if np.max(audio_db) < -40:  # Very quiet
                        metrics['silent_chunks'] += 1
                        problematic_chunks.append(f"{chunk_file}: Very quiet/silent")
                    
                    # Check for very short chunks
                    if duration < 0.5:
                        metrics['short_chunks'] += 1
                        problematic_chunks.append(f"{chunk_file}: Very short ({duration:.2f}s)")
                    
                    # Check for long silence at beginning/end
                    silence_threshold = -50
                    non_silent = audio_db > silence_threshold
                    if np.any(non_silent):
                        non_silent_indices = np.where(non_silent)[0]
                        start_silence = non_silent_indices[0] / sr
                        end_silence = (len(audio) - non_silent_indices[-1]) / sr
                        
                        if start_silence > 1.0 or end_silence > 1.0:
                            metrics['long_silence_chunks'] += 1
                            problematic_chunks.append(f"{chunk_file}: Long silence (start: {start_silence:.2f}s, end: {end_silence:.2f}s)")
                            
                except Exception as e:
                    problematic_chunks.append(f"{chunk_file}: Analysis error - {str(e)}")
            
            metrics['avg_duration'] = np.mean(durations) if durations else 0
            metrics['total_duration'] = np.sum(durations) if durations else 0
            
            report = f"""📊 Audio Quality Analysis for '{project_name}':
            
📈 Overall Stats:
• Total Chunks: {metrics['total_chunks']}
• Total Duration: {metrics['total_duration']:.1f} seconds ({metrics['total_duration']/60:.1f} minutes)
• Average Chunk Duration: {metrics['avg_duration']:.2f} seconds

⚠️ Potential Issues:
• Silent/Very Quiet Chunks: {metrics['silent_chunks']}
• Very Short Chunks: {metrics['short_chunks']} 
• Chunks with Long Silence: {metrics['long_silence_chunks']}

📋 Problematic Chunks:
{chr(10).join(problematic_chunks[:10])}
{'... and more' if len(problematic_chunks) > 10 else ''}
"""
            
            return report, metrics
            
        except ImportError:
            return "❌ Missing required libraries for audio analysis (librosa, numpy)", {}
        except Exception as e:
            return f"❌ Error analyzing project: {str(e)}", {}

    # Load projects on tab initialization  
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=project_dropdown
    )
    
    # Refresh projects dropdown
    refresh_projects_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=project_dropdown
    )
    
    # Clean Samples event handlers
    clean_project_state = gr.State("")
    
    def load_clean_project(project_name: str) -> tuple:
        """Load a project for cleaning operations"""
        if not project_name:
            return "📁 Select a project to start cleaning", True, True, True, project_name
        
        project_dir = os.path.join("audiobook_projects", project_name)
        if not os.path.exists(project_dir):
            return f"❌ Project '{project_name}' not found", True, True, True, ""
        
        chunk_files = [f for f in os.listdir(project_dir) if f.startswith(project_name + "_") and f.endswith(".wav") and not f.startswith("temp_")]
        if not chunk_files:
            return f"❌ No audio chunks found in project '{project_name}'", True, True, True, ""
        
        status_msg = f"✅ Project '{project_name}' loaded successfully!<br/>📊 Found {len(chunk_files)} audio chunks ready for analysis and cleaning."
        return status_msg, True, True, True, project_name
    
    refresh_clean_projects_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=clean_project_dropdown
    )
    
    load_clean_project_btn.click(
        fn=load_clean_project,
        inputs=[clean_project_dropdown],
        outputs=[clean_project_status, analyze_audio_btn, auto_clean_btn, preview_clean_btn, clean_project_state]
    )
    
    analyze_audio_btn.click(
        fn=analyze_project_audio_quality,
        inputs=[clean_project_state],
        outputs=[audio_analysis_results]
    )
    
    def handle_auto_clean(project_name: str, silence_threshold: float, min_silence_duration: float) -> tuple:
        """Handle automatic dead space removal"""
        if not project_name:
            return "❌ No project loaded", "📝 Load a project first"
        
        result = auto_remove_dead_space(project_name, silence_threshold, min_silence_duration)
        success_msg, processed_count, errors = result
        
        if errors:
            error_msg = f"<br/>⚠️ Errors encountered:<br/>" + "<br/>".join(errors[:5])
            if len(errors) > 5:
                error_msg += f"<br/>... and {len(errors) - 5} more errors"
            success_msg += error_msg
        
        detailed_results = f"""
        <div class='instruction-box'>
            <h4>🧹 Cleanup Results:</h4>
            <p><strong>Files Processed:</strong> {processed_count}</p>
            <p><strong>Status:</strong> {success_msg}</p>
        </div>
        """
        
        return success_msg, detailed_results
    
    auto_clean_btn.click(
        fn=handle_auto_clean,
        inputs=[clean_project_state, silence_threshold, min_silence_duration],
        outputs=[cleanup_status, cleanup_results]
    )
    
    def preview_cleanup_changes(project_name: str, silence_threshold: float, min_silence_duration: float) -> str:
        """Preview what will be cleaned without making changes"""
        if not project_name:
            return "❌ No project loaded"
        
        # This would analyze without making changes
        analysis_result = analyze_project_audio_quality(project_name)
        report, metrics = analysis_result
        
        preview_msg = f"""
        <div class='instruction-box'>
            <h4>👁️ Cleanup Preview:</h4>
            <p><strong>Silence Threshold:</strong> {silence_threshold} dB</p>
            <p><strong>Min Silence Duration:</strong> {min_silence_duration}s</p>
            <p><strong>Potential Issues Found:</strong></p>
            {report}
            <p><strong>💡 Note:</strong> This is a preview - no files will be modified until you run Auto Remove Dead Space.</p>
        </div>
        """
        
        return preview_msg
    
    preview_clean_btn.click(
        fn=preview_cleanup_changes,
        inputs=[clean_project_state, silence_threshold, min_silence_duration],
        outputs=[cleanup_results]
    )
    
    # Load clean projects dropdown on tab initialization
    demo.load(
        fn=force_refresh_single_project_dropdown,
        inputs=[],
        outputs=clean_project_dropdown
    )

    # Listen & Edit refresh handler (essential for project sync)
    refresh_listen_projects_btn.click(
        fn=force_complete_project_refresh,
        inputs=[],
        outputs=listen_project_dropdown
    )

    # Volume normalization event handlers
    volume_preset_dropdown.change(
        fn=apply_volume_preset,
        inputs=[volume_preset_dropdown, target_volume_level],
        outputs=[target_volume_level, volume_status]
    )
    
    enable_voice_normalization.change(
        fn=get_volume_normalization_status,
        inputs=[enable_voice_normalization, target_volume_level, voice_audio],
        outputs=volume_status
    )
    
    target_volume_level.change(
        fn=get_volume_normalization_status,
        inputs=[enable_voice_normalization, target_volume_level, voice_audio],
        outputs=volume_status
    )
    
    voice_audio.change(
        fn=get_volume_normalization_status,
        inputs=[enable_voice_normalization, target_volume_level, voice_audio],
        outputs=volume_status
    )
    
    # Volume preset handlers for single-voice audiobook
    volume_preset.change(
        fn=apply_volume_preset,
        inputs=[volume_preset, target_volume_level],
        outputs=[target_volume_level, volume_status]
    )
    
    target_volume_level.change(
        fn=lambda enable, target, audio: get_volume_normalization_status(enable, target, audio),
        inputs=[enable_volume_norm, target_volume_level, gr.State(None)],
        outputs=volume_status
    )
    
    # Volume preset handlers for multi-voice audiobook
    multi_volume_preset.change(
        fn=apply_volume_preset,
        inputs=[multi_volume_preset, multi_target_volume_level],
        outputs=[multi_target_volume_level, multi_volume_status]
    )
    
    multi_target_volume_level.change(
        fn=lambda enable, target, audio: get_volume_normalization_status(enable, target, audio),
        inputs=[multi_enable_volume_norm, multi_target_volume_level, gr.State(None)],
        outputs=multi_volume_status
    )
    
    # Enhanced Validation with project name

def load_text_files_batch(file_paths: list) -> tuple:
    """
    Load multiple text files for batch processing.
    
    Args:
        file_paths: List of file paths to load
        
    Returns:
        tuple: (list_of_contents, status_message)
    """
    if not file_paths:
        return [], "No files uploaded"
    
    loaded_files = []
    total_words = 0
    
    for i, file_path in enumerate(file_paths):
        try:
            content, status = load_text_file(file_path)
            if content:
                loaded_files.append({
                    'content': content,
                    'filename': os.path.basename(file_path),
                    'words': len(content.split())
                })
                total_words += len(content.split())
            else:
                return [], f"❌ Error loading file {i+1}: {status}"
        except Exception as e:
            return [], f"❌ Error loading file {i+1}: {str(e)}"
    
    status_msg = f"✅ Loaded {len(loaded_files)} files ({total_words} total words)"
    return loaded_files, status_msg

def validate_batch_audiobook_input(file_list: list, selected_voice: str, project_name: str) -> tuple:
    """
    Validate inputs for batch audiobook creation.
    
    Args:
        file_list: List of loaded file contents
        selected_voice: Selected voice profile name
        project_name: Base project name
        
    Returns:
        tuple: (process_button_state, status_message, dummy_output)
    """
    if not file_list:
        return gr.Button(interactive=False), "❌ No files loaded for batch processing", None
    
    if not selected_voice:
        return gr.Button(interactive=False), "❌ Please select a voice profile", None
    
    if not project_name or not project_name.strip():
        return gr.Button(interactive=False), "❌ Please enter a project name", None
    
    # Check if project name is valid
    safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
    if not safe_project_name:
        return gr.Button(interactive=False), "❌ Project name contains invalid characters", None
    
    total_files = len(file_list)
    total_words = sum(f['words'] for f in file_list)
    
    status_msg = f"✅ Ready to process {total_files} files ({total_words} total words) with voice '{selected_voice}' as project '{project_name}'"
    
    return gr.Button(interactive=True), status_msg, None

def create_batch_audiobook(
    model,
    file_list: list,
    voice_library_path: str,
    selected_voice: str,
    project_name: str,
    enable_norm: bool = True,
    target_level: float = -18.0
) -> tuple:
    """
    Create multiple audiobooks from a batch of files.
    
    Args:
        model: TTS model instance
        file_list: List of loaded file contents with metadata
        voice_library_path: Path to voice library
        selected_voice: Selected voice profile name
        project_name: Base project name (will be suffixed with -1, -2, etc.)
        enable_norm: Whether to enable volume normalization
        target_level: Target volume level in dB
        
    Returns:
        tuple: (last_audio_output, final_status_message)
    """
    if not file_list:
        return None, "❌ No files to process"
    
    if not selected_voice:
        return None, "❌ No voice selected"
    
    if not project_name or not project_name.strip():
        return None, "❌ No project name provided"
    
    # Validate voice exists
    voice_config = get_voice_config(voice_library_path, selected_voice)
    if not voice_config:
        return None, f"❌ Could not load voice configuration for '{selected_voice}'"
    
    total_files = len(file_list)
    successful_projects = []
    failed_projects = []
    last_audio = None
    
    try:
        # Process each file in the batch
        for i, file_info in enumerate(file_list, 1):
            try:
                # Create project name with suffix
                current_project_name = f"{project_name}-{i}"
                
                print(f"🎵 Processing file {i}/{total_files}: {file_info['filename']} -> {current_project_name}")
                
                # Create audiobook for this file
                result = create_audiobook_with_volume_settings(
                    model=model,
                    text_content=file_info['content'],
                    voice_library_path=voice_library_path,
                    selected_voice=selected_voice,
                    project_name=current_project_name,
                    enable_norm=enable_norm,
                    target_level=target_level
                )
                
                if result and len(result) >= 2 and result[0] is not None:
                    # Success
                    last_audio = result[0]  # Keep the last successful audio for preview
                    successful_projects.append({
                        'name': current_project_name,
                        'filename': file_info['filename'],
                        'words': file_info['words']
                    })
                    print(f"✅ Completed: {current_project_name}")
                else:
                    # Failed
                    error_msg = result[1] if result and len(result) > 1 else "Unknown error"
                    failed_projects.append({
                        'name': current_project_name,
                        'filename': file_info['filename'],
                        'error': error_msg
                    })
                    print(f"❌ Failed: {current_project_name} - {error_msg}")
                
                # Clear GPU memory between files to prevent accumulation
                clear_gpu_memory()
                
            except Exception as e:
                error_msg = str(e)
                failed_projects.append({
                    'name': f"{project_name}-{i}",
                    'filename': file_info['filename'],
                    'error': error_msg
                })
                print(f"❌ Exception in file {i}: {error_msg}")
                continue
    
    except Exception as e:
        return None, f"❌ Batch processing failed: {str(e)}"
    
    # Generate final status message
    status_parts = []
    
    if successful_projects:
        status_parts.append(f"✅ Successfully created {len(successful_projects)} audiobooks:")
        for proj in successful_projects:
            status_parts.append(f"  • {proj['name']} ({proj['filename']}, {proj['words']} words)")
    
    if failed_projects:
        status_parts.append(f"\n❌ Failed to create {len(failed_projects)} audiobooks:")
        for proj in failed_projects:
            status_parts.append(f"  • {proj['name']} ({proj['filename']}) - {proj['error']}")
    
    if not successful_projects and not failed_projects:
        status_parts.append("❌ No files were processed")
    
    status_parts.append(f"\n📁 All completed audiobooks are saved in the audiobook_projects directory")
    status_parts.append(f"🎧 Preview shows the last successfully generated audiobook")
    
    final_status = "\n".join(status_parts)
    
    return last_audio, final_status

if __name__ == "__main__":
    demo.queue(
        max_size=50,
        default_concurrency_limit=1,
    ).launch(share=True)
