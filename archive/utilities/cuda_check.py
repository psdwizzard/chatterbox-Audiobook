#!/usr/bin/env python3
"""
CUDA verification for ChatterBox TTS
"""

import torch
from src.chatterbox.tts import ChatterboxTTS

print("🔧 CUDA Verification for ChatterBox")
print("=" * 40)

# Check PyTorch CUDA
print(f"PyTorch Version: {torch.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"GPU Name: {torch.cuda.get_device_name(0)}")
    print(f"GPU Memory: {torch.cuda.get_device_properties(0).total_memory // 1024**3} GB")
    
    # Test device selection logic (same as in gradio app)
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Selected Device: {DEVICE}")
    
    # Test model loading on correct device
    try:
        print("\n⏳ Loading ChatterBox model...")
        model = ChatterboxTTS.from_pretrained(DEVICE)
        
        # Verify model is on GPU
        model_device = next(model.t3.parameters()).device
        print(f"✅ Model loaded on device: {model_device}")
        
        if str(model_device).startswith('cuda'):
            print("🎉 SUCCESS: Model is properly using GPU!")
        else:
            print("⚠️  WARNING: Model is not on GPU")
            
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        
else:
    print("❌ CUDA not available - check PyTorch installation")
    print("💡 Run: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124") 