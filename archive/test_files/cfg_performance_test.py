#!/usr/bin/env python3
"""
CFG Performance Test - Check how cfg_weight affects generation speed
"""

import time
import torch
from src.chatterbox.tts import ChatterboxTTS

def test_cfg_performance():
    """Test performance with different CFG weights"""
    
    test_text = "The quick brown fox jumps over the lazy dog. This is a test sentence for measuring performance."
    
    print("🎛️  CFG Performance Test")
    print("=" * 40)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    
    try:
        model = ChatterboxTTS.from_pretrained(device)
        print("✅ Model loaded")
        
        # Test different CFG weights
        cfg_weights = [0.3, 0.5, 0.7, 1.0]
        
        for cfg_weight in cfg_weights:
            print(f"\n🧪 Testing CFG Weight: {cfg_weight}")
            
            start_time = time.time()
            
            try:
                audio_result = model.generate(
                    text=test_text,
                    audio_prompt_path=None,
                    exaggeration=0.5,
                    cfg_weight=cfg_weight,
                    temperature=0.8
                )
                
                generation_time = time.time() - start_time
                audio_length = len(audio_result[0]) / model.sr
                estimated_tokens = int(audio_length * 12)
                tokens_per_sec = estimated_tokens / generation_time
                
                print(f"   ⏱️  Time: {generation_time:.2f}s")
                print(f"   🎵 Audio: {audio_length:.2f}s")
                print(f"   ⚡ Speed: {tokens_per_sec:.1f} tokens/sec")
                
            except Exception as e:
                print(f"   ❌ Error: {str(e)}")
                
    except Exception as e:
        print(f"❌ Error loading model: {e}")

if __name__ == "__main__":
    test_cfg_performance() 