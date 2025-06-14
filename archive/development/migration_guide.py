#!/usr/bin/env python3
"""
Migration Guide for ChatterBox Audiobook Generator Refactoring

This script helps identify which functions moved where in the refactoring.
"""

# Function location mapping from old to new
MIGRATION_MAP = {
    # Configuration functions
    "load_config": "src.audiobook.config",
    "save_config": "src.audiobook.config", 
    "update_voice_library_path": "src.audiobook.config",
    
    # Model functions
    "load_model": "src.audiobook.models",
    "load_model_cpu": "src.audiobook.models",
    "set_seed": "src.audiobook.models",
    "generate": "src.audiobook.models",
    "generate_with_cpu_fallback": "src.audiobook.models",
    "generate_with_retry": "src.audiobook.models",
    "clear_gpu_memory": "src.audiobook.models",
    "check_gpu_memory": "src.audiobook.models",
    "force_cpu_processing": "src.audiobook.models",
    "get_model_device_str": "src.audiobook.models",
    
    # Text processing functions
    "chunk_text_by_sentences": "src.audiobook.text_processing",
    "adaptive_chunk_text": "src.audiobook.text_processing",
    "load_text_file": "src.audiobook.text_processing",
    "validate_audiobook_input": "src.audiobook.text_processing",
    "parse_multi_voice_text": "src.audiobook.text_processing",
    "clean_character_name_from_text": "src.audiobook.text_processing",
    "chunk_multi_voice_segments": "src.audiobook.text_processing",
    "validate_multi_voice_text": "src.audiobook.text_processing",
    "validate_multi_audiobook_input": "src.audiobook.text_processing",
    "analyze_multi_voice_text": "src.audiobook.text_processing",
    
    # Audio processing functions
    "save_audio_chunks": "src.audiobook.audio_processing",
    "combine_audio_files": "src.audiobook.audio_processing",
    "save_trimmed_audio": "src.audiobook.audio_processing",
    "extract_audio_segment": "src.audiobook.audio_processing",
    "handle_audio_trimming": "src.audiobook.audio_processing",
    "cleanup_temp_files": "src.audiobook.audio_processing",
    "analyze_audio_quality": "src.audiobook.audio_processing",
    "auto_remove_silence": "src.audiobook.audio_processing",
    
    # Voice management functions
    "ensure_voice_library_exists": "src.audiobook.voice_management",
    "get_voice_profiles": "src.audiobook.voice_management",
    "get_voice_choices": "src.audiobook.voice_management",
    "get_audiobook_voice_choices": "src.audiobook.voice_management",
    "get_voice_config": "src.audiobook.voice_management",
    "load_voice_for_tts": "src.audiobook.voice_management",
    "save_voice_profile": "src.audiobook.voice_management",
    "load_voice_profile": "src.audiobook.voice_management",
    "delete_voice_profile": "src.audiobook.voice_management",
    "refresh_voice_list": "src.audiobook.voice_management",
    "refresh_voice_choices": "src.audiobook.voice_management",
    "refresh_audiobook_voice_choices": "src.audiobook.voice_management",
    
    # Project management functions
    "save_project_metadata": "src.audiobook.project_management",
    "load_project_metadata": "src.audiobook.project_management",
    "get_existing_projects": "src.audiobook.project_management",
    "get_project_choices": "src.audiobook.project_management",
    "load_project_for_regeneration": "src.audiobook.project_management",
    "create_audiobook": "src.audiobook.project_management",
    "create_multi_voice_audiobook_with_assignments": "src.audiobook.project_management",
    "cleanup_project_temp_files": "src.audiobook.project_management",
    "get_project_chunks": "src.audiobook.project_management",
}

def find_function_location(function_name: str) -> str:
    """Find where a function moved to in the refactored structure.
    
    Args:
        function_name: Name of the function to locate
        
    Returns:
        str: Module location or "not found" message
    """
    location = MIGRATION_MAP.get(function_name)
    if location:
        return f"from {location} import {function_name}"
    else:
        return f"Function '{function_name}' not found in migration map"

def show_migration_help():
    """Display migration help information."""
    print("ChatterBox Audiobook Generator - Migration Guide")
    print("=" * 60)
    print()
    print("This tool helps you migrate from the monolithic version to the refactored version.")
    print()
    print("QUICK START:")
    print("- Old version: python gradio_tts_app_audiobook.py")
    print("- New version: python main.py")
    print()
    print("MODULE ORGANIZATION:")
    print("- Configuration: src.audiobook.config")
    print("- TTS Models: src.audiobook.models")
    print("- Text Processing: src.audiobook.text_processing")
    print("- Audio Operations: src.audiobook.audio_processing")
    print("- Voice Management: src.audiobook.voice_management")
    print("- Project Management: src.audiobook.project_management")
    print()
    print("EXAMPLES:")
    print("Old: from gradio_tts_app_audiobook import create_audiobook")
    print("New: from src.audiobook.project_management import create_audiobook")
    print()
    print("Old: from gradio_tts_app_audiobook import load_model")
    print("New: from src.audiobook.models import load_model")
    print()

def interactive_function_finder():
    """Interactive function finder."""
    print("INTERACTIVE FUNCTION FINDER")
    print("-" * 30)
    print("Enter function names to find their new location (or 'quit' to exit):")
    print()
    
    while True:
        function_name = input("Function name: ").strip()
        
        if function_name.lower() in ['quit', 'exit', 'q']:
            break
        
        if not function_name:
            continue
        
        location = find_function_location(function_name)
        print(f"  → {location}")
        print()

def main():
    """Main migration guide function."""
    show_migration_help()
    
    while True:
        print("\nOptions:")
        print("1. Find function location")
        print("2. Show all function mappings")
        print("3. Exit")
        
        choice = input("\nChoose an option (1-3): ").strip()
        
        if choice == "1":
            interactive_function_finder()
        elif choice == "2":
            print("\nALL FUNCTION MAPPINGS:")
            print("-" * 40)
            for func, module in sorted(MIGRATION_MAP.items()):
                print(f"{func:<35} → {module}")
        elif choice == "3":
            print("\nHappy coding with the refactored structure! 🚀")
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

if __name__ == "__main__":
    main() 