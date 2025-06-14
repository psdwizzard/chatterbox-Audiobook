# ChatterBox Audiobook Generator - Refactored

This is the refactored version of the ChatterBox Audiobook Generator, now organized into a clean, modular structure that's much easier to maintain and extend.

## 🏗️ Project Structure

The codebase has been reorganized from a single 5,400+ line file into a modular architecture:

```
├── src/
│   └── audiobook/
│       ├── __init__.py           # Package initialization
│       ├── config.py             # Configuration management
│       ├── models.py             # TTS model handling
│       ├── text_processing.py    # Text chunking and validation
│       ├── audio_processing.py   # Audio operations
│       ├── voice_management.py   # Voice profile CRUD
│       └── project_management.py # Project lifecycle
├── main.py                       # Main entry point
├── gradio_tts_app_audiobook.py  # Original monolithic file (for reference)
└── README_REFACTORED.md         # This file
```

## 📦 Module Overview

### `config.py`
- Configuration loading and saving
- Voice library path management
- Application settings

### `models.py`
- TTS model loading (GPU/CPU)
- Audio generation with fallback mechanisms
- Memory management and error handling
- Random seed management

### `text_processing.py`
- Text chunking by sentences
- Input validation
- Multi-voice text parsing
- Character extraction and analysis

### `audio_processing.py`
- Audio file saving and combining
- Audio trimming and segment extraction
- Quality analysis
- Temporary file cleanup

### `voice_management.py`
- Voice profile CRUD operations
- Voice library scanning
- Voice configuration management
- UI dropdown population

### `project_management.py`
- Project creation and metadata handling
- Single and multi-voice audiobook generation
- Project loading and resumption
- File organization and cleanup

### `main.py`
- Application entry point
- Gradio interface creation
- Event handler coordination
- Module integration

## 🚀 Getting Started

### Running the Refactored Version

1. **Use the new main entry point:**
   ```bash
   python main.py
   ```

2. **Or run the original monolithic version:**
   ```bash
   python gradio_tts_app_audiobook.py
   ```

Both versions provide the same functionality, but the refactored version is much more maintainable.

## ✨ Benefits of the Refactored Structure

### 1. **Separation of Concerns**
- Each module has a single, clear responsibility
- Easier to understand and modify specific functionality
- Reduced coupling between components

### 2. **Better Code Organization**
- Related functions grouped together
- Clear import structure
- Logical file hierarchy

### 3. **Improved Maintainability**
- Easier to locate and fix bugs
- Simpler to add new features
- Better code reusability

### 4. **Enhanced Testability**
- Individual modules can be tested in isolation
- Clear interfaces between components
- Easier to mock dependencies

### 5. **Developer Experience**
- Much easier to navigate the codebase
- Clear module boundaries
- Better IDE support and code completion

## 🔧 Development Guidelines

### Adding New Features

1. **Identify the appropriate module** based on functionality
2. **Add new functions** following the existing patterns
3. **Update imports** in `main.py` if needed
4. **Add proper type hints** and docstrings
5. **Test thoroughly** before committing

### Code Standards

- Follow PEP 8 style guidelines
- Use type hints for all function parameters and returns
- Write comprehensive docstrings
- Use snake_case for variables and functions
- Use PascalCase for classes

### Module Guidelines

- Keep modules focused on their specific domain
- Avoid circular imports
- Use relative imports within the package
- Export only necessary functions in `__init__.py`

## 🔄 Migration Path

If you have existing code that imports from the monolithic file:

**Old:**
```python
from gradio_tts_app_audiobook import create_audiobook, load_model
```

**New:**
```python
from src.audiobook.project_management import create_audiobook
from src.audiobook.models import load_model
```

## 🧪 Testing

The modular structure makes testing much easier:

```python
# Test individual modules
from src.audiobook.text_processing import chunk_text_by_sentences

def test_text_chunking():
    text = "This is a test. Another sentence here."
    chunks = chunk_text_by_sentences(text, max_words=5)
    assert len(chunks) == 2
```

## 🤝 Contributing

With this new structure, contributing is much more straightforward:

1. **Pick a module** that needs enhancement
2. **Make focused changes** within that module
3. **Test your changes** thoroughly
4. **Update documentation** as needed

## 📈 Performance

The refactored version maintains the same performance characteristics while providing:
- Better memory management through modular loading
- Cleaner error handling and recovery
- More efficient development workflow

## 🔮 Future Enhancements

The modular structure makes it easier to add:
- New TTS engines
- Additional audio formats
- Advanced text processing features
- Different UI frameworks
- API endpoints
- Batch processing capabilities

---

This refactored structure transforms the project from a monolithic application into a maintainable, extensible codebase that follows Python best practices and modern software development principles. 