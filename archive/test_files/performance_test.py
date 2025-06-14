#!/usr/bin/env python3
"""
Performance Test Script for ChatterBox TTS
Tests token generation speed and measures improvements after optimization
"""

import time
import torch
from src.chatterbox.tts import ChatterboxTTS

def test_token_generation_performance():
    """Test token generation speed with a sample text"""
    
    # Sample text for testing (around 50 words)
    test_text = """
    The quick brown fox jumps over the lazy dog. This pangram contains every letter 
    of the English alphabet at least once. It's commonly used for testing fonts, 
    keyboards, and other text-related applications. The phrase has been used since 
    the early 1900s and remains popular today for various testing purposes.
    """
    
    print("🚀 ChatterBox TTS Performance Test")
    print("=" * 50)
    print(f"📝 Test text: {len(test_text.split())} words")
    print(f"💻 Device: {torch.cuda.get_device_name() if torch.cuda.is_available() else 'CPU'}")
    print(f"🔧 CUDA Available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        print(f"📊 GPU Memory: {torch.cuda.get_device_properties(0).total_memory // 1024**3} GB")
    
    print("\n⏳ Loading model...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    try:
        # Load model
        model_start = time.time()
        model = ChatterboxTTS.from_pretrained(device)
        model_load_time = time.time() - model_start
        print(f"✅ Model loaded in {model_load_time:.2f} seconds")
        
        # Test generation (need to prepare conditionals first)
        print("\n🎯 Testing generation performance...")
        
        # Multiple runs for averaging
        generation_times = []
        token_counts = []
        
        for run in range(3):
            print(f"\n🔄 Run {run + 1}/3...")
            
            start_time = time.time()
            
            # Generate audio (this will use the dynamic max_new_tokens optimization)
            audio_result = model.generate(
                text=test_text,
                audio_prompt_path=None,  # Will use default conditionals if available
                exaggeration=0.5,
                cfg_weight=0.5,  # Use moderate CFG
                temperature=0.8
            )
            
            end_time = time.time()
            generation_time = end_time - start_time
            generation_times.append(generation_time)
            
            # Estimate tokens (rough calculation based on audio length)
            audio_length_seconds = len(audio_result[0]) / model.sr
            estimated_tokens = int(audio_length_seconds * 12)  # Rough estimate: ~12 tokens per second
            token_counts.append(estimated_tokens)
            
            tokens_per_second = estimated_tokens / generation_time
            
            print(f"   ⏱️  Generation time: {generation_time:.2f}s")
            print(f"   🎵 Audio length: {audio_length_seconds:.2f}s")
            print(f"   🔢 Estimated tokens: {estimated_tokens}")
            print(f"   ⚡ Tokens/sec: {tokens_per_second:.1f}")
        
        # Calculate averages
        avg_generation_time = sum(generation_times) / len(generation_times)
        avg_tokens = sum(token_counts) / len(token_counts)
        avg_tokens_per_second = avg_tokens / avg_generation_time
        
        print("\n📈 PERFORMANCE SUMMARY")
        print("=" * 30)
        print(f"Average generation time: {avg_generation_time:.2f}s")
        print(f"Average estimated tokens: {avg_tokens:.0f}")
        print(f"Average tokens per second: {avg_tokens_per_second:.1f}")
        
        # Performance assessment
        if avg_tokens_per_second >= 24:
            print("🟢 EXCELLENT: Performance is at target level (24+ tokens/sec)")
        elif avg_tokens_per_second >= 18:
            print("🟡 GOOD: Performance is improved but below target")
        elif avg_tokens_per_second >= 12:
            print("🟠 FAIR: Performance is at baseline level")
        else:
            print("🔴 POOR: Performance is below baseline")
            
        print(f"\n💡 Target was 24-30 tokens/sec (from original performance)")
        print(f"🎯 Current: {avg_tokens_per_second:.1f} tokens/sec")
        
        return avg_tokens_per_second
        
    except Exception as e:
        print(f"❌ Error during performance test: {str(e)}")
        print("💡 Make sure you have a voice profile configured or the model has built-in conditionals")
        return None

if __name__ == "__main__":
    test_token_generation_performance() 