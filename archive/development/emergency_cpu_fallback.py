#!/usr/bin/env python3
"""
Emergency CPU Fallback for TTS Generation

This script provides a CPU-only fallback for TTS generation when CUDA errors persist.
Use this to continue audiobook generation while debugging CUDA issues.

Usage:
    python emergency_cpu_fallback.py "Your text here" output.wav
"""

import sys
import os
import torch
import argparse
from pathlib import Path

# Add project src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

def force_cpu_mode():
    """Force PyTorch to use CPU only."""
    # Disable CUDA globally
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    
    # Force CPU device
    torch.cuda.is_available = lambda: False
    
    print("🔄 Forced CPU-only mode activated")

def generate_audio_cpu_safe(text: str, output_path: str, voice: str = "default"):
    """Generate audio using CPU-only mode with extensive error handling."""
    
    try:
        print(f"🧪 Attempting CPU-only generation...")
        print(f"📝 Text: {text[:100]}{'...' if len(text) > 100 else ''}")
        print(f"🎯 Output: {output_path}")
        
        # Force CPU mode
        force_cpu_mode()
        
        # Import models (this should now load in CPU mode)
        from audiobook.models import load_models, generate as models_generate
        
        print("📦 Loading models in CPU mode...")
        models = load_models()
        print("✅ Models loaded successfully")
        
        # Generate with conservative settings
        print("🎵 Generating audio...")
        wav = models_generate(
            text=text,
            voice=voice,
            temperature=0.7,  # Conservative temperature
            repetition_penalty=1.1,
            max_length=100,   # Shorter sequences for safety
            style={"speed": 1.0}
        )
        
        print("✅ Audio generation successful")
        
        # Save the audio
        import scipy.io.wavfile as wavfile
        import numpy as np
        
        # Convert to proper format if needed
        if isinstance(wav, torch.Tensor):
            wav = wav.cpu().numpy()
        
        # Ensure proper format for saving
        if wav.dtype != np.int16:
            wav = (wav * 32767).astype(np.int16)
        
        # Save
        wavfile.write(output_path, 24000, wav)  # Assuming 24kHz sample rate
        print(f"💾 Audio saved to: {output_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ CPU generation failed: {e}")
        print(f"📋 Error type: {type(e).__name__}")
        return False

def chunk_text_for_cpu(text: str, max_chars: int = 200):
    """Chunk text into smaller pieces for CPU processing."""
    
    # Use our existing chunking system
    try:
        from audiobook.processing import chunk_text_by_sentences
        chunks = chunk_text_by_sentences(text, max_words=30)  # Smaller chunks for CPU
        return chunks
    except:
        # Fallback to simple sentence splitting
        import re
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Combine sentences to stay under character limit
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk + sentence) < max_chars:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks

def generate_audiobook_cpu(text: str, output_dir: str, project_name: str = "cpu_fallback"):
    """Generate a complete audiobook using CPU mode."""
    
    print(f"🚀 Starting CPU-only audiobook generation")
    print(f"📁 Output directory: {output_dir}")
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Chunk the text
    print("✂️  Chunking text...")
    chunks = chunk_text_for_cpu(text)
    print(f"📊 Created {len(chunks)} chunks")
    
    # Generate each chunk
    successful_chunks = []
    failed_chunks = []
    
    for i, chunk in enumerate(chunks, 1):
        print(f"\n🎯 Processing chunk {i}/{len(chunks)}")
        
        output_file = output_path / f"{project_name}_{i:03d}.wav"
        
        success = generate_audio_cpu_safe(chunk, str(output_file))
        
        if success:
            successful_chunks.append(str(output_file))
            print(f"✅ Chunk {i} completed")
        else:
            failed_chunks.append((i, chunk))
            print(f"❌ Chunk {i} failed")
    
    # Summary
    print(f"\n📋 Generation Summary:")
    print(f"✅ Successful: {len(successful_chunks)}/{len(chunks)}")
    print(f"❌ Failed: {len(failed_chunks)}/{len(chunks)}")
    
    if failed_chunks:
        print(f"\n⚠️  Failed chunks:")
        for chunk_num, chunk_text in failed_chunks:
            print(f"   Chunk {chunk_num}: {chunk_text[:50]}...")
    
    return successful_chunks, failed_chunks

def main():
    """Main function for command-line usage."""
    parser = argparse.ArgumentParser(description="Emergency CPU-only TTS generation")
    parser.add_argument("text", help="Text to generate (or path to text file)")
    parser.add_argument("output", help="Output file or directory")
    parser.add_argument("--voice", default="default", help="Voice to use")
    parser.add_argument("--project", default="cpu_fallback", help="Project name")
    parser.add_argument("--audiobook", action="store_true", help="Generate full audiobook")
    
    args = parser.parse_args()
    
    # Read text input
    if os.path.isfile(args.text):
        with open(args.text, 'r', encoding='utf-8') as f:
            text = f.read()
        print(f"📖 Loaded text from file: {args.text}")
    else:
        text = args.text
        print(f"📝 Using provided text")
    
    if args.audiobook:
        # Generate full audiobook
        successful, failed = generate_audiobook_cpu(text, args.output, args.project)
        print(f"\n🏁 Audiobook generation complete!")
        print(f"📁 Files saved to: {args.output}")
    else:
        # Generate single audio file
        success = generate_audio_cpu_safe(text, args.output, args.voice)
        if success:
            print(f"✅ Single file generation successful: {args.output}")
        else:
            print(f"❌ Single file generation failed")
            sys.exit(1)

if __name__ == "__main__":
    main() 