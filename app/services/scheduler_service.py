"""
Scheduler service for proactive behavior.
This is a foundation for:
- Morning summaries
- Advance reminders (3 days, 1 day before)
- Daily task summaries
- Price drop notifications

Note: This is a basic implementation. For production, consider using:
- APScheduler
- Celery + Redis
- Background tasks with FastAPI
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from app.repositories.reminder_repository import ReminderRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.line_service import reply_message

logger = logging.getLogger(__name__)

reminder_repo = ReminderRepository()
task_repo = TaskRepository()
user_repo = UserRepository()


class SchedulerService:
    """
    Scheduler for proactive assistant behavior.
    """
    
    def __init__(self):
        self.is_running = False
        self.check_interval = 60  # Check every 60 seconds
    
    async def start(self):
        """Start the scheduler."""
        self.is_running = True
        logger.info("Scheduler started")
        while self.is_running:
            try:
                await self.check_and_send_reminders()
                await self.check_daily_summaries()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """Stop the scheduler."""
        self.is_running = False
        logger.info("Scheduler stopped")
    
    async def check_and_send_reminders(self):
        """Check for due reminders and send them."""
        try:
            due_reminders = reminder_repo.get_due_reminders()
            if not due_reminders.data:
                return
            
            for reminder in due_reminders.data:
                user_id = reminder.get("user_id")
                message = reminder.get("message")
                reminder_id = reminder.get("id")
                
                # Get user's LINE ID
                user_result = user_repo.get_by_line_user_id(user_id)
                if not user_result.data:
                    continue
                
                line_user_id = user_result.data[0].get("line_user_id")
                
                if line_user_id:
                    # Format and send reminder
                    reminder_text = f"🔔 พลาดไม่ได้!\n\n{message}"
                    logger.info(f"Sending reminder to {line_user_id}: {message}")
                
                # Mark as sent
                reminder_repo.mark_sent(reminder_id)
                
        except Exception as e:
            logger.error(f"Error checking reminders: {e}")
    
    async def check_daily_summaries(self):
        """
        Check if it's time for daily summaries.
        This runs every minute but only sends at configured times.
        """
        now = datetime.now()
        
        # Morning summary at 7:00 AM
        if now.hour == 7 and now.minute == 0:
            await self.send_morning_summaries()
        
        # Evening summary at 9:00 PM
        if now.hour == 21 and now.minute == 0:
            await self.send_evening_summaries()
    
    async def send_morning_summaries(self):
        """Send morning task summaries to all users."""
        try:
            all_users = user_repo.get_all()
            if not all_users.data:
                return
            
            for user in all_users.data:
                user_id = user.get("id")
                line_user_id = user.get("line_user_id")
                display_name = user.get("display_name", "คุณ")
                
                # Get pending tasks
                tasks_result = task_repo.get_by_user_id(str(user_id))
                if not tasks_result.data:
                    continue
                
                pending_tasks = [t for t in tasks_result.data if t.get("status") == "pending"]
                
                if pending_tasks:
                    task_list = "\n".join([f"• {t.get('title', '')}" for t in pending_tasks[:5]])
                    message = f"🌅 สวัสดีครับ {display_name}!\n\nวันนี้มีงานที่ต้องทำ:\n{task_list}"
                else:
                    message = f"🌅 สวัสดีครับ {display_name}!\n\nวันนี้ไม่มีงานที่ต้องทำ! สบายๆ ครับ ✅"
                
                logger.info(f"Sending morning summary to {line_user_id}")
        
        except Exception as e:
            logger.error(f"Error sending morning summaries: {e}")
    
    async def send_evening_summaries(self):
        """Send evening summaries to all users."""
        try:
            all_users = user_repo.get_all()
            if not all_users.data:
                return
            
            for user in all_users.data:
                user_id = user.get("id")
                line_user_id = user.get("line_user_id")
                display_name = user.get("display_name", "คุณ")
                
                # Get pending tasks
                tasks_result = task_repo.get_by_user_id(str(user_id))
                if not tasks_result.data:
                    continue
                
                pending_tasks = [t for t in tasks_result.data if t.get("status") == "pending"]
                completed_tasks = [t for t in tasks_result.data if t.get("status") == "done"]
                
                message = f"🌙 รายสรุปประจำวันครับ {display_name}:\n\n"
                message += f"✅ งานที่เสร็จแล้ว: {len(completed_tasks)} งาน\n"
                message += f"⏳ งานที่เหลือ: {len(pending_tasks)} งาน\n"
                
                if pending_tasks:
                    message += f"\nยังเหลือ: {pending_tasks[0].get('title', '')}"
                
                logger.info(f"Sending evening summary to {line_user_id}")
        
        except Exception as e:
            logger.error(f"Error sending evening summaries: {e}")
    
    async def check_upcoming_reminders(self, days_ahead: int = 3):
        """Check and send advance reminders."""
        try:
            from datetime import datetime, timedelta
            
            # This would check for items expiring or events coming up
            # Implementation depends on specific use cases
            pass
        
        except Exception as e:
            logger.error(f"Error checking upcoming reminders: {e}")


# Global scheduler instance
scheduler = SchedulerService()


async def run_scheduler():
    """Run the scheduler in background."""
    await scheduler.start()


def start_scheduler_background():
    """Start scheduler in background thread/loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(run_scheduler())
        else:
            loop.run_until_complete(run_scheduler())
    except RuntimeError:
        # No event loop, create new one
        asyncio.run(run_scheduler())
