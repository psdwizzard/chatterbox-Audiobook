"""
Main entry point for the ChatterBox Audiobook Generator.

This module brings together all the components and launches the Gradio interface.
"""

import gradio as gr
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.audiobook.config import load_config, save_config, update_voice_library_path
from src.audiobook.models import load_model, load_model_cpu, set_seed, generate
from src.audiobook.text_processing import (
    load_text_file, validate_audiobook_input, validate_multi_audiobook_input,
    analyze_multi_voice_text, chunk_text_by_sentences
)
from src.audiobook.audio_processing import save_audio_chunks, combine_audio_files
from src.audiobook.voice_management import (
    get_voice_choices, get_audiobook_voice_choices, save_voice_profile,
    load_voice_profile, delete_voice_profile, refresh_voice_choices
)
from src.audiobook.project_management import (
    create_audiobook, create_multi_voice_audiobook_with_assignments,
    get_existing_projects, get_project_choices, load_project_for_regeneration,
    cleanup_project_temp_files, auto_clean_project_audio, analyze_project_audio_quality
)


def create_gradio_interface():
    """Create and configure the main Gradio interface.
    
    Returns:
        gr.Interface: Configured Gradio interface
    """
    # Load initial configuration
    voice_library_path = load_config()
    
    # Initialize model
    print("Loading TTS model...")
    model = load_model()
    print("Model loaded successfully!")
    
    with gr.Blocks(title="ChatterBox Audiobook Generator", theme=gr.themes.Soft()) as interface:
        
        # Header
        gr.Markdown("# 🎙️ ChatterBox Audiobook Generator")
        gr.Markdown("Generate high-quality audiobooks with single or multiple voices")
        
        # Configuration section
        with gr.Tab("⚙️ Configuration"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Voice Library Settings")
                    voice_lib_path = gr.Textbox(
                        label="Voice Library Path",
                        value=voice_library_path,
                        placeholder="Path to voice library directory"
                    )
                    update_config_btn = gr.Button("Update Configuration", variant="primary")
                    config_status = gr.Textbox(label="Status", interactive=False)
                
                with gr.Column():
                    gr.Markdown("### System Information")
                    gr.Markdown("Model loaded and ready for generation")
                    gr.Markdown("Check the other tabs to create audiobooks or manage voices")
        
        # Voice Management section
        with gr.Tab("🎭 Voice Management"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Add New Voice")
                    voice_name = gr.Textbox(label="Voice Name", placeholder="Enter unique voice name")
                    display_name = gr.Textbox(label="Display Name", placeholder="Friendly display name")
                    description = gr.Textbox(label="Description", placeholder="Voice description")
                    audio_file = gr.Audio(label="Voice Sample", type="filepath")
                    
                    with gr.Row():
                        exaggeration = gr.Slider(0.5, 2.0, value=1.0, label="Exaggeration")
                        cfg_weight = gr.Slider(0.1, 2.0, value=1.0, label="CFG Weight")
                        temperature = gr.Slider(0.1, 1.0, value=0.7, label="Temperature")
                    
                    save_voice_btn = gr.Button("Save Voice Profile", variant="primary")
                    save_voice_status = gr.Textbox(label="Status", interactive=False)
                
                with gr.Column():
                    gr.Markdown("### Manage Existing Voices")
                    voice_dropdown = gr.Dropdown(
                        label="Select Voice",
                        choices=get_voice_choices(voice_library_path),
                        value=None
                    )
                    refresh_voices_btn = gr.Button("Refresh Voice List")
                    
                    load_voice_btn = gr.Button("Load Voice for Editing")
                    delete_voice_btn = gr.Button("Delete Voice", variant="stop")
                    voice_action_status = gr.Textbox(label="Status", interactive=False)
        
        # Single Voice Audiobook section
        with gr.Tab("📖 Single Voice Audiobook"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Input")
                    text_input = gr.Textbox(
                        label="Text Content",
                        lines=10,
                        placeholder="Enter your text or upload a file..."
                    )
                    text_file = gr.File(label="Or Upload Text File", file_types=[".txt"])
                    
                    voice_selection = gr.Dropdown(
                        label="Select Voice",
                        choices=get_audiobook_voice_choices(voice_library_path),
                        value=None
                    )
                    project_name_input = gr.Textbox(
                        label="Project Name",
                        placeholder="Enter project name"
                    )
                    
                with gr.Column():
                    gr.Markdown("### Generation")
                    create_audiobook_btn = gr.Button("Create Audiobook", variant="primary", size="lg")
                    audiobook_status = gr.Textbox(label="Status", interactive=False)
                    audiobook_progress = gr.Textbox(label="Progress", interactive=False)
        
        # Multi-Voice Audiobook section
        with gr.Tab("🎭 Multi-Voice Audiobook"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Multi-Voice Text Input")
                    gr.Markdown("Format: `[CHARACTER_NAME]: dialogue text`")
                    multi_text_input = gr.Textbox(
                        label="Multi-Voice Text",
                        lines=10,
                        placeholder="[Alice]: Hello there!\n[Bob]: Hi Alice, how are you?"
                    )
                    multi_text_file = gr.File(label="Or Upload Multi-Voice Text File", file_types=[".txt"])
                    
                    analyze_btn = gr.Button("Analyze Text")
                    analysis_output = gr.Textbox(label="Analysis Results", interactive=False)
                
                with gr.Column():
                    gr.Markdown("### Character Voice Assignment")
                    multi_project_name = gr.Textbox(
                        label="Project Name",
                        placeholder="Enter multi-voice project name"
                    )
                    
                    # Character assignment dropdowns (will be populated dynamically)
                    char_assignments = []
                    for i in range(6):  # Support up to 6 characters
                        with gr.Row(visible=False) as char_row:
                            char_label = gr.Markdown(f"Character {i+1}:")
                            char_voice = gr.Dropdown(
                                label=f"Voice for Character {i+1}",
                                choices=get_voice_choices(voice_library_path),
                                value=None
                            )
                        char_assignments.append((char_row, char_label, char_voice))
                    
                    create_multi_btn = gr.Button("Create Multi-Voice Audiobook", variant="primary")
                    multi_status = gr.Textbox(label="Status", interactive=False)
        
        # Project Management section
        with gr.Tab("📁 Project Management"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Existing Projects")
                    project_dropdown = gr.Dropdown(
                        label="Select Project",
                        choices=get_project_choices(),
                        value=None
                    )
                    refresh_projects_btn = gr.Button("Refresh Project List")
                    
                    load_project_btn = gr.Button("Load Project Details")
                    project_details = gr.Textbox(label="Project Details", interactive=False, lines=5)
                
                with gr.Column():
                    gr.Markdown("### Project Actions")
                    cleanup_btn = gr.Button("Cleanup Temp Files")
                    cleanup_status = gr.Textbox(label="Cleanup Status", interactive=False)
                    
                    gr.Markdown("### Audio Processing")
                    with gr.Row():
                        silence_threshold = gr.Slider(
                            minimum=-60,
                            maximum=-20,
                            value=-50,
                            step=5,
                            label="Silence Threshold (dB)"
                        )
                        min_silence_duration = gr.Slider(
                            minimum=0.1,
                            maximum=2.0,
                            value=0.5,
                            step=0.1,
                            label="Min Silence Duration (s)"
                        )
                    
                    auto_clean_btn = gr.Button("Auto-Clean Project Audio", variant="primary")
                    analyze_quality_btn = gr.Button("Analyze Audio Quality")
                    audio_processing_status = gr.Textbox(label="Audio Processing Status", interactive=False, lines=3)
                    
                    gr.Markdown("### Export Options")
                    export_format = gr.Radio(["WAV", "MP3"], label="Export Format", value="WAV")
                    combine_btn = gr.Button("Combine All Chunks")
                    export_status = gr.Textbox(label="Export Status", interactive=False)
        
        # Event handlers
        def update_config_handler(new_path):
            return update_voice_library_path(new_path)
        
        def load_text_handler(file_obj):
            if file_obj is None:
                return "", ""
            content, status = load_text_file(file_obj.name)
            return content, status
        
        def save_voice_handler(name, display, desc, audio, exag, cfg, temp):
            return save_voice_profile(voice_library_path, name, display, desc, audio, exag, cfg, temp)
        
        def refresh_voices_handler():
            return gr.Dropdown(choices=get_voice_choices(voice_library_path))
        
        def create_audiobook_handler(text, voice, project_name):
            is_valid, error = validate_audiobook_input(text, voice, project_name)
            if not is_valid:
                return error, ""
            
            status, files, project_path = create_audiobook(
                model, text, voice_library_path, voice, project_name
            )
            return status, f"Generated {len(files)} audio files"
        
        def analyze_multi_text_handler(text):
            is_valid, message, char_counts = analyze_multi_voice_text(text, voice_library_path)
            return message
        
        def cleanup_project_handler(project_name):
            return cleanup_project_temp_files(project_name)
        
        def auto_clean_project_handler(project_name, threshold, min_duration):
            return auto_clean_project_audio(project_name, threshold, min_duration)
        
        def analyze_quality_handler(project_name):
            return analyze_project_audio_quality(project_name)
        
        # Wire up event handlers
        update_config_btn.click(
            update_config_handler,
            inputs=[voice_lib_path],
            outputs=[config_status]
        )
        
        text_file.upload(
            load_text_handler,
            inputs=[text_file],
            outputs=[text_input, audiobook_status]
        )
        
        save_voice_btn.click(
            save_voice_handler,
            inputs=[voice_name, display_name, description, audio_file, exaggeration, cfg_weight, temperature],
            outputs=[save_voice_status]
        )
        
        refresh_voices_btn.click(
            refresh_voices_handler,
            outputs=[voice_dropdown]
        )
        
        create_audiobook_btn.click(
            create_audiobook_handler,
            inputs=[text_input, voice_selection, project_name_input],
            outputs=[audiobook_status, audiobook_progress]
        )
        
        analyze_btn.click(
            analyze_multi_text_handler,
            inputs=[multi_text_input],
            outputs=[analysis_output]
        )
        
        cleanup_btn.click(
            cleanup_project_handler,
            inputs=[project_dropdown],
            outputs=[cleanup_status]
        )
        
        auto_clean_btn.click(
            auto_clean_project_handler,
            inputs=[project_dropdown, silence_threshold, min_silence_duration],
            outputs=[audio_processing_status]
        )
        
        analyze_quality_btn.click(
            analyze_quality_handler,
            inputs=[project_dropdown],
            outputs=[audio_processing_status]
        )
    
    return interface


def main():
    """Main function to launch the application."""
    print("🎙️ Starting ChatterBox Audiobook Generator...")
    
    # Create and launch interface
    interface = create_gradio_interface()
    
    # Launch with basic configuration (compatible with most Gradio versions)
    interface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )


if __name__ == "__main__":
    main() 