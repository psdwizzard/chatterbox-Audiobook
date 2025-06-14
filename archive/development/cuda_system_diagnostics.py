#!/usr/bin/env python3
"""
CUDA System Diagnostics for Persistent srcIndex Errors

This script performs comprehensive system-level debugging to identify
the root cause of the persistent CUDA "srcIndex < srcSelectDimSize" error.

Run this BEFORE attempting any TTS generation to identify system issues.
"""

import os
import sys
import gc
import torch
import subprocess
import psutil
from datetime import datetime
from pathlib import Path

def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"🔍 {title}")
    print(f"{'='*60}")

def check_cuda_environment():
    """Check CUDA environment and drivers."""
    print_header("CUDA Environment Check")
    
    try:
        # CUDA availability
        print(f"✅ CUDA Available: {torch.cuda.is_available()}")
        
        if torch.cuda.is_available():
            print(f"✅ CUDA Device Count: {torch.cuda.device_count()}")
            print(f"✅ Current CUDA Device: {torch.cuda.current_device()}")
            print(f"✅ CUDA Device Name: {torch.cuda.get_device_name()}")
            
            # CUDA version
            print(f"✅ CUDA Version (Runtime): {torch.version.cuda}")
            
            # GPU Memory
            gpu_memory = torch.cuda.get_device_properties(0).total_memory
            print(f"✅ Total GPU Memory: {gpu_memory / 1024**3:.2f} GB")
            
            # Current memory usage
            allocated = torch.cuda.memory_allocated() / 1024**3
            reserved = torch.cuda.memory_reserved() / 1024**3
            print(f"⚠️  Currently Allocated: {allocated:.2f} GB")
            print(f"⚠️  Currently Reserved: {reserved:.2f} GB")
            
        # Check NVIDIA driver
        try:
            result = subprocess.run(['nvidia-smi'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("✅ NVIDIA Driver Working")
                # Extract driver version
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Driver Version:' in line:
                        print(f"✅ {line.strip()}")
                        break
            else:
                print("❌ nvidia-smi failed")
        except:
            print("❌ nvidia-smi not available")
            
    except Exception as e:
        print(f"❌ CUDA Environment Check Failed: {e}")

def check_pytorch_environment():
    """Check PyTorch installation and configuration."""
    print_header("PyTorch Environment Check")
    
    try:
        print(f"✅ PyTorch Version: {torch.__version__}")
        print(f"✅ PyTorch CUDA Version: {torch.version.cuda}")
        print(f"✅ Python Version: {sys.version}")
        
        # Check if PyTorch was compiled with CUDA
        print(f"✅ PyTorch Built with CUDA: {torch.cuda.is_available()}")
        
        # Check cuDNN
        print(f"✅ cuDNN Available: {torch.backends.cudnn.enabled}")
        if torch.backends.cudnn.enabled:
            print(f"✅ cuDNN Version: {torch.backends.cudnn.version()}")
            
    except Exception as e:
        print(f"❌ PyTorch Environment Check Failed: {e}")

def check_system_resources():
    """Check system memory and CPU resources."""
    print_header("System Resources Check")
    
    try:
        # CPU Usage
        cpu_percent = psutil.cpu_percent(interval=1)
        print(f"💻 CPU Usage: {cpu_percent}%")
        
        # Memory Usage
        memory = psutil.virtual_memory()
        print(f"💾 Total Memory: {memory.total / 1024**3:.2f} GB")
        print(f"💾 Available Memory: {memory.available / 1024**3:.2f} GB")
        print(f"💾 Memory Usage: {memory.percent}%")
        
        # Disk Space
        disk = psutil.disk_usage('.')
        print(f"💽 Total Disk: {disk.total / 1024**3:.2f} GB")
        print(f"💽 Free Disk: {disk.free / 1024**3:.2f} GB")
        
        # Temperature (if available)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                print("🌡️  System Temperatures:")
                for name, entries in temps.items():
                    for entry in entries:
                        print(f"   {name}: {entry.current}°C")
        except:
            print("🌡️  Temperature monitoring not available")
            
    except Exception as e:
        print(f"❌ System Resources Check Failed: {e}")

def test_basic_cuda_operations():
    """Test basic CUDA operations to identify corruption."""
    print_header("Basic CUDA Operations Test")
    
    if not torch.cuda.is_available():
        print("❌ CUDA not available - skipping GPU tests")
        return False
    
    try:
        # Clear any existing memory
        torch.cuda.empty_cache()
        gc.collect()
        
        # Test 1: Simple tensor creation
        print("🧪 Test 1: Simple tensor creation...")
        x = torch.randn(100, 100, device='cuda')
        print("✅ Simple tensor creation successful")
        
        # Test 2: Basic operations
        print("🧪 Test 2: Basic tensor operations...")
        y = x @ x.T
        print("✅ Basic tensor operations successful")
        
        # Test 3: Memory operations
        print("🧪 Test 3: Memory transfer operations...")
        z = y.cpu()
        w = z.cuda()
        print("✅ Memory transfer operations successful")
        
        # Test 4: Index operations (related to our error)
        print("🧪 Test 4: Index operations...")
        indices = torch.randint(0, 50, (10,), device='cuda')
        selected = x[indices]
        print("✅ Index operations successful")
        
        # Test 5: Embedding-like operations
        print("🧪 Test 5: Embedding-like operations...")
        embedding = torch.nn.Embedding(1000, 256).cuda()
        input_ids = torch.randint(0, 1000, (10, 20), device='cuda')
        output = embedding(input_ids)
        print("✅ Embedding operations successful")
        
        # Clean up
        del x, y, z, w, indices, selected, embedding, input_ids, output
        torch.cuda.empty_cache()
        
        return True
        
    except Exception as e:
        print(f"❌ CUDA Operations Test Failed: {e}")
        print(f"💡 This suggests GPU/driver issues rather than text chunking problems")
        return False

def test_model_loading():
    """Test if the TTS model can be loaded without errors."""
    print_header("Model Loading Test")
    
    try:
        # Add project src to path
        sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
        
        print("🧪 Testing model import...")
        from audiobook.models import load_models, generate as models_generate
        print("✅ Model import successful")
        
        print("🧪 Testing model loading...")
        # This should trigger model loading
        models = load_models()
        print("✅ Model loading successful")
        
        # Test a very simple generation (minimal text)
        print("🧪 Testing minimal generation...")
        test_text = "Hello."  # Very simple, safe text
        try:
            wav = models_generate(
                text=test_text,
                voice="default",
                temperature=0.5,
                repetition_penalty=1.1,
                max_length=50,
                style={"speed": 1.0}
            )
            print("✅ Minimal generation successful")
            return True
        except Exception as gen_error:
            print(f"❌ Minimal generation failed: {gen_error}")
            print("💡 This confirms the issue is in the TTS model, not text processing")
            return False
            
    except Exception as e:
        print(f"❌ Model Loading Test Failed: {e}")
        return False

def recommend_fixes(cuda_ok: bool, model_ok: bool):
    """Recommend fixes based on test results."""
    print_header("Recommended Fixes")
    
    if not cuda_ok:
        print("🚨 CUDA SYSTEM ISSUES DETECTED")
        print("📋 Immediate Actions:")
        print("   1. Restart your computer completely")
        print("   2. Update NVIDIA GPU drivers")
        print("   3. Reinstall CUDA toolkit")
        print("   4. Check GPU hardware (overheating, power)")
        print("   5. Try different PyTorch CUDA version")
        
    elif not model_ok:
        print("🚨 MODEL/APPLICATION ISSUES DETECTED")
        print("📋 Immediate Actions:")
        print("   1. Restart the Python application completely")
        print("   2. Clear all cached model files")
        print("   3. Force CPU-only mode for testing")
        print("   4. Check model checkpoint integrity")
        print("   5. Reduce batch sizes/sequence lengths")
        
    else:
        print("✅ System appears healthy - issue may be specific to certain text patterns")
        print("📋 Try These:")
        print("   1. Test with completely different text")
        print("   2. Use CPU-only mode temporarily") 
        print("   3. Restart application between generations")
        print("   4. Monitor during generation for memory spikes")

def main():
    """Run comprehensive diagnostics."""
    print(f"🚀 CUDA System Diagnostics Started: {datetime.now()}")
    
    # Run all diagnostic checks
    check_cuda_environment()
    check_pytorch_environment()
    check_system_resources()
    
    # Test CUDA operations
    cuda_ok = test_basic_cuda_operations()
    
    # Test model loading
    model_ok = test_model_loading()
    
    # Provide recommendations
    recommend_fixes(cuda_ok, model_ok)
    
    print(f"\n🏁 Diagnostics Complete: {datetime.now()}")
    
    if cuda_ok and model_ok:
        print("✅ System appears healthy - the error may be intermittent or specific to certain conditions")
    else:
        print("❌ System issues detected - focus on system-level fixes rather than text chunking")

if __name__ == "__main__":
    main() 