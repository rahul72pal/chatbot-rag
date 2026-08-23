import contextvars

current_user_id = contextvars.ContextVar("current_user_id", default=None)
current_chatbot_id = contextvars.ContextVar("current_chatbot_id", default=None)
current_llm_config = contextvars.ContextVar("current_llm_config", default=None)
