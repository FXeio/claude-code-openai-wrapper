import base64
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from src.models import Message, ContentPart
import re


class MessageAdapter:
    """Converts between OpenAI message format and Claude Code prompts."""

    @staticmethod
    def messages_to_prompt(messages: List[Message]) -> tuple[str, Optional[str]]:
        """
        Convert OpenAI messages to Claude Code prompt format.
        Returns (prompt, system_prompt)
        """
        system_prompt = None
        conversation_parts = []

        for message in messages:
            if message.role == "system":
                # Use the last system message as the system prompt
                system_prompt = message.content
            elif message.role == "user":
                conversation_parts.append(f"Human: {message.content}")
            elif message.role == "assistant":
                conversation_parts.append(f"Assistant: {message.content}")

        # Join conversation parts
        prompt = "\n\n".join(conversation_parts)

        # If the last message wasn't from the user, add a prompt for assistant
        if messages and messages[-1].role != "user":
            prompt += "\n\nHuman: Please continue."

        return prompt, system_prompt

    MIME_TO_EXT = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }

    @staticmethod
    def extract_and_save_images(
        messages: List[Message],
    ) -> Tuple[str, Optional[str], List[Path]]:
        """
        Process messages: extract images to temp files, build prompt text.
        Returns (prompt, system_prompt, temp_image_files).
        """
        system_prompt = None
        conversation_parts = []
        temp_files = []

        for message in messages:
            if message.role == "system":
                system_prompt = message.content if isinstance(message.content, str) else ""
                continue

            # If content is a list, it may contain images
            if isinstance(message.content, list):
                text_parts = []
                for part in message.content:
                    if isinstance(part, ContentPart):
                        if part.type == "text" and part.text:
                            text_parts.append(part.text)
                        elif part.type == "image_url" and part.image_url:
                            path = MessageAdapter._save_image(part.image_url.url)
                            if path:
                                temp_files.append(path)
                                text_parts.append(f"[See attached image: {path.name}]")
                    elif isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            path = MessageAdapter._save_image(url)
                            if path:
                                temp_files.append(path)
                                text_parts.append(f"[See attached image: {path.name}]")

                content_text = "\n".join(text_parts)
            else:
                content_text = message.content

            role_prefix = "Human" if message.role == "user" else "Assistant"
            conversation_parts.append(f"{role_prefix}: {content_text}")

        prompt = "\n\n".join(conversation_parts)

        if messages and messages[-1].role != "user":
            prompt += "\n\nHuman: Please continue."

        return prompt, system_prompt, temp_files

    @staticmethod
    def _save_image(url: str) -> Optional[Path]:
        """Save a data URI image to a temp file. Returns the file path."""
        if not url.startswith("data:"):
            import logging
            logging.getLogger(__name__).warning(f"Skipping non-data-URI image URL (not yet supported): {url[:80]}")
            return None

        try:
            # Parse "data:image/png;base64,iVBOR..."
            header, b64_data = url.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]
            ext = MessageAdapter.MIME_TO_EXT.get(mime_type, ".png")

            image_bytes = base64.b64decode(b64_data)
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=ext, prefix="claude_img_"
            )
            tmp.write(image_bytes)
            tmp.close()
            return Path(tmp.name)
        except Exception:
            return None

    @staticmethod
    def filter_content(content: str) -> str:
        """
        Filter content for unsupported features and tool usage.
        Remove thinking blocks and tool calls.
        """
        if not content:
            return content

        # Remove thinking blocks (common when tools are disabled but Claude tries to think)
        thinking_pattern = r"<thinking>.*?</thinking>"
        content = re.sub(thinking_pattern, "", content, flags=re.DOTALL)

        # Extract content from attempt_completion blocks (these contain the actual user response)
        attempt_completion_pattern = r"<attempt_completion>(.*?)</attempt_completion>"
        attempt_matches = re.findall(attempt_completion_pattern, content, flags=re.DOTALL)
        if attempt_matches:
            # Use the content from the attempt_completion block
            extracted_content = attempt_matches[0].strip()

            # If there's a <result> tag inside, extract from that
            result_pattern = r"<result>(.*?)</result>"
            result_matches = re.findall(result_pattern, extracted_content, flags=re.DOTALL)
            if result_matches:
                extracted_content = result_matches[0].strip()

            if extracted_content:
                content = extracted_content
        else:
            # Remove other tool usage blocks (when tools are disabled but Claude tries to use them)
            tool_patterns = [
                r"<read_file>.*?</read_file>",
                r"<write_file>.*?</write_file>",
                r"<bash>.*?</bash>",
                r"<search_files>.*?</search_files>",
                r"<str_replace_editor>.*?</str_replace_editor>",
                r"<args>.*?</args>",
                r"<ask_followup_question>.*?</ask_followup_question>",
                r"<attempt_completion>.*?</attempt_completion>",
                r"<question>.*?</question>",
                r"<follow_up>.*?</follow_up>",
                r"<suggest>.*?</suggest>",
            ]

            for pattern in tool_patterns:
                content = re.sub(pattern, "", content, flags=re.DOTALL)

        # Strip markdown code fences that wrap the entire response
        # (e.g. ```json\n{...}\n``` ) — these break clients expecting raw content
        content = MessageAdapter.strip_markdown_code_fences(content)

        # Clean up extra whitespace and newlines
        content = re.sub(r"\n\s*\n\s*\n", "\n\n", content)  # Multiple newlines to double
        content = content.strip()

        # If content is now empty or only whitespace, provide a fallback
        if not content or content.isspace():
            return "I understand you're testing the system. How can I help you today?"

        return content

    @staticmethod
    def strip_markdown_code_fences(content: str) -> str:
        """
        Strip markdown code fences that wrap the entire response content.
        E.g. ```json\n{...}\n``` -> {...}
        """
        if not content:
            return content
        stripped = content.strip()
        if stripped.startswith("```"):
            # Remove opening ``` line (with optional language tag)
            first_newline = stripped.find("\n")
            if first_newline == -1:
                return content
            # Check for closing ```
            if stripped.endswith("```"):
                inner = stripped[first_newline + 1:]
                # Remove trailing ```
                inner = inner[: -len("```")]
                return inner.strip()
        return content

    @staticmethod
    def format_claude_response(
        content: str, model: str, finish_reason: str = "stop"
    ) -> Dict[str, Any]:
        """Format Claude response for OpenAI compatibility."""
        return {
            "role": "assistant",
            "content": content,
            "finish_reason": finish_reason,
            "model": model,
        }

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Rough estimation of token count.
        OpenAI's rule of thumb: ~4 characters per token for English text.
        """
        return len(text) // 4
