#!/usr/bin/env python3
"""
Quick test to check token calculation improvements
"""

def calculate_tokens(text):
    """Test our new token calculation logic"""
    text_length = len(text.split())
    estimated_tokens = max(text_length * 10, 80)  # Increased for better quality
    max_new_tokens = min(estimated_tokens, 800)  # Higher cap to avoid cutting off
    return text_length, max_new_tokens

# Test different text lengths
test_texts = [
    "Hello world",  # 2 words
    "The quick brown fox jumps over the lazy dog",  # 9 words  
    "This is a typical sentence that might be used in an audiobook chunk",  # 13 words
    "Here is a longer paragraph that contains multiple sentences and ideas. It should represent a more typical chunk size that would be processed by the TTS system in real audiobook generation scenarios.",  # 30 words
]

print("🔧 Token Calculation Test")
print("=" * 40)

for i, text in enumerate(test_texts, 1):
    words, tokens = calculate_tokens(text)
    print(f"Test {i}: {words} words → {tokens} max tokens")
    print(f"  Text: '{text[:50]}{'...' if len(text) > 50 else ''}'")
    print()

print("💡 Previous issue: 18 words × 6 = 108 tokens (too small)")
print("🎯 New calculation: 18 words × 10 = 180 tokens (better!)") 