#!/usr/bin/env python3
"""
Emergency fix script to restore broken functions in gradio_tts_app_audiobook.py
This specifically fixes the 6-dropdown refresh issue and syntax errors.
"""

def emergency_fix():
    """Apply emergency fixes to the main file"""
    
    print("🚨 EMERGENCY FIX: Restoring broken functions...")
    
    # The fixed function definitions
    fixed_functions = '''
def force_refresh_all_project_dropdowns():
    """Force refresh all project dropdowns to ensure new projects appear"""
    try:
        # Clear any potential caches and get fresh project list
        projects = get_existing_projects()
        choices = get_project_choices()
        # Return the same choices for all SIX dropdowns that need updating
        return (
            gr.Dropdown(choices=choices, value=None),  # previous_project_dropdown
            gr.Dropdown(choices=choices, value=None),  # multi_previous_project_dropdown
            gr.Dropdown(choices=choices, value=None),  # project_dropdown
            gr.Dropdown(choices=choices, value=None),  # single_project_dropdown
            gr.Dropdown(choices=choices, value=None),  # clean_project_dropdown
            gr.Dropdown(choices=choices, value=None)   # listen_project_dropdown
        )
    except Exception as e:
        print(f"Error refreshing project dropdowns: {str(e)}")
        error_choices = [("Error loading projects", None)]
        return (
            gr.Dropdown(choices=error_choices, value=None),
            gr.Dropdown(choices=error_choices, value=None),
            gr.Dropdown(choices=error_choices, value=None),
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

def get_project_dir(project_name: str) -> str:
    """Get the directory path for a project"""
    if not project_name:
        return None
    return os.path.join("audiobook_projects", project_name)

def remove_silence_from_audio(audio_data, sample_rate, silence_threshold=-50.0, min_silence_duration=0.5):
    """Remove silence from audio data using simple amplitude thresholding"""
    try:
        # Simple silence removal without librosa dependency
        # Convert dB threshold to amplitude (0-1 scale)
        silence_threshold_amplitude = 10 ** (silence_threshold / 20)
        
        # Find non-silent regions
        non_silent_mask = np.abs(audio_data) > silence_threshold_amplitude
        
        # Apply basic trimming - remove silence from start and end
        if np.any(non_silent_mask):
            start_idx = np.argmax(non_silent_mask)
            end_idx = len(audio_data) - np.argmax(non_silent_mask[::-1])
            trimmed_audio = audio_data[start_idx:end_idx]
            return trimmed_audio
        else:
            # If everything is considered silent, return original
            return audio_data
            
    except Exception as e:
        print(f"Warning: Could not remove silence: {str(e)}")
        return audio_data  # Return original audio if processing fails

'''

    # Read the current file
    try:
        with open('gradio_tts_app_audiobook.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the start of the corrupted section
        start_marker = "def force_refresh_all_project_dropdowns():"
        start_pos = content.find(start_marker)
        
        if start_pos == -1:
            print("❌ Could not find the target function to replace")
            return False
        
        # Find the next function after the corrupted section
        end_marker = "def load_project_for_regeneration(project_name: str) -> tuple:"
        end_pos = content.find(end_marker, start_pos)
        
        if end_pos == -1:
            print("❌ Could not find the end of corrupted section")
            return False
        
        # Replace the corrupted section with fixed functions
        new_content = content[:start_pos] + fixed_functions + content[end_pos:]
        
        # Write the fixed content
        with open('gradio_tts_app_audiobook.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print("✅ Emergency fix applied successfully!")
        print("📋 Fixed issues:")
        print("   - force_refresh_all_project_dropdowns() now returns 6 dropdowns")
        print("   - Removed syntax errors in function definitions") 
        print("   - Added missing helper functions get_project_dir() and remove_silence_from_audio()")
        print("   - All project dropdowns should now refresh correctly when creating new audiobooks")
        
        return True
        
    except Exception as e:
        print(f"❌ Emergency fix failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = emergency_fix()
    if not success:
        print("\n💡 MANUAL STEPS:")
        print("1. Backup your current file")
        print("2. Copy from archive/gradio_tts_app_audiobook_backup_current.py")
        print("3. Apply the 6-dropdown fix manually") 