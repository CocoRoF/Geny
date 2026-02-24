# Prompts Directory

This directory contains system prompt templates for Claude sessions.

## How to Use

1. Create a new `.md` file in this directory
2. The filename (without extension) will be used as the prompt name in the UI
3. The entire file content will be used as the system prompt

## File Format

Each file should contain the system prompt in Markdown format. The prompt will be passed directly to Claude when creating a session.

## Examples

- `worker.md` - General worker prompt focused on task completion
- `developer.md` - Software development focused prompt
- `researcher.md` - Research and analysis focused prompt

## Tips

- Use clear and specific instructions
- Structure prompts with headers and bullet points
- Define the AI's role and expected behavior
- Include any constraints or guidelines
