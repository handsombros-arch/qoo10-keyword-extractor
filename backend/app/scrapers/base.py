from app.browser.manager import BrowserManager
from app.services.task_manager import TaskManager


class BaseScraper:
    def __init__(self, browser: BrowserManager, tasks: TaskManager):
        self.browser = browser
        self.tasks = tasks

    async def run(self, **params) -> dict:
        raise NotImplementedError
