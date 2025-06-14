"""
ChatterBox Audiobook Batch Processing Demo

This file demonstrates the new batch processing functionality for creating multiple 
audiobooks from a queue of text files automatically.

Key Features:
- Upload multiple text files at once
- Sequential processing (one finishes, next starts automatically)
- Automatic project naming with suffixes (-1, -2, -3, etc.)
- Perfect for overnight batch processing of audiobook chapters

Usage Example:
1. Set upload mode to "Batch Processing"
2. Upload your chapter files (chapter1.txt, chapter2.txt, etc.)
3. Set your base project name (e.g., "my_book")
4. Select your voice profile
5. Click "Create Batch Audiobooks"

The system will automatically create:
- my_book-1 (from chapter1.txt)
- my_book-2 (from chapter2.txt)  
- my_book-3 (from chapter3.txt)
- etc.

Each will be saved as a separate project in the audiobook_projects directory.
"""

import gradio as gr
import os
from typing import List, Tuple

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
            # Read each file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if content:
                loaded_files.append({
                    'content': content,
                    'filename': os.path.basename(file_path),
                    'words': len(content.split())
                })
                total_words += len(content.split())
            else:
                return [], f"❌ File {i+1} is empty: {os.path.basename(file_path)}"
                
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

def simulate_batch_processing(file_list: list, project_name: str, selected_voice: str) -> tuple:
    """
    Simulate batch processing for demonstration purposes.
    
    In the real implementation, this would call create_audiobook_with_volume_settings
    for each file in sequence.
    """
    if not file_list:
        return None, "❌ No files to process"
    
    successful_projects = []
    
    # Simulate processing each file
    for i, file_info in enumerate(file_list, 1):
        current_project_name = f"{project_name}-{i}"
        successful_projects.append({
            'name': current_project_name,
            'filename': file_info['filename'],
            'words': file_info['words']
        })
    
    # Generate status message
    status_parts = [f"✅ Would create {len(successful_projects)} audiobooks:"]
    for proj in successful_projects:
        status_parts.append(f"  • {proj['name']} ({proj['filename']}, {proj['words']} words)")
    
    status_parts.append(f"\n📁 Projects would be saved in audiobook_projects/")
    status_parts.append(f"🎧 Each project would contain individual audio chunks")
    
    final_status = "\n".join(status_parts)
    
    # Return a dummy audio tuple for demonstration
    return (22050, [0] * 1000), final_status

# Example interface showing how batch processing would work
def create_batch_demo_interface():
    """Create a demo interface showing batch processing functionality."""
    
    with gr.Blocks(title="Batch Audiobook Processing Demo") as demo:
        gr.HTML("""
        <div style="text-align: center; margin: 20px;">
            <h1>🎵 ChatterBox Batch Audiobook Processing Demo</h1>
            <p>Upload multiple text files and process them sequentially into separate audiobook projects</p>
        </div>
        """)
        
        with gr.Row():
            with gr.Column(scale=2):
                # Upload Mode Selection
                upload_mode = gr.Radio(
                    choices=[("Single File", "single"), ("Batch Processing", "batch")],
                    value="batch",
                    label="📋 Upload Mode",
                    info="Single file for one audiobook, or batch for multiple chapters"
                )
                
                # Batch file upload
                batch_files = gr.File(
                    label="📚 Upload Multiple Text Files",
                    file_types=[".txt", ".md", ".rtf"],
                    file_count="multiple",
                    type="filepath",
                    info="Upload chapter files in order (e.g., chapter1.txt, chapter2.txt, etc.)"
                )
                
                load_batch_btn = gr.Button(
                    "📂 Load Batch Files", 
                    size="lg",
                    variant="secondary"
                )
                
                # Batch file status
                batch_status = gr.HTML(
                    "<div style='padding: 10px; border: 1px solid #ddd; border-radius: 5px;'>📚 No batch files loaded</div>"
                )
                
                # State for batch processing
                batch_file_list = gr.State([])
                
            with gr.Column(scale=1):
                # Project Settings
                gr.HTML("<h3>📁 Project Settings</h3>")
                
                project_name = gr.Textbox(
                    label="Project Name (Base)",
                    placeholder="e.g., my_audiobook",
                    info="Files will be named: my_audiobook-1, my_audiobook-2, etc."
                )
                
                # Voice Selection (simulated)
                voice_selector = gr.Dropdown(
                    choices=["narrator_voice", "character_voice", "storyteller_voice"],
                    label="Select Voice",
                    value="narrator_voice",
                    info="Choose your voice profile"
                )
                
                # Validation and Processing
                validate_batch_btn = gr.Button(
                    "🔍 Validate Batch", 
                    variant="secondary",
                    size="lg"
                )
                
                process_batch_btn = gr.Button(
                    "🎵 Create Batch Audiobooks", 
                    variant="primary",
                    size="lg",
                    interactive=False
                )
        
        # Results Section
        with gr.Row():
            with gr.Column():
                batch_processing_status = gr.HTML(
                    "<div style='padding: 10px; border: 1px solid #ddd; border-radius: 5px;'>📋 Ready for batch processing</div>"
                )
                
                batch_output_audio = gr.Audio(
                    label="Sample Output (Last Processed File)",
                    visible=False
                )
        
        # Instructions
        gr.HTML("""
        <div style="background: #f5f5f5; padding: 20px; border-radius: 5px; margin: 20px 0;">
            <h4>📋 How Batch Processing Works:</h4>
            <ol>
                <li><strong>Upload Files:</strong> Select multiple .txt files (your chapters)</li>
                <li><strong>Load Batch:</strong> Click "Load Batch Files" to analyze them</li>
                <li><strong>Set Project Name:</strong> Enter a base name (e.g., "my_book")</li>
                <li><strong>Select Voice:</strong> Choose your voice profile</li>
                <li><strong>Validate:</strong> Check that everything is ready</li>
                <li><strong>Process:</strong> Start batch creation - runs automatically!</li>
            </ol>
            <p><strong>🎯 Example Output:</strong></p>
            <ul>
                <li>my_book-1/ (from first file)</li>
                <li>my_book-2/ (from second file)</li>
                <li>my_book-3/ (from third file)</li>
            </ul>
            <p><strong>🌙 Perfect for overnight processing!</strong> Queue up all your chapters and let them process while you sleep.</p>
        </div>
        """)
        
        # Event handlers
        load_batch_btn.click(
            fn=load_text_files_batch,
            inputs=batch_files,
            outputs=[batch_file_list, batch_status]
        )
        
        validate_batch_btn.click(
            fn=validate_batch_audiobook_input,
            inputs=[batch_file_list, voice_selector, project_name],
            outputs=[process_batch_btn, batch_processing_status, batch_output_audio]
        )
        
        process_batch_btn.click(
            fn=simulate_batch_processing,
            inputs=[batch_file_list, project_name, voice_selector],
            outputs=[batch_output_audio, batch_processing_status]
        ).then(
            fn=lambda: gr.Audio(visible=True),
            outputs=batch_output_audio
        )
    
    return demo

if __name__ == "__main__":
    demo = create_batch_demo_interface()
    demo.launch(debug=True) 