import urllib.parse
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

class MongoDB:
    def __init__(self):
        self.client = None

    def init(self, mongo_url: str):
        if self.client is None:
            # Escape mongo_url credentials if needed
            if mongo_url and "://" in mongo_url:
                try:
                    scheme, rest = mongo_url.split("://", 1)
                    if "@" in rest:
                        creds, host = rest.rsplit("@", 1)
                        if ":" in creds:
                            username, password = creds.split(":", 1)
                            safe_username = urllib.parse.quote_plus(urllib.parse.unquote(username))
                            safe_password = urllib.parse.quote_plus(urllib.parse.unquote(password))
                            mongo_url = f"{scheme}://{safe_username}:{safe_password}@{host}"
                except Exception:
                    pass
            self.client = AsyncIOMotorClient(mongo_url)

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    @property
    def database(self):
        if self.client is None:
            raise RuntimeError("Database client is not initialized. Call init() first.")
        return self.client[settings.DATABASE_NAME]

    @property
    def users_collection(self):
        return self.database["users"]

    @property
    def chatbots_collection(self):
        return self.database["chatbots"]

    @property
    def conversations_collection(self):
        return self.database["conversations"]

    @property
    def messages_collection(self):
        return self.database["messages"]

    @property
    def user_llm_configs_collection(self):
        return self.database["user_llm_configs"]

db = MongoDB()