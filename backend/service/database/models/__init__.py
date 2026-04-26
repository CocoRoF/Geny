"""
Models Module Initialization

Registers all model classes and provides the APPLICATION_MODELS list.
To add a new model:
1. Create a new file in models/
2. Import it here and add to APPLICATION_MODELS
-> It will automatically become a target for table creation and migration.
"""
from service.database.models.base_model import BaseModel
from service.database.models.persistent_config import PersistentConfigModel
from service.database.models.session import SessionModel
from service.database.models.chat_room import ChatRoomModel
from service.database.models.chat_message import ChatMessageModel
from service.database.models.session_log import SessionLogModel
from service.database.models.session_memory_entry import SessionMemoryEntryModel
from service.database.models.admin_user import AdminUserModel
from service.database.models.background_task import (
    BackgroundTaskModel,
    BackgroundTaskOutputModel,
)
from service.database.models.cron_job import CronJobModel

__all__ = [
    'BaseModel',
    'PersistentConfigModel',
    'SessionModel',
    'ChatRoomModel',
    'ChatMessageModel',
    'SessionLogModel',
    'SessionMemoryEntryModel',
    'AdminUserModel',
    'BackgroundTaskModel',
    'BackgroundTaskOutputModel',
    'CronJobModel',
]

# List of models used by the application
# All models registered here will automatically have their tables created at app startup
# and will be migrated with ALTER TABLE when schema changes are detected.
APPLICATION_MODELS = [
    PersistentConfigModel,
    SessionModel,
    ChatRoomModel,
    ChatMessageModel,
    SessionLogModel,
    SessionMemoryEntryModel,
    AdminUserModel,
    BackgroundTaskModel,
    BackgroundTaskOutputModel,
    CronJobModel,
]
