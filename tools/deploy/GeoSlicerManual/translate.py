"""Translates markdown files using the Gemini API.

This script translates markdown files from a source directory to a target directory in a specified language.
It preserves markdown formatting, code blocks, URLs, and Jinja templates.

Usage:
    python translate.py --input-path <file_or_folder> --output-dir <output_directory> --language <target_language>
"""

import argparse
import os
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from google import genai

# Translation prompt
PROMPT_TEMPLATE = """
Translate the following markdown text into {language}.

**Instructions:**
- Keep the original markdown formatting.
- Do not translate URLs, file paths, or code blocks (```).
- Do not translate HTML tags.
- Do not translate any text within Jinja braces (e.g., {{...}}).
- Translate the text content accurately and naturally.

**Original Text:**
{text}
"""


def translate_text(text: str, language: str) -> Optional[str]:
    """Translates the given text to the specified language using the Gemini API.

    Args:
        text: The text to translate.
        language: The target language for translation.

    Returns:
        The translated text, or None if translation fails.
    """
    prompt = PROMPT_TEMPLATE.format(text=text, language=language)
    client = genai.Client()

    response = None
    for _ in range(3):
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

    if not response:
        return None

    return response.text


def run(args: argparse.Namespace) -> None:
    """Main function to handle file translation.

    Args:
        args: Command-line arguments.
    """
    # Load environment variables from .env file
    repository_root: Path = Path(__file__).parents[3]
    load_dotenv(dotenv_path=repository_root / ".env")
    api_key: Optional[str] = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env file.")
        return

    input_path: Path = Path(args.input_path)
    output_dir: Path = Path(args.output_dir)
    language: str = args.language

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    files_to_translate: List[Path]
    if input_path.is_file():
        files_to_translate = [input_path]
    else:
        files_to_translate = list(input_path.rglob("*.md"))

    print(f"⚙️  Translating {len(files_to_translate)} files...")
    for file_path in files_to_translate:
        # Determine output path
        relative_path: Path
        if input_path.is_file():
            relative_path = Path(file_path.name)
        else:
            relative_path = file_path.relative_to(input_path)

        output_file_path: Path = output_dir / relative_path
        output_file_path.parent.mkdir(parents=True, exist_ok=True)

        if args.skip_existing and output_file_path.exists():
            print(f"  ❗ File '{output_file_path}' already exists. Skipping...")
            continue

        if not args.force and output_file_path.exists():
            user_input = input(f"  ❓ File '{output_file_path}' already exists. Continue? [y/n] ")
            if user_input.lower() != "y":
                continue

        print(f"  🔧 Translating '{file_path}'...")
        with open(file_path, "r", encoding="utf-8") as f:
            original_text: str = f.read()

        translated_text: Optional[str] = translate_text(original_text, language)
        if not translated_text:
            print(f"    ❌ Translation failed for '{file_path}'")
            continue

        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write(translated_text)
        print(f"    ✅ Saved translated file to '{output_file_path}'")

        time.sleep(1)


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Translate markdown files using Gemini.")
    parser.add_argument("--input-path", "-i", required=True, help="File or folder to translate.")
    parser.add_argument("--output-dir", "-o", required=True, help="Directory to save translated files.")
    parser.add_argument("--language", "-l", required=True, help="Target language for translation.")
    parser.add_argument("--force", "-f", action="store_true", help="Force translation even if output file exists.")
    parser.add_argument(
        "--skip-existing", "-s", action="store_true", help="Skip translation for files that already have translations."
    )
    cli_args = parser.parse_args()

    run(cli_args)
