import os
from typing import Optional
from app.core.logger import logger

class PromptService:
    """Service to load and manage the system prompt configuration with custom behavior injection."""
    
    def __init__(self, prompt_path: str = "app/prompts/system_prompt.txt"):
        self.prompt_path = prompt_path
        self._system_prompt: str = ""
        self._load_prompt()

    def _load_prompt(self) -> None:
        """Synchronously reads and caches the system prompt template from the filesystem."""
        resolved_path = self.prompt_path
        
        if not os.path.isabs(resolved_path):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            resolved_path = os.path.join(project_root, self.prompt_path)
            
        logger.info(f"Attempting to load system prompt from: {resolved_path}")
        
        if not os.path.exists(resolved_path):
            logger.warning(f"System prompt file not found at {resolved_path}. Using fallback system prompt template.")
            self._system_prompt = (
                "You are Your Chatbot Agent, a helpful, professional, and friendly AI assistant.\n\n"
                "## Current Context\nToday's date and time is: {current_time_str}\n\n"
                "## Custom Chatbot Behavior\n{{behavior}}"
            )
            return

        try:
            with open(resolved_path, "r", encoding="utf-8") as file:
                self._system_prompt = file.read().strip()
            logger.info("System prompt template successfully loaded and cached in memory.")
        except Exception as exc:
            logger.error(f"Failed to read system prompt file: {exc}. Using fallback system prompt.")
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
