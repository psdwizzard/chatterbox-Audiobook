#!/usr/bin/env python3
"""Quick fix for syntax errors"""

# Read the current file
with open('gradio_tts_app_audiobook.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix the specific issues
fixed_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Skip the empty function definition at line 2021 (index 2020)
    if i == 2020 and line.strip() == "def force_refresh_single_project_dropdown():":
        i += 1  # Skip this empty definition
        continue
    
    # Fix the broken get_project_choices function at around line 2030
    if "def get_project_choices() -> list:" in line:
        fixed_lines.append(line)  # Keep the function definition
        i += 1
        # Add the missing try block and complete function
        fixed_lines.extend([
            '    """Get project choices for dropdown - always fresh data"""\n',
            '    try:\n',
            '        projects = get_existing_projects()  # This should always get fresh data\n',
            '        if not projects:\n',
            '            return [("No projects found", None)]\n',
            '        \n',
            '        choices = []\n',
            '        for project in projects:\n',
            '            metadata = project.get("metadata")\n',
            '            if metadata:\n',
            '                project_type = metadata.get("project_type", "unknown")\n',
            '                display_name = f"📁 {project[\'name\']} ({project_type}) - {project[\'audio_count\']} files"\n',
            '            else:\n',
            '                display_name = f"📁 {project[\'name\']} (no metadata) - {project[\'audio_count\']} files"\n',
            '            choices.append((display_name, project[\'name\']))\n',
            '        \n',
            '        return choices\n',
            '        \n'
        ])
        # Skip the broken lines until we find the except block
        while i < len(lines) and not lines[i].strip().startswith("except Exception as e:"):
            i += 1
        continue
    
    fixed_lines.append(line)
    i += 1

# Write the fixed content
with open('gradio_tts_app_audiobook.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print("✅ Quick syntax fix applied!") 