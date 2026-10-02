"""
Pub/Sub Client

Handles publishing messages to Google Cloud Pub/Sub topics:
- geo-tasks-pending: Tasks ready for dispatch
- geo-cloro-callbacks: Cloro API callback results
"""
import json
import logging
from google.cloud import pubsub_v1
from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PubSubService:
    """Pub/Sub Service for message publishing"""
    
    def __init__(self):
        self.project_id = settings.PUBSUB_PROJECT_ID
        self.publisher = pubsub_v1.PublisherClient()
        
        # Topic: geo-cloro-callbacks (Cloro callback results)
        self.callbacks_topic = settings.PUBSUB_CALLBACKS_TOPIC
        self.callbacks_topic_path = self.publisher.topic_path(self.project_id, self.callbacks_topic)
        
        # Topic: geo-tasks-pending (Tasks ready for dispatch)
        self.tasks_topic = settings.PUBSUB_TASKS_TOPIC
        self.tasks_topic_path = self.publisher.topic_path(self.project_id, self.tasks_topic)

    def publish_callback_message(self, task_id: str, payload: dict, task_meta: dict = None):
        """
        Publishes Cloro callback data to geo-cloro-callbacks topic.
        Used by CloroCallback service to buffer incoming callbacks.
        
        Args:
            task_id: The task UUID string
            payload: The Cloro response payload
            task_meta: Optional task metadata
        """
        message_data = {
            "task_id": task_id,
            "payload": payload
        }
        if task_meta:
            message_data["task_meta"] = task_meta
            
        data = json.dumps(message_data).encode("utf-8")
        
        try:
            future = self.publisher.publish(self.callbacks_topic_path, data)
            message_id = future.result()
            logger.info(f"Published callback message {message_id} for task {task_id}")
            return message_id
        except Exception as e:
            logger.error(f"Failed to publish callback for task {task_id}: {e}")
            raise

    def publish_dispatch_message(self, task_id: str, request_id: str = None):
        """
        Publishes a task dispatch message to geo-tasks-pending topic.
        Used by PromptExpander to trigger CloroDispatcher.
        
        Args:
            task_id: The task UUID to dispatch
            request_id: Optional request UUID for tracking
        """
        message_data = {
            "task_id": task_id,
            "action": "dispatch"
        }
        if request_id:
            message_data["request_id"] = request_id
            
        data = json.dumps(message_data).encode("utf-8")
        
        try:
            future = self.publisher.publish(
                self.tasks_topic_path, 
                data,
                task_id=task_id
            )
            message_id = future.result()
            logger.debug(f"Published dispatch message {message_id} for task {task_id}")
            return message_id
        except Exception as e:
            logger.error(f"Failed to publish dispatch for task {task_id}: {e}")
            raise

    def publish_dispatch_batch(self, task_ids: list, request_id: str = None) -> int:
        """
        Publishes multiple dispatch messages in batch.
        
        Args:
            task_ids: List of task UUIDs to dispatch
            request_id: Optional request UUID for tracking
            
        Returns:
            int: Number of successfully published messages
        """
        success_count = 0
        futures = []
        
        for task_id in task_ids:
            message_data = {
                "task_id": task_id,
                "action": "dispatch"
            }
            if request_id:
                message_data["request_id"] = request_id
                
            data = json.dumps(message_data).encode("utf-8")
            
            try:
                future = self.publisher.publish(
                    self.tasks_topic_path,
                    data,
                    task_id=task_id
                )
                futures.append((task_id, future))
            except Exception as e:
                logger.error(f"Failed to queue dispatch for task {task_id}: {e}")
        
        # Wait for all futures
        for task_id, future in futures:
            try:
                future.result()
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to publish dispatch for task {task_id}: {e}")
        
        logger.info(f"Published {success_count}/{len(task_ids)} dispatch messages for request {request_id}")
        return success_count
    
    # Legacy method name for backward compatibility
    def publish_message(self, task_id: str, payload: dict, task_meta: dict = None):
        """Deprecated: Use publish_callback_message instead"""
        return self.publish_callback_message(task_id, payload, task_meta)