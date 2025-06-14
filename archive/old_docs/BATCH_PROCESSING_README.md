# 🎵 ChatterBox Audiobook Batch Processing Feature

## Overview

The new batch processing feature allows you to upload multiple text files and process them sequentially into separate audiobook projects. This is perfect for processing multiple chapters overnight while you sleep!

## 🌟 Key Features

- **Multiple File Upload**: Upload all your chapter files at once
- **Sequential Processing**: Files process one after another automatically
- **Automatic Naming**: Projects are named with suffixes (-1, -2, -3, etc.)
- **Overnight Processing**: Queue up chapters and let them process unattended
- **Progress Tracking**: See which files succeed or fail
- **Memory Management**: GPU memory is cleared between chapters

## 📋 How to Use

### Step 1: Switch to Batch Mode
1. Open the "📖 Audiobook Creation - Single Sample" tab
2. In the upload section, select "Batch Processing" instead of "Single File"

### Step 2: Upload Your Files
1. Click "📚 Upload Multiple Text Files"
2. Select all your chapter files (e.g., chapter1.txt, chapter2.txt, chapter3.txt)
3. Click "📂 Load Batch Files" to analyze them

### Step 3: Configure Settings
1. Enter a **Project Name** (e.g., "my_audiobook")
2. Select your **Voice Profile**
3. Configure **Volume Normalization** settings if needed

### Step 4: Validate and Process
1. Click "🔍 Validate Batch" to check everything is ready
2. Click "🎵 Create Batch Audiobooks" to start processing

## 📁 Output Structure

If you upload 3 files with project name "my_book", you'll get:

```
audiobook_projects/
├── my_book-1/           # From chapter1.txt
│   ├── my_book-1_001.wav
│   ├── my_book-1_002.wav
│   └── ...
├── my_book-2/           # From chapter2.txt
│   ├── my_book-2_001.wav
│   ├── my_book-2_002.wav
│   └── ...
└── my_book-3/           # From chapter3.txt
    ├── my_book-3_001.wav
    ├── my_book-3_002.wav
    └── ...
```

## 🌙 Perfect for Overnight Processing

This feature is designed for scenarios like:

- **10-chapter audiobook**: Upload all chapters before bed
- **Multiple short stories**: Process an entire collection
- **Course materials**: Convert multiple lessons automatically
- **Podcast series**: Batch process multiple episodes

## ⚠️ Important Notes

1. **Processing Time**: Each chapter typically takes 1 hour to process
2. **GPU Performance**: Performance may degrade slightly over long sessions
3. **File Order**: Files are processed in the order you upload them
4. **Error Handling**: If one file fails, the others continue processing
5. **Memory Management**: GPU memory is automatically cleared between files

## 🛠️ Technical Implementation

The batch processing feature includes:

- `load_text_files_batch()`: Loads and validates multiple files
- `validate_batch_audiobook_input()`: Checks all requirements are met
- `create_batch_audiobook()`: Processes files sequentially
- Automatic project naming with suffixes
- Error handling and progress reporting
- Memory cleanup between files

## 📖 Example Workflow

```python
# 1. User uploads: [chapter1.txt, chapter2.txt, chapter3.txt]
# 2. System loads and validates all files
# 3. User sets project name: "fantasy_novel"
# 4. User selects voice: "epic_narrator"
# 5. System processes:
#    - fantasy_novel-1 (from chapter1.txt)
#    - fantasy_novel-2 (from chapter2.txt)  
#    - fantasy_novel-3 (from chapter3.txt)
```

## 🎯 Benefits

- **Time Saving**: Set up once, process all chapters
- **Consistency**: Same voice and settings for all chapters
- **Convenience**: No need to wake up every hour
- **Organization**: Automatic project naming keeps things organized
- **Reliability**: Continues processing even if one file fails

## 🔧 Files Modified

The batch processing feature was added to:
- `gradio_tts_app_audiobook_with_batch.py` - Main implementation
- `batch_audiobook_demo.py` - Demonstration interface

## 🚀 Getting Started

To try the batch processing feature:

1. Run `python batch_audiobook_demo.py` to see a demonstration
2. Use the main application with the new batch processing mode
3. Upload your chapter files and enjoy hands-free processing!

**Happy Audiobook Creating! 🎧📚** 