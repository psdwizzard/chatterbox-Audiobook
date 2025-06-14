"""
Simple Batch Processing UI Demo for ChatterBox Audiobook

This file shows exactly what needs to be added to the main interface
to enable the batch processing functionality.
"""

import gradio as gr

# Simulated functions (these already exist in your main file)
def load_text_files_batch(file_paths):
    if not file_paths:
        return [], "No files uploaded"
    return [{"filename": f"file_{i}.txt", "content": "sample", "words": 100} for i in range(len(file_paths))], f"Loaded {len(file_paths)} files"

def validate_batch_audiobook_input(file_list, voice, project_name):
    if not file_list:
        return gr.Button(interactive=False), "❌ No files loaded", None
    if not voice:
        return gr.Button(interactive=False), "❌ Select a voice", None  
    if not project_name:
        return gr.Button(interactive=False), "❌ Enter project name", None
    return gr.Button(interactive=True), f"✅ Ready to process {len(file_list)} files", None

def create_batch_audiobook(model, file_list, voice_lib, voice, project_name, norm, level):
    return None, f"✅ Batch processing complete! Created {len(file_list)} audiobooks with names {project_name}-1, {project_name}-2, etc."

def demo_interface():
    with gr.Blocks(title="Batch Processing Demo") as demo:
        gr.HTML("""
        <h1>🎵 Batch Processing Demo</h1>
        <p>This shows the UI components that need to be added to your main interface.</p>
        """)
        
        with gr.Row():
            with gr.Column():
                # Upload Mode Selection
                upload_mode = gr.Radio(
                    choices=[("Single File", "single"), ("Batch Processing", "batch")],
                    value="single",
                    label="📋 Upload Mode",
                    info="Switch between single file and batch processing"
                )
                
                # Single file upload (visible by default)
                with gr.Group(visible=True) as single_group:
                    single_file = gr.File(
                        label="📄 Upload Single Text File",
                        file_types=[".txt"],
                        type="filepath"
                    )
                    single_status = gr.HTML("📄 Single file mode")
                
                # Batch file upload (hidden by default)  
                with gr.Group(visible=False) as batch_group:
                    batch_files = gr.File(
                        label="📚 Upload Multiple Text Files",
                        file_types=[".txt"],
                        file_count="multiple",
                        type="filepath"
                    )
                    load_batch_btn = gr.Button("📂 Load Batch Files")
                    batch_status = gr.HTML("📚 Batch processing mode")
                
                # Voice and project settings
                voice_dropdown = gr.Dropdown(
                    choices=["Voice 1", "Voice 2", "Voice 3"],
                    label="Select Voice",
                    value=None
                )
                
                project_name = gr.Textbox(
                    label="Project Name",
                    placeholder="my_audiobook"
                )
                
                # Batch file list state
                batch_file_list = gr.State([])
                
            with gr.Column():
                # Processing buttons
                validate_batch_btn = gr.Button("🔍 Validate Batch", variant="secondary")
                process_batch_btn = gr.Button("🎵 Create Batch Audiobooks", variant="primary", interactive=False)
                
                # Status and output
                processing_status = gr.HTML("Ready for batch processing")
                output_audio = gr.Audio(label="Preview (last created audiobook)", visible=False)
        
        # Event handlers
        def toggle_upload_mode(mode):
            if mode == "single":
                return gr.Group(visible=True), gr.Group(visible=False)
            else:
                return gr.Group(visible=False), gr.Group(visible=True)
        
        upload_mode.change(
            fn=toggle_upload_mode,
            inputs=[upload_mode],
            outputs=[single_group, batch_group]
        )
        
        load_batch_btn.click(
            fn=load_text_files_batch,
            inputs=[batch_files],
            outputs=[batch_file_list, batch_status]
        )
        
        validate_batch_btn.click(
            fn=validate_batch_audiobook_input,
            inputs=[batch_file_list, voice_dropdown, project_name],
            outputs=[process_batch_btn, processing_status, gr.State()]
        )
        
        process_batch_btn.click(
            fn=create_batch_audiobook,
            inputs=[gr.State(None), batch_file_list, gr.State(""), voice_dropdown, project_name, gr.State(True), gr.State(-18)],
            outputs=[output_audio, processing_status]
        )
        
        gr.HTML("""
        <div style="margin-top: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px;">
            <h3>📋 To Add This to Your Main Interface:</h3>
            <ol>
                <li>Replace the simple file upload section with the Upload Mode selection</li>
                <li>Add the single and batch upload groups</li>
                <li>Add the batch processing buttons</li>
                <li>Wire up the event handlers</li>
                <li>Add the batch_file_list State component</li>
            </ol>
            <p><strong>Key Components Needed:</strong></p>
            <ul>
                <li>upload_mode (Radio)</li>
                <li>single_upload_group and batch_upload_group (Group)</li>
                <li>batch_files (File with file_count="multiple")</li>
                <li>load_batch_btn (Button)</li>
                <li>validate_batch_btn and process_batch_btn (Buttons)</li>
                <li>batch_file_list (State)</li>
            </ul>
        </div>
        """)
    
    return demo

if __name__ == "__main__":
    demo = demo_interface()
    demo.launch() 