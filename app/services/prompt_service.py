import os
from typing import Optional
from app.core.logger import logger

class PromptService:
    """Service to load and manage the system prompt configuration with custom behavior injection."""
    
    def __init__(self, prompt_path: str = "app/prompts/system_prompt.txt"):
        self.prompt_path = prompt_path
        self._resolved_path: Optional[str] = None
        self._last_mtime: float = 0.0
        self._system_prompt: str = ""
        self._load_prompt()

    def _get_resolved_path(self) -> str:
        if self._resolved_path:
            return self._resolved_path
        resolved_path = self.prompt_path
        if not os.path.isabs(resolved_path):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            resolved_path = os.path.join(project_root, self.prompt_path)
        self._resolved_path = resolved_path
        return resolved_path

    def _load_prompt(self) -> None:
        """Synchronously reads and caches the system prompt template from the filesystem if changed."""
        resolved_path = self._get_resolved_path()
        
        if not os.path.exists(resolved_path):
            if not self._system_prompt:
                logger.warning(f"System prompt file not found at {resolved_path}. Using fallback system prompt template.")
                self._system_prompt = (
                    "You are Your Chatbot Agent, a helpful, professional, and friendly AI assistant.\n\n"
                    "## Current Context\nToday's date and time is: {current_time_str}\n\n"
                    "## Custom Chatbot Behavior\n{{behavior}}"
                )
            return

        try:
            mtime = os.path.getmtime(resolved_path)
            if mtime != self._last_mtime:
                with open(resolved_path, "r", encoding="utf-8") as file:
                    self._system_prompt = file.read().strip()
                self._last_mtime = mtime
                logger.info(f"System prompt template loaded from {resolved_path} (mtime: {mtime}).")
        except Exception as exc:
            logger.error(f"Failed to read system prompt file: {exc}.")
            if not self._system_prompt:
                self._system_prompt = (
                    "You are Your Chatbot Agent, a helpful, professional, and friendly AI assistant.\n\n"
                    "## Current Context\nToday's date and time is: {current_time_str}\n\n"
                    "## Custom Chatbot Behavior\n{{behavior}}"
                )

    def get_system_prompt(self, behavior: Optional[str] = None) -> str:
        """
        Returns the complete system prompt, replacing {{behavior}} with user instructions
        and {current_time_str} with current datetime.
        """
        self._load_prompt()

        print("behavior ===>", behavior)
        from datetime import datetime
        try:
            import pytz
            now = datetime.now(pytz.timezone("Asia/Kolkata"))
        except Exception:
            now = datetime.utcnow()

        current_time_str = now.strftime("%A, %d %B %Y, %I:%M %p %Z")
        prompt = self._system_prompt

        # Inject behavior instructions
        user_behavior = behavior.strip() if (behavior and str(behavior).strip()) else "Be helpful, professional, and friendly."
        if "{{behavior}}" in prompt:
            prompt = prompt.replace("{{behavior}}", user_behavior)
        else:
            prompt = f"{prompt}\n\n## Custom Chatbot Behavior\n{user_behavior}"

        # Inject current datetime
        if "{current_time_str}" in prompt:
            prompt = prompt.replace("{current_time_str}", current_time_str)

        return prompt
