# 🎵 Batch Processing UI Changes Required

## 📋 Current Status
- ✅ **Backend Functions Added**: All batch processing functions are implemented
- ❌ **UI Not Updated**: The interface still shows only single file upload

## 🔧 Required Changes

### 1. Replace File Upload Section (Around Line 3823)

**FIND THIS CODE:**
```python
with gr.Column(scale=1):
    # File upload
    text_file = gr.File(
        label="📄 Upload Text File",
        file_types=[".txt", ".md", ".rtf"],
        type="filepath"
    )
    
    load_file_btn = gr.Button(
        "📂 Load File", 
        size="sm",
        variant="secondary"
    )
    
    # File status
    file_status = gr.HTML(
        "<div class='file-status'>📄 No file loaded</div>"
    )
```

**REPLACE WITH:**
```python
with gr.Column(scale=1):
    # Upload Mode Selection
    upload_mode = gr.Radio(
        choices=[("Single File", "single"), ("Batch Processing", "batch")],
        value="single",
        label="📋 Upload Mode",
        info="Single file for one audiobook, or batch for multiple chapters"
    )
    
    # Single file upload (default visible)
    with gr.Group(visible=True) as single_upload_group:
        text_file = gr.File(
            label="📄 Upload Text File",
            file_types=[".txt", ".md", ".rtf"],
            type="filepath"
        )
        
        load_file_btn = gr.Button(
            "📂 Load File", 
            size="sm",
            variant="secondary"
        )
        
        # File status
        file_status = gr.HTML(
            "<div class='file-status'>📄 No file loaded</div>"
        )
    
    # Batch file upload (hidden by default)
    with gr.Group(visible=False) as batch_upload_group:
        batch_files = gr.File(
            label="📚 Upload Multiple Text Files",
            file_types=[".txt", ".md", ".rtf"],
            file_count="multiple",
            type="filepath",
            info="Upload chapter files in order (e.g., chapter1.txt, chapter2.txt, etc.)"
        )
        
        load_batch_btn = gr.Button(
            "📂 Load Batch Files", 
            size="sm",
            variant="secondary"
        )
        
        # Batch file status
        batch_status = gr.HTML(
            "<div class='file-status'>📚 No batch files loaded</div>"
        )
    
    # State for batch processing
    batch_file_list = gr.State([])
```

### 2. Add Batch Processing Buttons (Around Line 4130)

**FIND THIS CODE:**
```python
with gr.Row():
    validate_btn = gr.Button(
        "🔍 Validate Input", 
        variant="secondary",
        size="lg"
    )
    
    process_btn = gr.Button(
        "🎵 Create Audiobook", 
        variant="primary",
        size="lg",
        interactive=False
    )
```

**REPLACE WITH:**
```python
with gr.Row():
    validate_btn = gr.Button(
        "🔍 Validate Input", 
        variant="secondary",
        size="lg"
    )
    
    process_btn = gr.Button(
        "🎵 Create Audiobook", 
        variant="primary",
        size="lg",
        interactive=False
    )

# Batch processing buttons (visible when batch mode is selected)
with gr.Group(visible=False) as batch_processing_group:
    with gr.Row():
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
```

### 3. Add Event Handlers (After existing event handlers)

**ADD THIS CODE:**
```python
# Batch processing event handlers
def toggle_upload_mode(mode):
    if mode == "single":
        return (
            gr.Group(visible=True),   # single_upload_group
            gr.Group(visible=False),  # batch_upload_group
            gr.Group(visible=True),   # normal processing buttons
            gr.Group(visible=False)   # batch_processing_group
        )
    else:
        return (
            gr.Group(visible=False),  # single_upload_group
            gr.Group(visible=True),   # batch_upload_group
            gr.Group(visible=False),  # normal processing buttons
            gr.Group(visible=True)    # batch_processing_group
        )

upload_mode.change(
    fn=toggle_upload_mode,
    inputs=[upload_mode],
    outputs=[single_upload_group, batch_upload_group, gr.Group(), batch_processing_group]
)

load_batch_btn.click(
    fn=load_text_files_batch,
    inputs=[batch_files],
    outputs=[batch_file_list, batch_status]
)

validate_batch_btn.click(
    fn=validate_batch_audiobook_input,
    inputs=[batch_file_list, audiobook_voice_selector, project_name],
    outputs=[process_batch_btn, audiobook_status, gr.State()]
)

process_batch_btn.click(
    fn=create_batch_audiobook,
    inputs=[
        model_state, 
        batch_file_list, 
        voice_library_path_state, 
        audiobook_voice_selector, 
        project_name, 
        enable_volume_norm, 
        target_volume_level
    ],
    outputs=[audiobook_output, audiobook_status]
)
```

## 🎯 What This Will Add

1. **Upload Mode Toggle**: Radio buttons to switch between single and batch mode
2. **Multiple File Upload**: When in batch mode, users can upload multiple files at once
3. **Batch Processing Buttons**: Separate validation and processing buttons for batch mode
4. **Sequential Processing**: Files will be processed one after another with names like:
   - `my_book-1` (from first file)
   - `my_book-2` (from second file)
   - `my_book-3` (from third file)

## 🚀 Result

After these changes, users will see:
- A toggle to switch between "Single File" and "Batch Processing"
- In batch mode: ability to upload multiple files and process them overnight
- Automatic project naming with suffixes
- Perfect for queuing up chapters before bed!

## 📁 Demo Available

Run `python simple_batch_demo.py` to see exactly how it should look and work. 